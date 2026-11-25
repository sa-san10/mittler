"""Mittler の「動画化」の H3 のアダプタ：H3 の決まりは全部ここ（サーバーの server.js は持たない）。受け渡しの形の正本は docs/H3受け渡し契約.md。
エンジン h3-fl2va・h3-ref2va のアダプタとして tools/engines.json に登録してある（絵の Codex のアダプタ tools/codex_jobs.py と同じ形：build・submit・poll）。
- build：ジョブを作るとき、編集画面のサーバー（server.js の createVideoJob）が呼ぶ。
    python tools/h3_jobs.py build  < エンジンに依らない依頼の JSON  → 1行の JSON {ok, video, sent, warnings} か {ok: false, error}
  H3 の決まり（コマ数・声の長さ・参照の数・プロンプトの形・既定値・下書きのステップ・置き場所と名前）を当てて、ジョブの video・sent を組み立てる。
  頼めないものはここで止める（理由は編集画面に出る）。直したものは warnings（ジョブの JSON の warnings → 編集画面）。
- submit・poll：ジョブ係（tools/jobs.py）が呼ぶ。MiniMax H3 のキュー（Google ドライブの H3_tasks）に依頼を置いて、結果を取り込む。
  - 入力の絵・声：<マイドライブ>/claude-cut-h3/<project>/<id>/ に写す（H3 のランナーはマイドライブからの相対パスで読む）
  - 依頼：<H3_tasks>/inbox/<project>__<id>.yaml（書き終えてから置く）。project は cc_<作品フォルダ名>
    （ドライブのフォルダ名 claude-cut-h3 と project の頭 cc_ は、H3 との受け渡しの名前＝契約なので、2026-11-12 の Mittler への改名でも変えていない）
  - 結果：<H3_tasks>/outbox/<project>/<id>.result.json（outputs は Colab のパス → このPCのマイドライブに読みかえる）か <id>.error.txt
  - できた動画は作品の assets/videos/gen/ に写す
H3 のランナーは Mittler の外（置いて待つだけ。Colab を動かすのは H3 の運用の担当、ユーザーの GO のあと）。
ジョブの video：{engine: h3-fl2va|h3-ref2va, prompt, start, end（絶対パス）, seconds, orientation, mydrive, h3_root, h3（YAML に足す設定）, draft,
               project, id, out（素材の根からの相対）, root, project_dir, dry, audio:{here, timeline, t0, t1, seconds}|{src（絶対パス）, in, out, seconds}, ref_images}
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pyengine'))
from mittler.names import env  # noqa: E402（環境変数 MITTLER_*。古い名前 CC_* も読む。標準ライブラリだけ）
from mittler.i18n import t  # noqa: E402（断る理由・注意の文の言葉。環境変数 MITTLER_LANG。H3 に送るプロンプト・YAML の文は変えない）

POLL_SEC = 20
SUBMIT_ERROR = t('py.h3.submitErr')  # submit が例外で止まったとき、ジョブ係がジョブの error の頭に付ける（エンジンのアダプタの形。tools/engines.json）
H3_KEYS =('steps', 'scheduler', 'ref_image_size', 'seed', 'fit', 'gen_seconds', 'lyrics', 'sing_start', 'sing_end')

# ---- H3 の決まり（2026-10-30 に server.js の createVideoJob から移した）----
FPS = 24                    # H3 の動画のコマの速さ
MIN_FRAMES = 5              # いちばん短い動画のコマ数
FL2V_STEP, FL2V_BASE = 17, 5  # 開始と終了の絵がある fl2va は 17k+5 コマ（でないと速さが変わる）
VOICE_MIN, VOICE_MAX = 1.5, 14.5  # ref2va の声の長さ（ランナーが前に 0.5 秒の無音を足して 2〜15 秒）
REF2VA_MAX_REFS = 8         # ref2va の参照画像（開始の絵と合わせて 9 枚まで）
REF2VA_DEFAULTS = {'ref_image_size': 'max', 'scheduler': 'beta', 'steps': 25}  # 顔の対策（偽マリアの ref2va v2 で採用した設定）
DRAFT_STEPS, DRAFT_MIN, DRAFT_MAX = 10, 4, 40  # 下書きのステップ（既定・下限・上限）
SIX_SECTIONS = re.compile(r'subject_definitions\s*:', re.I)  # 6節の形（ref2va の成功例の型。docs/H3受け渡し契約.md の 6）



def _author_mydrives():
    """環境変数 MITTLER_MYDRIVE が無いときに探すマイドライブ：作者の PC の既定（server/defaults.author.json の mydrives）。無ければ空＝環境変数で指定"""
    try:
        return tuple(json.loads((Path(__file__).resolve().parent.parent / 'server' / 'defaults.author.json').read_text(encoding='utf-8')).get('mydrives') or ())
    except (OSError, ValueError):
        return ()


MYDRIVES = _author_mydrives()


class Refuse(Exception):
    """頼めない（理由は編集画面に出す）"""


def js_round(x):
    """JavaScript の Math.round（.5 は大きいほうへ）"""
    f = math.floor(x)
    return int(f + 1 if x - f >= 0.5 else f)


def js_fixed(x, n):
    """JavaScript の x.toFixed(n)（2進の値そのものを十進で丸める。ちょうど半分は大きいほうへ）"""
    return str(Decimal(x).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def js_num(s):
    """JavaScript の +"…"（整数なら int にして、JSON に 5.0 でなく 5 と書く）"""
    x = float(s)
    return int(x) if x.is_integer() else x


def js_str(x):
    """JavaScript で数を文字にしたとき（5.0 は 5）"""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def js_plus(v):
    """JavaScript の +v（数にならなければ NaN）"""
    if v is None:
        return 0.0
    if isinstance(v, (bool, int, float)):
        return float(v)
    try:
        return float(str(v).strip() or 0)
    except ValueError:
        return float('nan')


def safe_name(s):
    """英数字・_・- 以外は _ に（JavaScript の replace(/[^A-Za-z0-9_-]/g, '_') と同じ：BMP の外の字は2つ）"""
    return ''.join(c if re.fullmatch(r'[A-Za-z0-9_-]', c) else ('__' if ord(c) > 0xFFFF else '_') for c in s)


def places():
    """マイドライブ（Google ドライブ）と H3 のキュー。テストでは環境変数 MITTLER_MYDRIVE・MITTLER_H3_ROOT（古い名前 CC_MYDRIVE・CC_H3_ROOT も読む）で別の場所にできる"""
    mydrive = env('MYDRIVE') or next((d for d in MYDRIVES if os.path.exists(d)), None)
    h3 = env('H3_ROOT') or (mydrive and os.path.normpath(os.path.join(mydrive, 'H3_tasks')))
    if not mydrive or not h3 or not os.path.exists(h3):
        raise Refuse(t('py.h3.noTasks'))
    return mydrive, h3


def build(q):
    """エンジンに依らない依頼（サーバーが参照を開いたもの）→ H3 のジョブの video・sent と warnings。頼めなければ Refuse。
    q：{engine, body（@import を除いた本文）, imports（server/plan_refs.js の resolve の imports。絵には image_abs）,
        start, end（素材の根からの相対）, start_abs, end_abs, audio（声の参照：[{here, t0, t1, seconds, empty} | {src, src_abs, in, out, seconds}]）,
        dur（クリップの長さ・秒）, width, height, seed（サーバーが決めたシード）, seed_from_clip（クリップの video.seed か）, h3（クリップの video.h3）,
        draft, steps（下書きのステップ）, out（出力の名前。素材の根からの相対）, root, project_dir, clip, dry}"""
    engine = q['engine']
    body, imports, audios = q.get('body') or '', q.get('imports') or [], q.get('audio') or []
    start, end = q.get('start'), q.get('end')
    ok = [im for im in imports if not im.get('error')]
    if engine == 'h3-fl2va' and audios:
        raise Refuse(t('py.h3.fl2vaVoice'))
    if not start and not end and not body:
        raise Refuse(t('py.h3.nothing'))
    warnings = []
    # ref2va（声から口パク）：声の参照は1つ。長さは 1.5〜14.5 秒（前に 0.5 秒の無音を足して 2〜15 秒＝H3 の決まり）。開始の絵＝<Picture 1>
    audio, sent_audio, ref_images = None, None, []
    if engine == 'h3-ref2va':
        if len(audios) != 1:
            raise Refuse(t('py.h3.ref2vaVoice'))
        if not start:
            raise Refuse(t('py.h3.ref2vaStart'))
        if not body:
            raise Refuse(t('py.h3.ref2vaBody'))
        if end:
            warnings.append(t('py.h3.ref2vaNoEnd'))
        a = audios[0]
        if a.get('here'):  # このクリップの時間に鳴っている TTS（ミュートしていないトラック）を混ぜる。混ぜる元のタイムラインはサーバーが書く（timeline）
            if a.get('empty'):
                raise Refuse(t('py.h3.noTtsHere'))
            audio = {'here': True, 'timeline': None, 't0': a['t0'], 't1': a['t1'], 'seconds': a['seconds']}
            sent_audio = {'here': True, 't0': a['t0'], 't1': a['t1']}
        else:
            audio = {'src': a['src_abs'], 'in': a['in'], 'out': a['out'], 'seconds': a['seconds']}
            sent_audio = {'src': a['src'], 'in': a['in'], 'out': a['out']}
        if audio['seconds'] < VOICE_MIN or audio['seconds'] > VOICE_MAX:
            raise Refuse(t('py.h3.voiceLen', s=js_str(audio['seconds']), min=VOICE_MIN, max=VOICE_MAX))
        ref_images = [im['image_abs'] for im in ok if im.get('image') and im.get('kind') != 'frame']
        if len(ref_images) > REF2VA_MAX_REFS:
            raise Refuse(t('py.h3.maxRefs', n=REF2VA_MAX_REFS + 1))
    frames = max(MIN_FRAMES, js_round(q['dur'] * FPS))
    if start and end and engine != 'h3-ref2va':  # FL2V は 17k+5 フレームにしないと速さが変わる（H3 の決まり）
        k = max(1, js_round((frames - FL2V_BASE) / FL2V_STEP))
        f2 = FL2V_STEP * k + FL2V_BASE
        if f2 != frames:
            warnings.append(t('py.h3.len17', s=js_fixed(f2 / FPS, 3), f=f2))
        frames = f2
    seconds = js_num(js_fixed(frames / FPS, 3))
    # H3 のプロンプト：本文＋キャラの外見＋画風（H3 には開始・終了の絵しか渡らないので、参照画像の番号は書かない）
    extra = [f"{im.get('alias')}：{im['text']}" for im in ok if im.get('kind') == 'char' and im.get('text')]
    styles = [im.get('text') or '' for im in ok if im.get('kind') == 'style']
    # 6節の形（subject_definitions: …。ref2va の成功例の型）で書いてあれば、そのまま送る：自前の前置き（<Picture>・<Audio 1> の行）や
    # キャラの外見・画風を足すと、(S1) の決め方と食い違う（2026-10-26。口パクの失敗が続いた）
    six = bool(SIX_SECTIONS.search(body))
    if six:
        warnings.append(t('py.h3.six'))
        prompt = body
    else:
        prompt = '\n\n'.join(x for x in [body, '人物：\n' + '\n'.join(extra) if extra else '', '\n\n'.join(styles)] if x)
    if engine == 'h3-ref2va' and not six:  # ref2va：<Picture N> で参照を名指しする（H3 のプロンプトの型）
        pics = ['<Picture 1> is the exact first frame.'] + [f"<Picture {i + 2}> is {im.get('alias')}（参照）." for i, im in
                                                             enumerate(x for x in ok if x.get('image') and x.get('kind') != 'frame')]
        prompt = '\n'.join(pics) + '\n<Audio 1>: fully_copy - the voice of the speaking character. Mouth movements are precisely synchronized with <Audio 1>.\n\n' + prompt
    mydrive, h3_root = places()
    project = 'cc_' + safe_name(os.path.basename(q['project_dir']))
    vid = safe_name(re.sub(r'\.mp4$', '', os.path.basename(q['out'])))
    orientation = 'landscape' if (q.get('width') or 1920) >= (q.get('height') or 1080) else 'portrait'
    # H3 の設定の上書き（クリップの video.h3。YAML に足すのは H3_KEYS だけ）＋シード＋下書きのステップ
    h3o = dict(q['h3']) if isinstance(q.get('h3'), dict) else {}
    if q.get('seed_from_clip') or h3o.get('seed') is None:  # シードはクリップの video.seed、無ければ video.h3.seed、それも無ければサーバーが決めた値
        h3o['seed'] = q['seed']
    if q.get('draft'):
        n = js_plus(q.get('steps'))
        h3o['steps'] = max(DRAFT_MIN, min(DRAFT_MAX, js_round(n if n and not math.isnan(n) else DRAFT_STEPS)))
        warnings.append(t('py.h3.draft', n=h3o['steps']))
    seconds = audio['seconds'] if audio else seconds
    end_used = None if engine == 'h3-ref2va' else end
    video = {'engine': engine, 'prompt': prompt, 'start': q.get('start_abs'), 'end': None if engine == 'h3-ref2va' else q.get('end_abs'),
             'seconds': seconds, 'orientation': orientation, 'mydrive': mydrive, 'h3_root': h3_root, 'h3': h3o or None, 'draft': bool(q.get('draft')),
             'project': project, 'id': vid, 'out': q['out'], 'root': q['root'], 'project_dir': q['project_dir'], 'dry': bool(q.get('dry')),
             'audio': audio, 'ref_images': ref_images}
    sent = {'draft': bool(q.get('draft')), 'steps': h3o.get('steps') or None, 'seed': h3o.get('seed'), 'engine': engine, 'prompt': prompt,
            'start': start, 'end': end_used, 'seconds': seconds, 'audio': sent_audio}
    return {'ok': True, 'video': video, 'sent': sent, 'warnings': warnings}


def yq(v):
    """YAML に書く値（JSON の書き方は YAML でもそのまま読める）"""
    return json.dumps(v, ensure_ascii=False)


def rel_mydrive(p, mydrive):
    return Path(p).resolve().relative_to(Path(mydrive).resolve()).as_posix()


def make_voice(a, dst):
    """声の参照の wav（48kHz・2ch）：音声ファイルの切り出しか、クリップの時間の TTS を混ぜたもの（pyengine の mittler mix。numpy なしで動く）"""
    if a.get('here'):
        # mix.py を直接（python -m mittler は描画のために Pillow・numpy を読むが、混ぜるのは ffmpeg だけでよい。ジョブ係の python には入っていないことがある）
        mix_py = Path(__file__).resolve().parent.parent / 'pyengine' / 'mittler' / 'mix.py'
        r = subprocess.run([sys.executable, '-X', 'utf8', str(mix_py), a['timeline'], str(dst), '--from', str(a['t0']), '--to', str(a['t1'])],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode or not dst.is_file():
            raise RuntimeError(t('py.h3.mixFail', err=(r.stderr or r.stdout)[-800:]))
    else:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f"{a['in']:.3f}", '-t', f"{a['out'] - a['in']:.3f}", '-i', a['src'], '-ac', '2', '-ar', '48000', str(dst)], check=True)


def submit(runner, p, job):
    v = job['video']
    mydrive, h3 = Path(v['mydrive']), Path(v['h3_root'])
    src_dir = mydrive / 'claude-cut-h3' / v['project'] / v['id']
    src_dir.mkdir(parents=True, exist_ok=True)
    fields = {'project': v['project'], 'id': v['id']}
    if v.get('start'):
        dst = src_dir / ('start' + Path(v['start']).suffix); shutil.copy2(v['start'], dst); fields['image'] = rel_mydrive(dst, mydrive)
    if v.get('end') and v.get('engine') != 'h3-ref2va':
        dst = src_dir / ('end' + Path(v['end']).suffix); shutil.copy2(v['end'], dst); fields['last_image'] = rel_mydrive(dst, mydrive)
    fields['prompt'] = v.get('prompt') or 'auto'
    fields['seconds'] = v['seconds']
    fields['orientation'] = v.get('orientation', 'landscape')
    if v.get('engine') == 'h3-ref2va':
        fields['mode'] = 'ref2va'
        refs = []
        for i, r in enumerate(v.get('ref_images', [])):
            dst = src_dir / f'ref{i + 1}{Path(r).suffix}'; shutil.copy2(r, dst); refs.append(rel_mydrive(dst, mydrive))
        if refs:
            fields['ref_images'] = refs
        a = v['audio']
        dst = src_dir / 'voice.wav'
        make_voice(a, dst)
        fields.update({'audio': rel_mydrive(dst, mydrive), 'audio_start': 0, 'audio_seconds': a['seconds']})
        fields['seconds'] = a['seconds']
        fields.update(REF2VA_DEFAULTS)  # 顔の対策：開始画像の一致度・beta・25 step（上の REF2VA_DEFAULTS）
    # クリップの video.h3 で H3 の設定を上書き・追加できる（steps・scheduler・ref_image_size・seed・fit・gen_seconds・lyrics・sing_start・sing_end）
    for k, x in (v.get('h3') or {}).items():
        if k in H3_KEYS:
            fields[k] = x
    lines = ['# claude-cut の 🎬 動画化（tools/h3_jobs.py が置いた）', f"# 作品: {v.get('project_dir', '')}  クリップ: {job.get('clip')}"]
    lines += [f'{k}: {yq(x)}' for k, x in fields.items()]
    text = '\n'.join(lines) + '\n'
    name = f"{v['project']}__{v['id']}.yaml"
    tmp = src_dir / (name + '.part')
    tmp.write_text(text, encoding='utf-8')
    (src_dir / name).write_text(text, encoding='utf-8')  # 置いたものの控え
    inbox = h3 / 'inbox'
    if v.get('dry'):  # 確かめるだけ（inbox に置かない）
        tmp.unlink()
        runner.update(p, state='failed', error=t('py.h3.dry'), h3={'yaml': str(src_dir / name), 'fields': fields})
        return
    inbox.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, inbox / name)  # 書き終えてから置く
    runner.update(p, state='waiting', submitted=time.strftime('%Y-%m-%dT%H:%M:%S'), h3={'yaml': str(inbox / name), 'fields': fields}, last_poll=0)
    runner.log(f"H3 に依頼 {v['project']}/{v['id']}（{fields.get('mode', 'fl2va')}・{fields['seconds']}秒）")


def poll(runner, p, job):
    if time.time() - job.get('last_poll', 0) < POLL_SEC:
        return
    v = job['video']
    h3, mydrive = Path(v['h3_root']), Path(v['mydrive'])
    out_dir = h3 / 'outbox' / v['project']
    err = out_dir / f"{v['id']}.error.txt"
    res = out_dir / f"{v['id']}.result.json"
    if job.get('cancel'):
        runner.update(p, state='cancelled', note=t('py.h3.cancelNote'))
        return
    if err.is_file():
        runner.update(p, state='failed', error=t('py.h3.fail', err=err.read_text(encoding='utf-8', errors='replace')[-1500:]))
        runner.log(f"H3 失敗 {v['project']}/{v['id']}")
        return
    if not res.is_file():
        runner.update(p, last_poll=time.time())
        return
    r = json.loads(res.read_text(encoding='utf-8'))
    src = None
    for o in r.get('outputs', []):
        q = o.replace('/content/drive/MyDrive/', '')
        cand = mydrive / q
        if cand.suffix == '.mp4' and '_lipsync' not in cand.name and cand.is_file():
            src = cand; break
    if not src:
        runner.update(p, last_poll=time.time(), note=t('py.h3.waitDrive'))
        return
    root = Path(v['root'])
    dst = root / v['out']
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    st = r.get('settings', {})
    secs = (st.get('frames') or 0) / (st.get('fps') or 24) if st.get('frames') else None
    runner.update(p, state='done', finished=time.strftime('%Y-%m-%dT%H:%M:%S'),
                  result={'src': v['out'], 'dur': round(secs, 3) if secs else v.get('seconds'), 'h3': {k: r.get(k) for k in ('settings', 'seconds_h3', 'warnings')}})
    runner.log(f"H3 できた {v['project']}/{v['id']} → {v['out']}")


if __name__ == '__main__':
    # python tools/h3_jobs.py build：標準入力の依頼（JSON）→ 標準出力に1行の JSON（サーバーの createVideoJob が読む）
    if sys.argv[1:] != ['build']:
        sys.exit('usage: python tools/h3_jobs.py build  < 依頼の JSON')
    try:
        out = build(json.loads(sys.stdin.buffer.read().decode('utf-8')))
    except Refuse as e:
        out = {'ok': False, 'error': str(e)}
    sys.stdout.write(json.dumps(out) + '\n')
