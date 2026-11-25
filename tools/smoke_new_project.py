"""new_project.js で作ったばかりの作品で、編集画面がひととおり動くかの確認（ヘッドレス、localhost だけ。サーバーの PC で本当に描く）。
  <Playwright の python> -X utf8 tools\\smoke_new_project.py <URL> --timeline <作品>\\<名前>.cut.json
作品は試し用に作ったものを使う（ユーザーの作品で流さない）。assets/images に画像を1枚入れておくこと。
確かめること：空のタイムラインが開く（トラック4本・エラーなし）→ 最初の1コマ → 画像を置く → 字幕を足して文字を入れる（字の
ファイルが無くても Windows の字で描ける）→ 色の卓（カットが無いので全体）→ トラックの 👁（映像を隠すと絵が変わり、戻すと同じ絵）・🔈・シャイ 🫣 →
0〜3秒を書き出す（音のクリップが無くても）→ 取り消しで最初と同じ。
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(); ap.add_argument('url'); ap.add_argument('--timeline', required=True); ap.add_argument('--shot')
a = ap.parse_args()
if not a.url.startswith(('http://127.0.0.1:', 'http://localhost:')): sys.exit('localhost only')
tlf = Path(a.timeline); first = json.loads(tlf.read_text(encoding='utf-8'))
fails, errors = [], []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


def saved(pg):
    pg.wait_for_function("() => !window.MITTLER_EDITOR.saveTimer && !window.MITTLER_EDITOR.saving", timeout=60000); time.sleep(0.4)
    return json.loads(tlf.read_text(encoding='utf-8'))


def frame_sha(pg):
    return pg.evaluate("""async () => { const i = document.getElementById('frameImg'); const b = await (await fetch(i.src)).arrayBuffer();
      const h = await crypto.subtle.digest('SHA-256', b); return [...new Uint8Array(h)].map(x => x.toString(16).padStart(2, '0')).join(''); }""")


def fresh_frame(pg, t, timeout=240000):
    pg.wait_for_function(f"() => {{ const S = window.MITTLER_EDITOR, i = document.getElementById('frameImg'); return !i.hidden && S.exactT === {t} && S.shownVer === S.ver && !S.saveTimer && !S.saving; }}", timeout=timeout)


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={'width': 1600, 'height': 940})
    pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(a.url)
    pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl && window.MITTLER_EDITOR.assets', timeout=60000)
    # トラックの頭の印は Lucide のアイコン（2026-11-14〜。前は絵文字）：動画化予定は clapperboard
    heads = pg.eval_on_selector_all('#headList .head:not(.meta) .nm', "els => els.map(e => { const i = e.querySelector('.tk .ic'); return (i ? i.dataset.ic : '') + ' ' + e.textContent.trim(); })")
    check(len(heads) == 5 and any(h.startswith('clapperboard ') for h in heads), f'トラック {heads}')
    pg.evaluate('window.MITTLER_EDITOR.seek(1)')
    fresh_frame(pg, 1)
    check(True, '最初の1コマ（空のタイムライン）')
    # 画像を置く
    pg.click('#assetTabs button[data-tab="images"]'); pg.locator('#assetBody .acell').first.click()
    pg.wait_for_selector('#apImg'); pg.evaluate('window.MITTLER_EDITOR.seek(0)'); pg.click('#apImg')
    tl = saved(pg); img = [c for t in tl['tracks'] if t['kind'] == 'video' for c in t['clips']]
    check(len(img) == 1 and img[0]['type'] == 'image', f'画像を置けた {img and img[0].get("src")}')
    # 🎬 動画化予定：6秒のところにクリップ → スタートの絵を選ぶ → 映像が無い時刻では、その絵が仮に映る
    pg.evaluate("window.MITTLER_EDITOR.seek(6)"); fresh_frame(pg, 6); h_empty = frame_sha(pg)
    pg.evaluate("window.MITTLER_LANE_DBL(window.MITTLER_EDITOR.tl.tracks.find(t => t.kind === 'plan'), 5)")
    pg.wait_for_selector('#sel .planSec[data-which="start_frame"] [data-f="src"]')
    img_path = pg.evaluate("window.MITTLER_EDITOR.assets.images[0].path")
    pg.select_option('#sel .planSec[data-which="start_frame"] [data-f="src"]', img_path)
    pg.fill('#sel .planSec[data-which="start_frame"] [data-f="prompt"]', '@import char(kurochan) as クロ;\nクロ が窓辺に立つ')
    pg.dispatch_event('#sel .planSec[data-which="start_frame"] [data-f="prompt"]', 'change')
    tl = saved(pg); pc = next(c for t in tl['tracks'] if t['kind'] == 'plan' for c in t['clips'])
    check(pc['start'] == 5 and pc['start_frame']['src'] == img_path and 'クロ' in pc['start_frame']['prompt'] and pc['video']['engine'] == 'h3-fl2va',
          f"🎬 予定クリップ（{pc['id']}・開始の絵 {pc['start_frame']['src']}）")
    fresh_frame(pg, 6); h_plan = frame_sha(pg)
    check(h_plan != h_empty, f'🎬 開始の絵が仮に映る（{h_empty[:10]} → {h_plan[:10]}）')
    # 字幕
    sub = next(t for t in tl['tracks'] if t['kind'] == 'subtitle')
    pg.evaluate("window.MITTLER_EDITOR.seek(1.0)")
    pg.evaluate(f"window.MITTLER_LANE_DBL(window.MITTLER_EDITOR.tl.tracks.find(t => t.id === '{sub['id']}'), 1.0)")
    pg.fill('#sel [data-k="text"]', 'はじめての字幕'); pg.dispatch_event('#sel [data-k="text"]', 'change')
    tl = saved(pg)
    check(any(c.get('text') == 'はじめての字幕' for t in tl['tracks'] for c in t['clips']), '字幕を足せた')
    fresh_frame(pg, 1)
    check(True, '画像と字幕の1コマが描けた（字のファイルなし）')
    # 色の卓：カットが無い作品は全体に1つ（cut なしの grade クリップ）
    pg.click('#paneTabs button[data-p="grade"]')
    head = pg.text_content('#gradePanel h2')
    pg.evaluate("() => { const el = document.getElementById('g_b'); el.value = '1.2'; el.dispatchEvent(new Event('change')); }")
    tl = saved(pg); gs = [c for t in tl['tracks'] for c in t['clips'] if c.get('effect') == 'grade']
    check('全体' in head and len(gs) == 1 and 'cut' not in gs[0] and gs[0]['params'] == {'b': 1.2}, f'色の卓（{head}）{gs}')
    fresh_frame(pg, 1)
    check(True, '色を変えた1コマが描けた')
    # トラックの有効・無効：映像を隠す → 絵が変わる → 戻す → 同じ絵（ビット単位）。音楽はミュート
    h0 = frame_sha(pg)
    pg.click('#headList .head[data-track="t_video_0"] .vis'); tl = saved(pg); fresh_frame(pg, 1); h1 = frame_sha(pg)
    vt = next(t for t in tl['tracks'] if t['id'] == 't_video_0')
    check(vt.get('hidden') is True and h1 != h0 and pg.is_visible('#headList .head.off[data-track="t_video_0"]'), '👁 で映像のトラックを隠すと描かない（トラックは残る）')
    pg.click('#headList .head[data-track="t_video_0"] .vis'); tl = saved(pg); fresh_frame(pg, 1); h2 = frame_sha(pg)
    vt = next(t for t in tl['tracks'] if t['id'] == 't_video_0')
    check('hidden' not in vt and h2 == h0, f'もう一度押すと戻る（同じ絵 {h0[:10]} → {h1[:10]} → {h2[:10]}）')
    pg.click('#headList .head[data-track="t_music_0"] .mute'); tl = saved(pg)
    # シャイ：効果音のトラックに 🫣 → 上の 🫣 で表示から隠れる → もう一度で出る（描画は変わらない）→ 印を外す
    pg.click('#headList .head[data-track="t_sfx_0"] .shy'); tl = saved(pg)
    check(next(t for t in tl['tracks'] if t['id'] == 't_sfx_0').get('shy') is True, 'トラックをシャイにできる')
    total = pg.locator('#headList .head:not(.meta)').count()
    pg.click('#shyBtn')
    gone = pg.locator('#headList .head[data-track="t_sfx_0"]').count() == 0 and pg.locator('#laneList .lane[data-track="t_sfx_0"]').count() == 0
    left = pg.locator('#headList .head:not(.meta)').count()
    pg.click('#shyBtn'); back = pg.locator('#headList .head[data-track="t_sfx_0"]').count() == 1
    check(gone and left == total - 1 and back, f'🫣 でシャイのトラックを隠せて、もう一度で戻る（隠したとき {left} 本）')
    pg.click('#headList .head[data-track="t_sfx_0"] .shy'); tl = saved(pg)
    check(next(t for t in tl['tracks'] if t['id'] == 't_music_0').get('muted') is True, '🔈 で音楽のトラックをミュート')
    pg.click('#headList .head[data-track="t_music_0"] .mute'); tl = saved(pg)
    if a.shot:
        pg.screenshot(path=a.shot)
    # 書き出し 0〜3秒
    pg.click('#exportBtn'); pg.wait_for_selector('#exportPanel:not([hidden]) #xName')
    pg.evaluate("document.querySelectorAll('#exportPanel details.xadv').forEach(d => d.open = true)")  # 同時処理数は詳細設定の中
    pg.check('#exportPanel input[name=xr][value=part]'); pg.fill('#xFrom', '0'); pg.fill('#xTo', '3'); pg.fill('#xJobs', '2'); pg.uncheck('#xProxy')
    pg.fill('#xName', 'smoke_new'); pg.click('#exportPanel [data-x=start]')
    pg.wait_for_function("() => ['done', 'error', 'cancelled'].includes(window.MITTLER_EXPORT.job.state)", timeout=600000)
    j = pg.evaluate('window.MITTLER_EXPORT.job')
    check(j['state'] == 'done', f"書き出せた（{j['state']} {j.get('error', '')[:400]}）")
    if j['state'] == 'done':
        mp4 = tlf.parent / j['result']['path']
        d = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(mp4)], capture_output=True, text=True).stdout or 0)
        st = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(mp4)], capture_output=True, text=True).stdout.split()
        check(abs(d - 3) < 0.15 and 'audio' in st and 'video' in st, f'MP4 {d:.3f}秒 {st}')
    # 上のバーの「＋ 新規」（新規プロジェクト作成。editor/newproject.js → /api/new_project → tools/new_project.js の create()）：
    # 一時フォルダの中に別の作品を作る。今開いている作品は変わらない。作る先は空のフォルダだけ・名前は英数字と - _・書き込みの口はトークンが要る
    import shutil, tempfile, urllib.error, urllib.request
    base_url = a.url.split('/editor/')[0]; np_parent = Path(tempfile.mkdtemp(prefix='mittler_np_'))
    try:
        def http(method, path, body=None, token=None):
            req = urllib.request.Request(base_url + path, data=None if body is None else json.dumps(body).encode('utf-8'), method=method,
                                         headers=dict({'Content-Type': 'application/json'}, **({'X-Mittler-Token': token} if token else {})))
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, json.loads(r.read().decode('utf-8') or '{}')
            except urllib.error.HTTPError as e:
                return e.code, {}
        s1, _ = http('POST', '/api/new_project', {'parent': str(np_parent), 'id': 'no_token'})
        s2, _ = http('GET', '/api/new_project')
        check(s1 == 403 and s2 == 403 and not (np_parent / 'no_token').exists(), f'新規：トークンが無いと作れない・初めの値も返さない（{s1}・{s2}）')
        pg.click('#newProjBtn'); pg.wait_for_selector('#newProjDlg #npId')
        check(pg.input_value('#npParent') == str(tlf.parent.parent) and pg.locator('#newProjDlg [data-n=pick]').count() == 0,
              f"新規：窓が開く。置く場所の初めは今の作品の親のフォルダ（{pg.input_value('#npParent')}）。VS Code の外なので「選ぶ…」は無い")
        pg.fill('#npParent', str(np_parent)); pg.fill('#npId', '日本語の名前'); pg.click('#newProjDlg [data-n=create]'); time.sleep(0.3)
        check('英数字' in pg.inner_text('#npErr') and not any(np_parent.iterdir()), '新規：英数字と - _ でない名前は作らない（理由が出る）')
        pg.fill('#npId', 'np_one'); pg.fill('#npName', '新規の試し'); pg.select_option('#npSize', '1080x1920'); pg.fill('#npFps', '24'); pg.fill('#npDur', '15')
        pg.click('#newProjDlg [data-n=create]'); pg.wait_for_selector('#newProjDlg .dok', timeout=60000)
        made = np_parent / 'np_one'; ntl = json.loads((made / 'np_one.cut.json').read_text(encoding='utf-8')) if (made / 'np_one.cut.json').exists() else {}
        check((ntl.get('name'), ntl.get('width'), ntl.get('height'), ntl.get('fps'), ntl.get('duration')) == ('新規の試し', 1080, 1920, 24, 15)
              and all((made / f).exists() for f in ('AGENTS.md', 'CLAUDE.md', 'characters.json', 'effects/subtitle.py', 'assets/images', '.claude/settings.json', '.gitignore')),
              f"新規：作れた（表示名・大きさ・fps・長さ・ひな形のファイル）{ntl.get('name')} {ntl.get('width')}x{ntl.get('height')} {ntl.get('fps')}fps {ntl.get('duration')}秒")
        check('np_one.cut.json' in pg.inner_text('#newProjDlg .dok') and pg.locator('#newProjDlg [data-n=reveal]').count() == 1, '新規：VS Code の外では、できた場所と開き方が窓に出る')
        pg.click('#newProjDlg .df [data-n=close]'); pg.wait_for_selector('#newProjDlg', state='detached')
        token = a.url.split('token=')[1].split('&')[0]
        _, r2 = http('POST', '/api/new_project', {'parent': str(np_parent), 'id': 'np_one'}, token)
        _, r3 = http('POST', '/api/new_project', {'parent': str(np_parent), 'id': 'np_odd', 'width': 641, 'height': 361}, token)
        _, r4 = http('POST', '/api/new_project', {'parent': 'relative/path', 'id': 'np_rel'}, token)
        check(r2.get('ok') is False and '中身' in r2.get('error', '') and r3.get('ok') is False and not (np_parent / 'np_odd').exists() and r4.get('ok') is False,
              f"新規：もう中身があるフォルダ・奇数の大きさ・絶対パスでない場所は断る（{r2.get('error', '')[:30]}／{r3.get('error', '')[:30]}／{r4.get('error', '')[:30]}）")
        check(json.loads(tlf.read_text(encoding='utf-8')) == saved(pg) and pg.evaluate('window.MITTLER_EDITOR.file') == tlf.name, '新規：今開いている作品はそのまま')
        # Esc で閉じる・後ろのタイムラインのキーに効かない
        pg.click('#newProjBtn'); pg.wait_for_selector('#newProjDlg #npId'); n_tr = pg.locator('#headList .head:not(.meta)').count()
        pg.keyboard.press('Delete'); pg.keyboard.press('Escape'); pg.wait_for_selector('#newProjDlg', state='detached')
        check(pg.locator('#headList .head:not(.meta)').count() == n_tr, '新規：窓は Esc で閉じる（窓の中のキーは後ろのタイムラインに効かない）')
    finally:
        def _rm_ro(fn, pth, exc):  # git の読み取り専用のファイル（.git/objects）も消す
            import os, stat
            try:
                os.chmod(pth, stat.S_IWRITE); fn(pth)
            except OSError:
                pass
        shutil.rmtree(np_parent, onerror=_rm_ro)
    while pg.evaluate('window.MITTLER_EDITOR.undo.length') > 0:
        pg.click('#undo')
    tl = saved(pg)
    b.close()

check(tl == first, 'タイムラインの中身が最初と同じ（取り消しで戻った）')
check(not errors, 'コンソールエラーなし' + ('' if not errors else ': ' + ' | '.join(errors[:5])))
sys.exit(1 if fails else 0)
