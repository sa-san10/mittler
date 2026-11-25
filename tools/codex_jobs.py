"""Mittler の「絵の生成」（🎬 の開始・終了の絵）の Codex のアダプタ：Codex の決まりは全部ここ（サーバーの server.js は持たない）。
H3 のアダプタ（tools/h3_jobs.py）と同じ形。エンジンとアダプタの対応表は tools/engines.json（エンジンの足し方は docs/H3受け渡し契約.md の「エンジンを足すには」）。
- build：ジョブを作るとき、編集画面のサーバー（server.js の createJob）が呼ぶ。
    python tools/codex_jobs.py build  < エンジンに依らない依頼の JSON  → 1行の JSON {ok, image, sent, warnings, sidecars} か {ok: false, error}
  Codex の決まり（参照画像は5枚まで・画面の大きさの行を足す・作品ごとの Codex のセッション）を当てて、ジョブの image・sent を組み立てる。
  image.out（出力の名前 assets/frames/<クリップ>_<start|end>_t<n>.png）はサーバーが決める。sidecars＝出力と一緒にできるファイルの付け足し（.codex.json）
  とも重ならない名前にしてもらう。
- submit・poll：ジョブ係（tools/jobs.py）が呼ぶ。submit は tools/gen/codex_image.py（Codex CLI の内蔵の画像生成）を動かして、終わるまで待つ
  （同時1件。止める＝ジョブの cancel を見ながら）。poll は何もしない（submit の中で終わるので waiting にならない）。
  Codex CLI の場所・モデルは環境変数 MITTLER_CODEX・MITTLER_CODEX_MODEL（VS Code の設定 mittler.codex.path・mittler.codex.model をサーバーがジョブ係に渡す。古い名前 CC_CODEX・CC_CODEX_MODEL も読む）。
  無ければ PATH の codex・gpt-6.1-sol（tools/gen/codex_image.py）。
ジョブの image：{prompt（参照を開いた全文＋画面の大きさ）, refs:[絶対パス], out（素材の根からの相対）, root（素材の根）, session（Codex のセッション記録）}
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pyengine'))
from mittler.i18n import t  # noqa: E402（断る理由・注意の文の言葉。環境変数 MITTLER_LANG。Codex に送るプロンプトの文は変えない）

HERE = Path(__file__).resolve().parent
MAX_REFS = 5          # image_gen に渡せる参照画像の数
SIDECARS = ['.codex.json']  # codex_image.py が出力の横に書く記録（<出力>.codex.json）
SUBMIT_ERROR = None   # submit の例外はジョブ係の外の決まり（前と同じ：書き残してやり直す）。H3 は「H3 に依頼できなかった：」


class Refuse(Exception):
    """頼めない（理由は編集画面に出す）"""


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def js_str(x):
    """JavaScript で数を文字にしたとき（1920.0 は 1920）"""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def build(q):
    """エンジンに依らない依頼（サーバーが参照を開いたもの）→ Codex のジョブの image・sent。頼めなければ Refuse。
    q：{engine, prompt（server/plan_refs.js の resolve の prompt＝参照を開いた全文）, refs（参照画像。素材の根からの相対）, width, height, root, project_dir, clip, which}"""
    refs = q.get('refs') or []
    if len(refs) > MAX_REFS:
        raise Refuse(t('py.cx.maxRefs'))
    W, H = q.get('width') or 1920, q.get('height') or 1080
    prompt = q['prompt'] + f'\n\n【画面】横 {js_str(W)} × 縦 {js_str(H)}（動画の1コマ。この縦横の比で、画面いっぱいの絵にする）'
    image = {'prompt': prompt, 'refs': [os.path.normpath(os.path.join(q['root'], x)) for x in refs], 'out': None, 'root': q['root'],
             'session': os.path.normpath(os.path.join(q['project_dir'], 'work', 'codex-session.json'))}
    return {'ok': True, 'image': image, 'sent': {'prompt': prompt, 'refs': refs}, 'warnings': [], 'sidecars': SIDECARS}


def submit(runner, p, job):
    """codex_image.py で1枚生成して、終わるまで待つ（止める＝cancel を見ながら）。結果はジョブの result（src・refs_ok・spec_coverage・warnings）"""
    im = job['image']
    root = Path(im['root'])
    out = root / im['out']
    prompt_file = runner.jobs / f"{job['id']}.prompt.txt"
    prompt_file.write_text(im['prompt'], encoding='utf-8')
    cmd = [sys.executable, '-X', 'utf8', str(HERE / 'gen' / 'codex_image.py'), '--prompt-file', str(prompt_file), '--out', str(out)]
    for r in im.get('refs', []):
        cmd += ['--ref', r]
    if im.get('session'):
        cmd += ['--session', im['session']]
    runner.update(p, state='running', started=now())
    runner.log(f"画像 {job['id']} {job.get('clip')} {job.get('which')} → {im['out']}")
    t0 = time.time()
    runner.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', errors='replace', cwd=str(runner.project))
    while runner.proc.poll() is None:  # 止める（cancel）を見ながら待つ
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
        runner.update(p, state='failed', finished=now(), error=(stderr or stdout)[-2000:])
        runner.log(f"失敗 {job['id']} {code}")
        return
    info = {}
    for line in reversed(stdout.strip().splitlines()):
        try:
            info = json.loads(line); break
        except ValueError:
            continue
    warn = []
    if info.get('spec_coverage') is not None and info['spec_coverage'] < 0.9:
        warn.append(t('py.cx.coverage', p=round(info['spec_coverage'] * 100)))
    if im.get('refs') and info.get('refs_ok') is not True:
        warn.append(t('py.cx.refs'))
    runner.update(p, state='done', finished=now(), seconds=round(time.time() - t0, 1),
                  result={'src': im['out'], 'refs_ok': info.get('refs_ok'), 'spec_coverage': info.get('spec_coverage'),
                          'width': info.get('width'), 'height': info.get('height'), 'warnings': warn})
    runner.log(f"できた {job['id']} {round(time.time() - t0)}秒 {warn}")


def poll(runner, p, job):
    """Codex は submit の中で終わる（waiting にならない）"""
    return


if __name__ == '__main__':
    # python tools/codex_jobs.py build：標準入力の依頼（JSON）→ 標準出力に1行の JSON（サーバーの createJob が読む）
    if sys.argv[1:] != ['build']:
        sys.exit('usage: python tools/codex_jobs.py build  < 依頼の JSON')
    try:
        out = build(json.loads(sys.stdin.buffer.read().decode('utf-8')))
    except Refuse as e:
        out = {'ok': False, 'error': str(e)}
    sys.stdout.write(json.dumps(out) + '\n')
