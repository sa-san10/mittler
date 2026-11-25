"""ためた絵の置き場を作品の外にする設定（PC の設定 mittler.cache.dir＝環境変数 MITTLER_CACHE_DIR。2026-11-22）の確かめ。描画の python で流す。
  <描画の python> -X utf8 tools\\smoke_cachedir.py
試しの作品を一時フォルダに作って、終わったら消す。確かめること：
1. Python（pyengine/mittler/names.py の cache_root）と JS（server/names.js の cacheRoot）が、同じ作品に同じ置き場を返す（日本語の名前・終わりの \\ も）
2. 設定が無ければ、今までどおり作品の work/cache/frames にためる
3. 設定があれば、<置き場>/<作品の名前>-<印>/cache/frames にため、作品の work/cache は作らない。_project.txt に作品の場所
4. どちらでも書き出した MP4 が同じ（置き場は絵を変えない）
5. 編集画面のサーバー（--cache-dir）：止めた 1 コマのためた絵・数・消すのも置き場の下
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
fails = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


def run(args, env=None, cwd=None):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, cwd=cwd, timeout=600)


work = Path(tempfile.mkdtemp(prefix='mittler_cachedir_'))
try:
    # 1. Python と JS の決まりが同じ
    cdir = work / 'cache'
    pyenv = dict(os.environ, MITTLER_CACHE_DIR=str(cdir))
    for proj in [str(work / 'ためし作品'), str(work / 'proj-a') + '\\', 'D:\\videos\\my-mv']:
        a = run([PY, '-X', 'utf8', '-c', f'from mittler.names import cache_root; print(cache_root({proj!r}))'], env=pyenv, cwd=str(ROOT / 'pyengine')).stdout.strip()
        b = run(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node', '-e', f"console.log(require({json.dumps(str(ROOT / 'server' / 'names.js'))}).cacheRoot({json.dumps(proj)}))"], env=pyenv).stdout.strip()
        check(a and a == b and a.startswith(str(cdir)), f'1 Python と JS が同じ置き場（{proj} → {a}）')
    shutil.rmtree(cdir, ignore_errors=True)

    # 試しの作品：画像 1 枚と字幕
    proj = work / 'cdproj'
    r = run(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node', str(ROOT / 'tools' / 'new_project.js'), str(proj), '--duration', '2', '--no-git'])
    if r.returncode:
        raise SystemExit('new_project 失敗: ' + r.stdout + r.stderr)
    from PIL import Image
    (proj / 'assets' / 'images').mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (320, 180), (30, 90, 160)).save(proj / 'assets' / 'images' / 'bg.png')
    tlf = next(proj.glob('*.cut.json'))
    tl = json.loads(tlf.read_text(encoding='utf-8'))
    tl.update(width=320, height=180, fps=10)
    tl.setdefault('settings', {})['export'] = {'video': {'preset': 'ultrafast', 'crf': 0}}
    for t in tl['tracks']:
        if t.get('kind') == 'video':
            t['clips'] = [{'id': 'bg', 'type': 'image', 'src': 'assets/images/bg.png', 'start': 0, 'dur': 2}]
        if t.get('kind') == 'subtitle':
            t['clips'] = [{'id': 's1', 'type': 'subtitle', 'start': 0.3, 'dur': 1.4, 'text': '置き場の確かめ'}]
    tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    def export(name, env):
        out = work / f'{name}.mp4'
        r = run([PY, '-X', 'utf8', '-B', '-m', 'mittler', 'video', str(tlf), str(out), '--jobs', '2'], env=env, cwd=str(ROOT / 'pyengine'))
        if r.returncode:
            print(r.stdout[-1500:], r.stderr[-1500:])
        return out

    env0 = {k: v for k, v in os.environ.items() if k not in ('MITTLER_CACHE_DIR', 'CC_CACHE_DIR')}
    # 2. 設定なし：作品の work/cache/frames
    o1 = export('plain', env0)
    inproj = list((proj / 'work' / 'cache' / 'frames').rglob('*.png')) if (proj / 'work' / 'cache' / 'frames').exists() else []
    check(o1.is_file() and len(inproj) > 0, f'2 設定なし：作品の work/cache/frames にためる（{len(inproj)} 枚）')
    shutil.rmtree(proj / 'work' / 'cache', ignore_errors=True)
    # 3. 設定あり：作品の外
    o2 = export('outside', dict(env0, MITTLER_CACHE_DIR=str(cdir)))
    roots = [p for p in cdir.iterdir() if p.is_dir()] if cdir.exists() else []
    out_frames = list(roots[0].joinpath('cache', 'frames').rglob('*.png')) if roots else []
    mark = roots[0] / '_project.txt' if roots else None
    check(len(roots) == 1 and roots[0].name.startswith('cdproj-') and len(out_frames) > 0, f'3 設定あり：置き場の下にためる（{roots[0].name if roots else "無し"}・{len(out_frames)} 枚）')
    check(not (proj / 'work' / 'cache').exists(), '3 設定あり：作品の work/cache は作らない')
    check(mark is not None and mark.is_file() and Path(mark.read_text(encoding='utf-8').strip()) == proj, '3 _project.txt に作品の場所')
    # 4. 同じ MP4
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ''
    check(sha(o1) and sha(o1) == sha(o2), f'4 置き場が違っても書き出しは同じ（{sha(o1)[:12]}）')
    # 5. 編集画面のサーバー（--cache-dir）：止めた 1 コマのためた絵も置き場の下・「ためた絵」の数と消すのも置き場を見る
    import re as _re
    import urllib.request
    shutil.rmtree(cdir, ignore_errors=True)
    srv = subprocess.Popen(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'serve', str(tlf), '--render-python', PY, '--cache-dir', str(cdir)],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=dict(env0, MITTLER_NO_REVEAL='1'), text=True, encoding='utf-8', errors='replace')
    url = srv.stdout.readline().strip()
    try:
        base, tok = url.split('/editor/')[0], _re.search(r'token=(\w+)', url).group(1)
        call = lambda path, body=None: urllib.request.urlopen(urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), method='POST' if body is not None else 'GET', headers={'X-Mittler-Token': tok}), timeout=180).read()
        for _ in range(240):
            if json.loads(call('/api/status')).get('ready'):
                break
            __import__('time').sleep(0.5)
        call('/api/frame?t=1.0')
        n = json.loads(call('/api/fcache', {}))
        jpgs = list(cdir.rglob('*.jpg'))
        check(len(jpgs) > 0 and not (proj / 'work' / 'cache').exists(), f'5 サーバー：止めた 1 コマのためた絵も置き場の下（{len(jpgs)} 枚）・作品の work/cache は作らない')
        check(n.get('frames', n.get('n', 0)) > 0 if isinstance(n, dict) else False, f'5 サーバー：ためた絵の数は置き場を見る（{n}）')
        call('/api/fcache', {'clear': True})
        check(not list(cdir.rglob('*.jpg')), '5 サーバー：「ためた絵を消す」は置き場の下を消す')
    finally:
        try:
            call('/api/quit', {})
        except Exception:  # noqa: BLE001
            pass
        try:
            srv.wait(timeout=45)
        except subprocess.TimeoutExpired:
            print('サーバーが止まらない', srv.pid)
finally:
    shutil.rmtree(work, ignore_errors=True)
print('smoke_cachedir: ' + ('OK' if not fails else f'FAIL {len(fails)}'))
sys.exit(1 if fails else 0)
