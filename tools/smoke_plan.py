"""🎬 動画化予定の動作確認（ヘッドレス、localhost だけ）。試し用に作った作品で流す（ユーザーの作品で流さない）。
  <Playwright の python> -X utf8 tools\\smoke_plan.py <URL> --timeline <作品>\\<名前>.cut.json [--phase 2]
作品の準備：assets/images/room.png、assets/characters/kurochan.png、characters.json に kurochan（smoke_plan.py --prepare <作品> で作る）。
第2段階：参照のチップ（@import の読み取り・番号・だめなものは赤）・「＋キャラ」・キャラの外見と差分。
--phase 3：開始の絵を本当に生成する（Codex CLI。1〜3分。使用量がかかる）→ テイクが入る → もう1本頼んですぐ止める。
--phase 4 --fake-drive <フォルダ>：動画化（H3 は動かさない）。サーバーは環境変数 MITTLER_MYDRIVE・MITTLER_H3_ROOT をこの偽のドライブ（一時フォルダ）に向けて起動しておく。
  inbox に依頼の YAML → 模擬の H3（下の mock_h3：docs/H3受け渡し契約.md の形かを確かめて、outbox に模擬の result.json と動画を置く）→ テイク → 採用で映像トラック → 1コマに映る。
  → 止める：もう1本頼んで、H3 の順番待ちのあいだに止める（置いた依頼は inbox に残る）。
--phase 5 --fake-drive …：第4段階のあと、声の参照（ref2va）。TTS のクリップ（試しの wav）→ audio(here) で口パクの依頼（mode ref2va・声の wav）→ 模擬の H3 で形を確かめる。
  声なしの ref2va・声つきの fl2va は、頼む前に止まる。
H3 のランナーは Mittler の外にあり、ここからは動かさない（受け渡しの形は docs/H3受け渡し契約.md だけ）。
"""
import argparse
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ap = argparse.ArgumentParser(); ap.add_argument('url', nargs='?'); ap.add_argument('--timeline'); ap.add_argument('--prepare'); ap.add_argument('--image')
ap.add_argument('--shot'); ap.add_argument('--phase', type=int, default=2); ap.add_argument('--fake-drive')
a = ap.parse_args()

if a.prepare:  # 作品に試しの素材とキャラを置く
    d = Path(a.prepare)
    for rel in ('assets/images/room.png', 'assets/characters/kurochan.png'):
        (d / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy(a.image, d / rel)
    (d / 'characters.json').write_text(json.dumps({'characters': [{'id': 'kurochan', 'name': 'テトちゃん','image': 'assets/characters/kurochan.png',
        'profile': '余裕がある自信家', 'look': '', 'color': '#b25ad6', 'tts': {'default_engine': 'gemini', 'gemini': {}, 'voicevox': {}}}]}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('prepared', d); sys.exit(0)

from playwright.sync_api import sync_playwright  # noqa: E402

if not a.url.startswith(('http://127.0.0.1:', 'http://localhost:')): sys.exit('localhost only')
tlf = Path(a.timeline); proj = tlf.parent
first = json.loads(tlf.read_text(encoding='utf-8')); chars0 = (proj / 'characters.json').read_bytes()
fails, errors = [], []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


def saved(pg):
    pg.wait_for_function("() => !window.MITTLER_EDITOR.saveTimer && !window.MITTLER_EDITOR.saving", timeout=60000); time.sleep(0.4)
    return json.loads(tlf.read_text(encoding='utf-8'))


def chips(pg, which):
    return pg.eval_on_selector_all(f'#sel .planSec[data-which="{which}"] .chip', 'els => els.map(e => ({t: e.textContent.trim(), bad: e.classList.contains("bad"), img: !!e.querySelector("img"), n: (e.querySelector("b") || {}).textContent || ""}))')


def frame_sha(pg, t):
    pg.evaluate(f'window.MITTLER_EDITOR.seek({t})')
    pg.wait_for_function(f"() => {{ const S = window.MITTLER_EDITOR, i = document.getElementById('frameImg'); return !i.hidden && i.complete && S.exactT === {t} && S.shownVer === S.ver && !S.saveTimer && !S.saving; }}", timeout=240000)
    return pg.evaluate("""async () => { const i = document.getElementById('frameImg'); const b = await (await fetch(i.src)).arrayBuffer();
      const h = await crypto.subtle.digest('SHA-256', b); return [...new Uint8Array(h)].map(x => x.toString(16).padStart(2, '0')).join(''); }""")


# ---- 模擬の H3（ランナーの代わり）：アダプタが inbox に置いた依頼の YAML を読み、docs/H3受け渡し契約.md の形かを確かめて、模擬の結果を返す ----
CONTRACT_KEYS = ['project', 'id', 'image', 'last_image', 'prompt', 'seconds', 'orientation', 'mode', 'ref_images', 'audio', 'audio_start', 'audio_seconds',
                 'ref_image_size', 'scheduler', 'steps', 'seed', 'fit', 'gen_seconds', 'lyrics', 'sing_start', 'sing_end']


def read_request(y):
    """依頼の YAML：2行のコメント＋1行に1つ「キー: JSON の値」（契約の 5章）"""
    raw = y.read_bytes()
    lines = raw.decode('utf-8').splitlines()
    fields = {}
    for ln in lines[2:]:
        k, v = ln.split(': ', 1)
        fields[k] = json.loads(v)
    return raw, lines, fields


def mock_h3(fake, y, deliver=True):
    """契約どおりかを確かめる（だめな点のリストを返す）。deliver なら outbox に模擬の result.json と動画（ComfyUI_output、Colab のパスで書く）を置く"""
    import subprocess
    raw, lines, f = read_request(y)
    bad = []
    if raw.startswith(b'\xef\xbb\xbf'):
        bad.append('BOM がある')
    if not (lines[0].startswith('# claude-cut') and lines[1].startswith('# 作品:')):  # 依頼の頭の行・素材フォルダ claude-cut-h3・project の cc_ は H3 との受け渡しの名前（改名のあとも変えていない）
        bad.append('頭の2行のコメントが無い')
    bad += [f'契約に無いキー {k}' for k in f if k not in CONTRACT_KEYS]
    order = [k for k in CONTRACT_KEYS if k in f]
    head = [k for k in f if k not in ('fit', 'gen_seconds', 'lyrics', 'sing_start', 'sing_end', 'seed', 'steps')]
    if head != [k for k in order if k in head]:
        bad.append(f'キーの並びが契約と違う {list(f)}')
    bad += [f'{k} が無い' for k in ('project', 'id', 'prompt', 'seconds', 'orientation', 'seed') if k not in f]
    if bad:
        return f, bad
    if y.name != f"{f['project']}__{f['id']}.yaml":
        bad.append(f'名前が <project>__<id>.yaml でない {y.name}')
    folder = f"claude-cut-h3/{f['project']}/{f['id']}/"
    for k in ('image', 'last_image', 'audio'):
        if k in f and not (f[k].startswith(folder) and (fake / f[k]).is_file()):
            bad.append(f'{k} が素材フォルダに無い {f[k]}')
    for r in f.get('ref_images', []):
        if not (r.startswith(folder) and (fake / r).is_file()):
            bad.append(f'ref_images が素材フォルダに無い {r}')
    if not (fake / folder / y.name).is_file() or (fake / folder / y.name).read_bytes() != raw:
        bad.append('素材フォルダに同じ中身の控えが無い')
    if not (isinstance(f['seconds'], (int, float)) and f['seconds'] > 0) or f['orientation'] not in ('landscape', 'portrait'):
        bad.append(f"seconds・orientation がおかしい {f['seconds']} {f['orientation']}")
    if f.get('mode') == 'ref2va':
        if not ('audio' in f and f.get('audio_start') == 0 and f.get('audio_seconds') == f['seconds'] and 'last_image' not in f and 'image' in f):
            bad.append('ref2va の audio・audio_start・audio_seconds・image・last_image がおかしい')
        if not all(k in f for k in ('ref_image_size', 'scheduler', 'steps')):
            bad.append('ref2va の既定（ref_image_size・scheduler・steps）が無い')
    elif 'mode' in f or 'audio' in f:
        bad.append('fl2va に mode・audio がある')
    if deliver and not bad:
        proj_name, vid = f['project'], f['id']
        mp4 = fake / 'ComfyUI_output' / 'MiniMax_H3' / proj_name / f'{vid}.mp4'; mp4.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=1344x768:rate=24', '-t', str(f['seconds']), '-pix_fmt', 'yuv420p', str(mp4)], check=True)
        ob = fake / 'H3_tasks' / 'outbox' / proj_name; ob.mkdir(parents=True, exist_ok=True)
        (ob / f'{vid}.result.json').write_text(json.dumps({'id': vid, 'project': proj_name, 'outputs': [f'/content/drive/MyDrive/ComfyUI_output/MiniMax_H3/{proj_name}/{vid}.mp4'],
            'settings': {'frames': round(f['seconds'] * 24), 'fps': 24, 'seed': f['seed']}, 'seconds_h3': 1, 'warnings': []}), encoding='utf-8')
    return f, bad


def phase4(pg, pc):
    import subprocess
    fake = Path(a.fake_drive); h3 = fake / 'H3_tasks'
    sec = '#sel .planSec[data-which="start_frame"]'; esec = '#sel .planSec[data-which="end_frame"]'; vsec = '#sel .planSec[data-which="video"]'
    pg.evaluate(f"window.MITTLER_EDITOR.select('{pc['id']}')"); pg.click('#paneTabs button[data-p="sel"]'); pg.wait_for_selector(vsec)
    pg.select_option(f'{sec} [data-f="src"]', 'assets/images/room.png'); saved(pg)
    pg.select_option(f'{esec} [data-f="src"]', 'assets/characters/kurochan.png'); saved(pg)
    pg.fill(f'{vsec} textarea', '@import char(kurochan) as クロ;\nクロ がゆっくり振り返って、窓の外を見る。')
    pg.dispatch_event(f'{vsec} textarea', 'change'); saved(pg)
    h_plan = frame_sha(pg, 4.0)  # 予定の仮の絵
    pg.click(f'{vsec} .gen')
    pg.wait_for_function(f"() => {{ const s = document.querySelector('{vsec} .jobst'); return s && /H3 の順番待ち/.test(s.textContent); }}", timeout=60000)
    ys = list((h3 / 'inbox').glob('*.yaml'))
    check(len(ys) == 1, f'H3 の inbox に依頼（{[y.name for y in ys]}）')
    y = ys[0]; text = y.read_text(encoding='utf-8')
    check('project: "cc_' in text and 'last_image:' in text and 'seconds: 5.167' in text and 'クロ：' in text,
          'YAML に project・開始と終了の絵・17k+5 の秒数・人物の外見')
    # 模擬の H3：依頼の形を契約で確かめて、outbox に結果、ComfyUI_output に動画（5.167 秒）を置く（ランナーは動かさない）
    fields, bad = mock_h3(fake, y)
    check(not bad, f'依頼の形が契約（docs/H3受け渡し契約.md）どおり {bad}')
    pg.wait_for_function(f"() => {{ const c = window.MITTLER_EDITOR.tl.tracks.flatMap(t => t.clips).find(c => c.id === '{pc['id']}'); return c && (c.video.takes || []).length > 0; }}", timeout=120000)
    tl = saved(pg); c = next(c for t in tl['tracks'] for c in t['clips'] if c['id'] == pc['id']); k = c['video']['takes'][-1]
    check((proj / k['src']).is_file() and abs(k['dur'] - 5.167) < 0.01, f"動画のテイク（{k['src']}・{k['dur']}秒）")
    pg.wait_for_selector(f'{vsec} .vtake .adopt'); pg.click(f'{vsec} .vtake .adopt')
    tl = saved(pg); c = next(c for t in tl['tracks'] for c in t['clips'] if c['id'] == pc['id'])
    vc = next((x for t in tl['tracks'] if t['kind'] == 'video' for x in t['clips'] if x.get('from_plan') == pc['id']), None)
    check(vc and c['video'].get('adopted') == vc['id'] and vc['src'] == [k['src']] and vc['start'] == c['start'], f'採用で映像トラックに置いた {vc and vc["id"]}')
    h_vid = frame_sha(pg, 4.0)
    check(h_vid != h_plan, f'採用した動画がプレビューに映る（{h_plan[:10]} → {h_vid[:10]}）')


def phase5(pg, pc):
    import subprocess
    fake = Path(a.fake_drive); h3 = fake / 'H3_tasks'
    vsec = '#sel .planSec[data-which="video"]'
    wav = proj / 'assets' / 'voice' / 'tts_test_t1.wav'; wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000', '-t', '2', '-ac', '2', str(wav)], check=True)
    pg.evaluate("""() => window.MITTLER_EDITOR.change(() => window.MITTLER_EDITOR.tl.tracks.push({ id: 't_tts_test', name: 'TTS テスト', kind: 'tts', character: 'kurochan',
      clips: [{ id: 'tts_test', type: 'tts', start: 2.5, dur: 2, character: 'kurochan', engine: 'voicevox', text: 'テスト', label: 'テスト',
        takes: [{ id: 't1', src: 'assets/voice/tts_test_t1.wav', dur: 2 }], activeTake: 't1', gain: 0, in: 0, fade_in: 0, fade_out: 0 }] }))""")
    saved(pg)
    pg.evaluate(f"window.MITTLER_EDITOR.select('{pc['id']}')"); pg.click('#paneTabs button[data-p="sel"]'); pg.wait_for_selector(vsec)
    def ask(prompt, engine):
        pg.select_option(f'{vsec} [data-v="engine"]', engine); saved(pg)
        pg.fill(f'{vsec} textarea', prompt); pg.dispatch_event(f'{vsec} textarea', 'change'); saved(pg)
        pg.click(f'{vsec} .gen'); time.sleep(1.5)
        return pg.text_content(f'{vsec} .jobst')
    t = ask('クロ がこちらを見て話す。', 'h3-ref2va')
    check('声の参照がちょうど1つ' in t, f'声なしの ref2va は頼む前に止まる（{t}）')
    t = ask('@import audio(here);\nクロ が話す。', 'h3-fl2va')
    check('fl2va は声の参照を使えない' in t, f'声つきの fl2va は頼む前に止まる（{t}）')
    before = set((h3 / 'inbox').glob('*.yaml'))
    t = ask('@import audio(here);\n@import char(kurochan) as クロ;\nクロ がこちらを見て、落ち着いた声で話す。', 'h3-ref2va')
    pg.wait_for_function(f"() => {{ const s = document.querySelector('{vsec} .jobst'); return s && /H3 の順番待ち|失敗/.test(s.textContent); }}", timeout=120000)
    t = pg.text_content(f'{vsec} .jobst')
    new = [y for y in (h3 / 'inbox').glob('*.yaml') if y not in before]
    check(len(new) == 1 and 'H3 の順番待ち' in t, f'ref2va の依頼を置いた（{t}・{[y.name for y in new]}）')
    if not new:
        return
    y = new[0]
    fields, bad = mock_h3(fake, y, deliver=False)  # 模擬の H3：契約の形か（ref2va）
    check(not bad, f'ref2va の依頼の形が契約（docs/H3受け渡し契約.md）どおり {bad}')
    voice = fake / fields.get('audio', 'x')
    d = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(voice)], capture_output=True, text=True).stdout or 0)
    check(fields.get('mode') == 'ref2va' and 'last_image' not in fields and voice.is_file() and abs(d - 5.0) < 0.05 and fields.get('audio_seconds') == 5.0
          and '<Picture 1> is the exact first frame.' in fields['prompt'] and len(fields.get('ref_images', [])) == 1,
          f"YAML（mode ref2va・声 {d:.2f} 秒＝クリップの時間の TTS・<Picture 1>・参照画像 {len(fields.get('ref_images', []))}）")
    check(fields.get('ref_image_size') == 'max' and fields.get('scheduler') == 'beta' and fields.get('steps') == 25 and isinstance(fields.get('seed'), int),
          f"ref2va の既定（ref_image_size {fields.get('ref_image_size')}・scheduler {fields.get('scheduler')}・steps {fields.get('steps')}・seed {fields.get('seed')}）")
    wav.unlink()


def phase_cancel(pg, pc):
    """止める：H3 の順番待ちの動画化を止める → 「止めた」。置いた依頼は inbox に残る（契約の 9章）。第4・5段階のあと
    （第5段階の ref2va の依頼が順番待ちならそれを、無ければもう1本頼んでから。順番待ちのあいだ「動画化」は押せない）"""
    vsec = '#sel .planSec[data-which="video"]'
    pg.evaluate(f"window.MITTLER_EDITOR.select('{pc['id']}')"); pg.click('#paneTabs button[data-p="sel"]'); pg.wait_for_selector(vsec)
    t0 = time.time()
    if not pg.is_disabled(f'{vsec} .gen.primary'):
        pg.click(f'{vsec} .gen.primary')
    else:
        t0 = 0
    pg.wait_for_function(f"() => {{ const s = document.querySelector('{vsec} .jobst'); return s && /H3 の順番待ち/.test(s.textContent); }}", timeout=60000)
    pg.wait_for_selector(f'{vsec} .genStop:not([hidden])', timeout=30000); pg.click(f'{vsec} .genStop')
    pg.wait_for_function(f"() => {{ const s = document.querySelector('{vsec} .jobst'); return s && /止めた/.test(s.textContent); }}", timeout=90000)
    js = [json.loads(f.read_text(encoding='utf-8')) for f in (proj / 'work' / 'jobs').glob('job_*.json')]
    j = max((x for x in js if x.get('kind') == 'video' and x.get('clip') == pc['id']), key=lambda x: x.get('created', ''))
    y = Path(((j.get('h3') or {}).get('yaml')) or 'x')
    # （名前 <クリップ>_t<n> はテイクの数から決まるので、まだテイクになっていない前の依頼と同じ名前になることがある。ここでは「この依頼が置かれて残っている」を見る）
    check(j.get('state') == 'cancelled' and 'H3 に置いた依頼は残る' in (j.get('note') or '') and y.is_file() and y.stat().st_mtime >= t0 - 2,
          f"動画化を止めた（{pg.text_content(f'{vsec} .jobst')}・{j.get('note')}）。置いた依頼は inbox に残る {y.name}")


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={'width': 1600, 'height': 940})
    pg.on('console', lambda m: errors.append(m.text + ' ' + str((m.location or {}).get('url', ''))[:120]) if m.type == 'error' else None)
    pg.on('response', lambda r: errors.append(f'{r.status} {r.url[:140]}') if r.status >= 400 else None)
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(a.url)
    pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl && window.MITTLER_EDITOR.assets && window.MITTLER_PLAN', timeout=60000)
    # 予定クリップ
    pg.evaluate("window.MITTLER_LANE_DBL(window.MITTLER_EDITOR.tl.tracks.find(t => t.kind === 'plan'), 2)")
    sec = '#sel .planSec[data-which="start_frame"]'
    pg.wait_for_selector(f'{sec} .addChar')
    # ＋キャラ → 宣言の行 → チップ（立ち絵のサムネと 参照画像1）
    pg.select_option(f'{sec} .addChar', 'kurochan')
    pg.wait_for_function(f"() => document.querySelectorAll('{sec} .chip').length === 1", timeout=20000)
    ta = pg.input_value(f'{sec} textarea'); cs = chips(pg, 'start_frame')
    check(ta.startswith('@import char(kurochan) as テトちゃん;') and cs[0]['img'] and cs[0]['n'] == '1', f'＋キャラで宣言の行とチップ {ta!r} {cs}')
    # 書いた参照：キャラ・画像・知らない種類 → 3つのチップ、だめなものは赤
    pg.fill(f'{sec} textarea', '@import char(kurochan) as クロ;\n@import image("assets/images/room.png") as 部屋;\n@import bogus(1);\nクロ が 部屋 の窓辺に立つ')
    pg.dispatch_event(f'{sec} textarea', 'input'); pg.dispatch_event(f'{sec} textarea', 'change')
    pg.wait_for_function(f"() => document.querySelectorAll('{sec} .chip').length === 3", timeout=20000)
    cs = chips(pg, 'start_frame')
    check([c['n'] for c in cs] == ['1', '2', ''] and [c['bad'] for c in cs] == [False, False, True], f'参照のチップ（番号・赤）{cs}')
    tl = saved(pg); pc = next(c for t in tl['tracks'] if t['kind'] == 'plan' for c in t['clips'])
    check('部屋' in pc['start_frame']['prompt'], 'プロンプトが保存された')
    # 声の参照は絵のプロンプトでは赤
    pg.fill(f'{sec} textarea', '@import audio(here);\n声'); pg.dispatch_event(f'{sec} textarea', 'input')
    pg.wait_for_function(f"() => {{ const c = document.querySelectorAll('{sec} .chip'); return c.length === 1 && c[0].classList.contains('bad'); }}", timeout=20000)
    check(True, '絵のプロンプトの audio(…) は赤')
    vsec = '#sel .planSec[data-which="video"]'
    pg.fill(f'{vsec} textarea', '@import audio(here);\n@import frame(start);\n振り返る'); pg.dispatch_event(f'{vsec} textarea', 'input')
    pg.wait_for_function(f"() => document.querySelectorAll('{vsec} .chip').length === 2", timeout=20000)
    cs = chips(pg, 'video')
    check(not cs[0]['bad'] and cs[1]['bad'], f'動画のプロンプトの audio(here) は使える・まだ無い開始の絵は赤 {cs}')
    # キャラの外見と差分（characters.json）
    pg.click('#assetTabs button[data-tab="chars"]')
    try:
        pg.wait_for_selector('#assetBody .char', timeout=10000)
    except Exception:
        print('tabs on:', pg.eval_on_selector_all('#assetTabs button.on', 'els => els.map(e => e.dataset.tab)'), 'focus:', pg.evaluate('document.activeElement.outerHTML.slice(0,80)'))
        print('assetBody:', pg.inner_html('#assetBody')[:400], 'chars:', pg.evaluate('JSON.stringify(window.MITTLER_EDITOR.chars)')[:300])
        raise
    pg.click('#assetBody .char')
    pg.wait_for_selector('#assetPreview [data-c="look"]')
    pg.fill('#assetPreview [data-c="look"]', '黒髪、黒いスーツ、細身')
    pg.click('#charVarAdd'); pg.fill('#assetPreview .variant .vk', 'smile')
    pg.select_option('#assetPreview .variant .vp', 'assets/images/room.png')
    pg.click('#charSave'); time.sleep(1.0)
    ch = json.loads((proj / 'characters.json').read_text(encoding='utf-8'))['characters'][0]
    check(ch.get('look') == '黒髪、黒いスーツ、細身' and ch.get('images') == {'smile': 'assets/images/room.png'}, f"キャラの外見と差分を保存 {ch.get('look')} {ch.get('images')}")
    # 差分の参照
    pg.evaluate(f"window.MITTLER_EDITOR.select('{pc['id']}')"); pg.click('#paneTabs button[data-p="sel"]')
    pg.wait_for_selector(f'{sec} textarea')
    pg.fill(f'{sec} textarea', '@import char(kurochan, smile) as クロ笑;\n@import char(kurochan, angry);\nクロ笑'); pg.dispatch_event(f'{sec} textarea', 'input')
    pg.wait_for_function(f"() => document.querySelectorAll('{sec} .chip').length === 2", timeout=20000)
    cs = chips(pg, 'start_frame')
    check(cs[0]['img'] and not cs[0]['bad'] and cs[1]['bad'], f'差分の参照（無い差分は赤）{cs}')
    if a.phase == 3:  # 第3段階：開始の絵を生成（ジョブ係 → Codex）→ テイク
        pg.fill(f'{sec} textarea', '@import char(kurochan) as クロ;\n@import image("assets/images/room.png") as 部屋;\nクロ が 部屋 の窓辺に立って、こちらを振り返る。夕方のやわらかい光。アニメ調。')
        pg.dispatch_event(f'{sec} textarea', 'change'); saved(pg)
        t0 = time.time(); pg.click(f'{sec} .gen')
        pg.wait_for_function(f"() => {{ const s = document.querySelector('{sec} .jobst'); return s && /順番待ち|生成中/.test(s.textContent); }}", timeout=30000)
        check(True, f"生成を頼んだ（{pg.text_content(f'{sec} .jobst')}）")
        pg.wait_for_function(f"() => {{ const c = window.MITTLER_EDITOR.tl.tracks.flatMap(t => t.clips).find(c => c.id === '{pc['id']}'); return c && (c.start_frame.takes || []).length > 0; }}", timeout=600000)
        tl = saved(pg); c = next(c for t in tl['tracks'] for c in t['clips'] if c['id'] == pc['id']); k = c['start_frame']['takes'][-1]
        f = proj / k['src']
        check(f.is_file() and c['start_frame']['src'] == k['src'] and k['engine'] == 'codex' and len(k['sent']['refs']) == 2,
              f"開始の絵ができてテイクに入った（{k['src']}・{time.time() - t0:.0f}秒・refs_ok {k.get('refs_ok')}・spec {k.get('spec_coverage')}・{k.get('warnings')}）")
        jobs = json.loads(urllib.request.urlopen(a.url.split('/editor')[0] + '/api/jobs').read())['jobs']
        check(any(j['state'] == 'done' and j.get('applied') for j in jobs), 'ジョブは done・applied')
        if a.shot:
            pg.screenshot(path=a.shot)
        # もう1本頼んで、すぐ止める
        pg.click(f'{sec} .gen')
        pg.wait_for_selector(f'{sec} .genStop:not([hidden])', timeout=30000); time.sleep(3)
        pg.click(f'{sec} .genStop')
        pg.wait_for_function(f"() => {{ const s = document.querySelector('{sec} .jobst'); return s && /止めた/.test(s.textContent); }}", timeout=60000)
        check(True, '生成を途中で止められる')
    elif a.shot:
        pg.screenshot(path=a.shot)
    if a.phase >= 4:
        phase4(pg, pc)
    if a.phase >= 5:
        phase5(pg, pc)
    if a.phase >= 4:
        phase_cancel(pg, pc)
    # 取り消しで戻す
    while pg.evaluate('window.MITTLER_EDITOR.undo.length') > 0:
        pg.click('#undo')
    tl = saved(pg)
    b.close()

check(tl == first, 'タイムラインの中身が最初と同じ（取り消しで戻った）')
(proj / 'characters.json').write_bytes(chars0)
check(not errors, 'コンソールエラーなし' + ('' if not errors else ': ' + ' | '.join(errors[:5])))
sys.exit(1 if fails else 0)
