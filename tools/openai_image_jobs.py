"""Mittler の「絵の生成」（🎬 の開始・終了の絵）の OpenAI（GPT Image）のアダプタ：OpenAI の決まりは全部ここ（2026-11-15。Codex とは別口）。
Codex のアダプタ（tools/codex_jobs.py）と同じ形。エンジンとアダプタの対応表は tools/engines.json。
- build：ジョブを作るとき、編集画面のサーバー（server.js の createJob）が呼ぶ。
    python tools/openai_image_jobs.py build  < エンジンに依らない依頼の JSON  → 1行の JSON {ok, image, sent, warnings, sidecars} か {ok: false, error}
  OpenAI の決まり（参照画像は16枚まで・大きさは 16 の倍数で縦横の比は 1:3〜3:1・品質）を当てて、ジョブの image・sent を組み立てる。
  モデル・品質：依頼の model・quality（絵の欄の model・quality）→ PC の設定（mittler.openai.imageModel・imageQuality。サーバーが依頼の
  default_model・default_quality に入れる）→ 既定（gpt-image-2.5-sunburst・high）。
- submit・poll：ジョブ係（tools/jobs.py）が呼ぶ。submit は tools/gen/openai_image.py（OpenAI の Image API）を動かして、終わるまで待つ
  （同時1件。止める＝ジョブの cancel を見ながら）。poll は何もしない。
  鍵は Windows の資格情報マネージャー ps:OPENAI_API_KEY（環境変数 OPENAI_API_KEY が先）。値は出さない。
ジョブの image：{prompt, refs:[絶対パス], out（素材の根からの相対）, root（素材の根）, engine, model, quality, size}
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pyengine'))
from mittler.i18n import t  # noqa: E402

HERE = Path(__file__).resolve().parent
MAX_REFS = 16
DEFAULT_MODEL = 'gpt-image-2.5-sunburst'
DEFAULT_QUALITY = 'high'
QUALITIES = ('auto', 'low', 'medium', 'high', 'xhigh', 'max')
SIDECARS = ['.openai.json']  # openai_image.py が出力の横に書く記録
SUBMIT_ERROR = None
MIN_PX, MAX_PX, MAX_EDGE = 655360, 2560 * 1440, 2560  # 2560×1440 より大きいのは試し（experimental）なので使わない


class Refuse(Exception):
    pass


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def pick_size(W, H):
    """動画の縦横 → API に頼む大きさ（両辺 16 の倍数・比 1:3〜3:1・画素は MIN_PX〜MAX_PX）。比を優先して、画素は動画に近く"""
    a = min(3.0, max(1 / 3, W / H))
    target = min(MAX_PX, max(MIN_PX, W * H))
    best = None
    for w in range(256, MAX_EDGE + 1, 16):
        h = round(w / a / 16) * 16
        if not (256 <= h <= MAX_EDGE) or not (MIN_PX <= w * h <= MAX_PX) or not (1 / 3 <= w / h <= 3):
            continue
        px = abs(w * h - target) / target * (2 if w * h < target else 1)  # 動画より小さいのは引き伸ばすことになるので重く
        score = 500 * abs(w / h - a) / a + px  # 比のずれはもっと重く（ずれた絵は画面で切れる）
        if best is None or score < best[0]:
            best = (score, w, h)
    return f'{best[1]}x{best[2]}' if best else 'auto'


def build(q):
    """エンジンに依らない依頼（サーバーが参照を開いたもの）→ OpenAI のジョブの image・sent。頼めなければ Refuse。
    q：{engine, prompt, refs（素材の根からの相対）, width, height, root, project_dir, clip, which, model, quality, default_model, default_quality}"""
    refs = q.get('refs') or []
    if len(refs) > MAX_REFS:
        raise Refuse(t('py.oa.maxRefs', n=MAX_REFS))
    model = (q.get('model') or q.get('default_model') or DEFAULT_MODEL).strip()
    quality = (q.get('quality') or q.get('default_quality') or DEFAULT_QUALITY).strip()
    if quality not in QUALITIES:
        raise Refuse(t('py.oa.quality', q=quality, list=' / '.join(QUALITIES)))
    size = pick_size(q.get('width') or 1920, q.get('height') or 1080)
    prompt = q['prompt'] + '\n\n【画面】動画の1コマ。この縦横の比で、画面いっぱいの絵にする'
    image = {'prompt': prompt, 'refs': [os.path.normpath(os.path.join(q['root'], x)) for x in refs], 'out': None, 'root': q['root'],
             'engine': q.get('engine') or 'openai', 'model': model, 'quality': quality, 'size': size}
    return {'ok': True, 'image': image, 'sent': {'prompt': prompt, 'refs': refs, 'model': model, 'quality': quality, 'size': size},
            'warnings': [], 'sidecars': SIDECARS}


def submit(runner, p, job):
    """openai_image.py で1枚生成して、終わるまで待つ（止める＝cancel を見ながら）。結果はジョブの result（src・model・width・height・usage）"""
    im = job['image']
    root = Path(im['root'])
    out = root / im['out']
    prompt_file = runner.jobs / f"{job['id']}.prompt.txt"
    prompt_file.write_text(im['prompt'], encoding='utf-8')
    cmd = [sys.executable, '-X', 'utf8', str(HERE / 'gen' / 'openai_image.py'), '--prompt-file', str(prompt_file), '--out', str(out),
           '--model', im.get('model') or DEFAULT_MODEL, '--quality', im.get('quality') or DEFAULT_QUALITY, '--size', im.get('size') or 'auto']
    for r in im.get('refs', []):
        cmd += ['--ref', r]
    runner.update(p, state='running', started=now())
    runner.log(f"画像 {job['id']} {job.get('clip')} {job.get('which')} OpenAI {im.get('model')} {im.get('size')} → {im['out']}")
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
        sys.exit('usage: python tools/openai_image_jobs.py build  < 依頼の JSON')
    try:
        out = build(json.loads(sys.stdin.buffer.read().decode('utf-8')))
    except Refuse as e:
        out = {'ok': False, 'error': str(e)}
    sys.stdout.write(json.dumps(out) + '\n')
