"""Mittler の「絵の生成」（🎬 の開始・終了の絵）の Nano Banana（Gemini の画像生成）のアダプタ：Gemini の決まりは全部ここ（2026-11-19。
モデルを選べる・既定はいちばんよいモデルと品質・解像度の既定は 2K・参照画像も渡せる）。
OpenAI のアダプタ（tools/openai_image_jobs.py）と同じ形。エンジンとアダプタの対応表は tools/engines.json（エンジンの名前 nanobanana）。
- build：ジョブを作るとき、編集画面のサーバー（server.js の createJob）が呼ぶ。
    python tools/gemini_image_jobs.py build  < エンジンに依らない依頼の JSON  → 1行の JSON {ok, image, sent, warnings, sidecars} か {ok: false, error}
  Gemini の決まり（参照画像は14枚まで・縦横の比は決まったものから・解像度 1K／2K／4K）を当てて、ジョブの image・sent を組み立てる。
  モデル・解像度：依頼の model・quality（絵の欄の model・quality。quality に解像度）→ PC の設定（mittler.gemini.imageModel・imageSize。サーバーが依頼の
  default_model・default_quality に入れる）→ 既定（gemini-3-pro-image＝Nano Banana Pro・2K）。
- submit・poll：ジョブ係（tools/jobs.py）が呼ぶ。submit は tools/gen/gemini_image.py を動かして、終わるまで待つ（止める＝ジョブの cancel を見ながら）。
  鍵は Gemini TTS と同じ（資格情報マネージャーの ps:GEMINI_API_KEY。環境変数 GEMINI_API_KEY が先）。値は出さない。
ジョブの image：{prompt, refs:[絶対パス], out（素材の根からの相対）, root（素材の根）, engine, model, quality（解像度）, aspect}
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pyengine'))
sys.path.insert(0, str(HERE / 'gen'))
from mittler.i18n import t  # noqa: E402
from gemini_image import ASPECTS, DEFAULT_MODEL, DEFAULT_SIZE, MAX_REFS, SIZES, pick_aspect  # noqa: E402,F401

MODELS = ['gemini-3-pro-image', 'gemini-nano-banana-2.1', 'gemini-3.1-flash-image', 'gemini-3.1-flash-lite-image', 'gemini-2.5-flash-image']  # 編集画面の候補（ほかの名前も書ける）
SIDECARS = ['.gemini.json']  # gemini_image.py が出力の横に書く記録
SUBMIT_ERROR = None  # submit の中で終わるまで待つ（ジョブ係 tools/jobs.py が見る。絵は同時 1 件）


class Refuse(Exception):
    pass


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def build(q):
    """エンジンに依らない依頼（サーバーが参照を開いたもの）→ Nano Banana のジョブの image・sent。頼めなければ Refuse。
    q：{engine, prompt, refs（素材の根からの相対）, width, height, root, project_dir, clip, which, model, quality, default_model, default_quality}"""
    refs = q.get('refs') or []
    if len(refs) > MAX_REFS:
        raise Refuse(t('py.nb.maxRefs', n=MAX_REFS))
    model = (q.get('model') or q.get('default_model') or DEFAULT_MODEL).strip()
    size = (q.get('quality') or q.get('default_quality') or DEFAULT_SIZE).strip().upper()
    if size not in SIZES:
        raise Refuse(t('py.nb.size', q=size, list=' / '.join(SIZES)))
    aspect = pick_aspect(q.get('width') or 1920, q.get('height') or 1080)
    prompt = q['prompt'] + '\n\n【画面】動画の1コマ。この縦横の比で、画面いっぱいの絵にする'
    image = {'prompt': prompt, 'refs': [os.path.normpath(os.path.join(q['root'], x)) for x in refs], 'out': None, 'root': q['root'],
             'engine': q.get('engine') or 'nanobanana', 'model': model, 'quality': size, 'aspect': aspect}
    return {'ok': True, 'image': image, 'sent': {'prompt': prompt, 'refs': refs, 'model': model, 'quality': size, 'aspect': aspect},
            'warnings': [], 'sidecars': SIDECARS}


def submit(runner, p, job):
    """gemini_image.py で1枚生成して、終わるまで待つ（止める＝cancel を見ながら）。結果はジョブの result（src・model・width・height・usage）"""
    im = job['image']
    root = Path(im['root'])
    out = root / im['out']
    prompt_file = runner.jobs / f"{job['id']}.prompt.txt"
    prompt_file.write_text(im['prompt'], encoding='utf-8')
    cmd = [sys.executable, '-X', 'utf8', str(HERE / 'gen' / 'gemini_image.py'), '--prompt-file', str(prompt_file), '--out', str(out),
           '--model', im.get('model') or DEFAULT_MODEL, '--image-size', im.get('quality') or DEFAULT_SIZE, '--aspect', im.get('aspect') or '16:9']
    for r in im.get('refs', []):
        cmd += ['--ref', r]
    runner.update(p, state='running', started=now())
    runner.log(f"画像 {job['id']} {job.get('clip')} {job.get('which')} Nano Banana {im.get('model')} {im.get('quality')} {im.get('aspect')} → {im['out']}")
    t0 = time.time()
    runner.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', errors='replace', cwd=str(runner.project))
    while runner.proc.poll() is None:
        time.sleep(1)
        j = runner.read(p) or {}
        if j.get('cancel'):
            subprocess.run(['taskkill', '/PID', str(runner.proc.pid), '/T', '/F'], capture_output=True) if os.name == 'nt' else runner.proc.kill()
            runner.proc.wait()
            runner.update(p, state='cancelled', finished=now())
            runner.log(f"止めた {job['id']}")
            runner.proc = None
            return
    stdout, stderr = runner.proc.communicate()
    code = runner.proc.returncode
    runner.proc = None
    if code != 0 or not out.is_file():
        runner.update(p, state='failed', finished=now(), error=(stderr or stdout).strip()[-2000:])
        runner.log(f"失敗 {job['id']} {code}")
        return
    info = {}
    for line in reversed(stdout.strip().splitlines()):
        try:
            info = json.loads(line); break
        except ValueError:
            continue
    runner.update(p, state='done', finished=now(), seconds=round(time.time() - t0, 1),
                  result={'src': im['out'], 'model': info.get('model') or im.get('model'), 'width': info.get('width'), 'height': info.get('height'),
                          'usage': info.get('usage'), 'warnings': []})
    runner.log(f"できた {job['id']} {round(time.time() - t0)}秒")


def poll(runner, p, job):
    """submit の中で終わる（waiting にならない）"""
    return


if __name__ == '__main__':
    if sys.argv[1:] != ['build']:
        sys.exit('usage: python tools/gemini_image_jobs.py build  < 依頼の JSON')
    try:
        out = build(json.loads(sys.stdin.buffer.read().decode('utf-8')))
    except Refuse as e:
        out = {'ok': False, 'error': str(e)}
    sys.stdout.write(json.dumps(out) + '\n')
