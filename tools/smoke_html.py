"""HTML のレイヤー（effects_lib/common/html.py・pyengine/mittler/htmllayer.py・html_runtime.js・templates/html/）の確かめ（2026-11-18）。
  <描画の python> -X utf8 tools/smoke_html.py [--work <フォルダ>] [--keep]
描く python に Playwright と Chromium が要る（無ければ SKIP と出して終わる）。自分で試しの作品を作り、エンジンのコマンド（python -m mittler stills・video）と
編集画面のサーバー（tools/mittler.cmd serve。「作品に入れる」）で確かめる。ユーザーの作品には触らない。確かめること：
- 「作品に入れる」（/api/effects/add html）で、ひな形のページ 3 つと three.js が作品の html/ に入る
- ひな形 3 つ（文字の動き・three.js の光る粒・three.js の立体の形）が描ける（重ねる前と絵が違う）
- 同じ時刻は同じ絵：別のプロセスで 2 回・前のコマを描いてから・書き出し（並列 2・劣化なし）の同じコマ
- 種（seed）を変えると絵が変わる・args がページに届く
- ページのフォルダ・vendor/ を直すと、ためた絵（fcache）の鍵が変わる。関係ない素材では変わらない
- ページの JavaScript のエラー・ページが無いときは、理由つきで止まる
- ページのサーバーは作品の html/・assets/ だけを配る（状態フォルダ・タイムラインは 403）
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'pyengine'))
fails = []


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


def run(cmd, timeout=900):
    return subprocess.run([str(c) for c in cmd], cwd=str(ROOT / 'pyengine'), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)


def sha(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


def make(d):
    (d / 'effects').mkdir(parents=True, exist_ok=True)
    (d / 'assets').mkdir(exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'gradients=s=480x270:c0=0x101830:c1=0x403060:speed=0.01', '-frames:v', '1',
                    str(d / 'assets' / 'bg.png')], check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=330:duration=12', '-ar', '48000', '-ac', '2', str(d / 'assets' / 'tone.wav')], check=True)
    tl = {'format': 'mittler/py1', 'engine': 'mittler', 'name': 'smokehtml', 'width': 480, 'height': 270, 'fps': 30, 'duration': 12.0, 'root': '.',
          'settings': {'export': {'video': {'preset': 'ultrafast', 'crf': 0}}}, 'meta': [],
          'tracks': [
              {'id': 't_fx', 'name': 'fx', 'kind': 'effect', 'clips': [
                  {'id': 'k1', 'type': 'effect', 'effect': 'html', 'start': 0, 'dur': 4, 'params': {'page': 'html/kinetic/index.html', 'args': {'text': 'Mittler 映像'}}},
                  {'id': 'p1', 'type': 'effect', 'effect': 'html', 'start': 4, 'dur': 4, 'params': {'page': 'html/particles3d/index.html', 'args': {}, 'blend': 'add'}},
                  {'id': 's1', 'type': 'effect', 'effect': 'html', 'start': 8, 'dur': 4, 'params': {'page': 'html/shapes3d/index.html', 'args': {}}}]},
              {'id': 't_v', 'name': 'v', 'kind': 'video', 'clips': [{'id': 'v1', 'type': 'image', 'src': 'assets/bg.png', 'start': 0, 'dur': 12}]},
              {'id': 't_a', 'name': 'a', 'kind': 'audio', 'clips': [{'id': 'a1', 'type': 'audio', 'src': 'assets/tone.wav', 'start': 0, 'dur': 12, 'gain': -12}]}]}
    f = d / 'smokehtml.test.cut.json'
    f.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return f, tl


def write(f, tl):
    f.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def stills(py, tl, at, out):
    return run([py, '-X', 'utf8', '-B', '-m', 'mittler', 'stills', tl, '--at', at, '--out', out])


def add_via_server(d, tlf):
    """編集画面のサーバーを立てて「作品に入れる」（/api/effects/add html）"""
    env = dict(os.environ, MITTLER_NO_REVEAL='1')
    nd = shutil.which('node')  # PATH の node があればそれ（VS Code の無いアカウントでも）。無ければ tools\mittler.cmd（VS Code の Node）
    head = [nd, str(ROOT / 'server' / 'main.js')] if nd else ['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'serve']
    p = subprocess.Popen(head + [str(tlf), '--port', '0', '--render-python', sys.executable, '--lang', 'ja'],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True, encoding='utf-8', errors='replace')
    url = p.stdout.readline().strip()
    base, token = url.split('/editor/')[0], re.search(r'token=(\w+)', url).group(1)

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method='POST', headers={'X-Mittler-Token': token, 'Content-Type': 'application/json'})
        return json.loads(urllib.request.urlopen(req, timeout=120).read())
    try:
        return post('/api/effects/add', {'name': 'html'})
    finally:
        try:
            post('/api/quit', {})
        except Exception:  # noqa: BLE001
            pass
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', default='')
    ap.add_argument('--keep', action='store_true')
    a = ap.parse_args()
    py = sys.executable
    from mittler.defaults import author
    env = dict(os.environ)  # Chromium の置き場：環境変数 → 作者の PC の既定（htmllayer.py と同じ）
    bp = author('playwrightBrowsers', '')
    if bp and os.path.isdir(bp) and not env.get('PLAYWRIGHT_BROWSERS_PATH'):
        env['PLAYWRIGHT_BROWSERS_PATH'] = bp
    r = subprocess.run([py, '-c', 'from playwright.sync_api import sync_playwright\nwith sync_playwright() as p:\n b = p.chromium.launch(); b.close()'], capture_output=True, text=True, timeout=180, env=env)
    if r.returncode:
        print('SKIP 描く python で Playwright の Chromium が起動しない（HTML のレイヤーを使わない PC では要らない）：' + (r.stderr or '').strip().splitlines()[-1:][0][:200] if r.stderr else '')
        print(json.dumps({'ok': True, 'skipped': True}))
        return
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix='mittler_smokehtml_'))
    d = work / 'proj'
    shutil.rmtree(d, ignore_errors=True)
    tlf, tl = make(d)
    out = work / 'out'
    shutil.rmtree(out, ignore_errors=True)

    # ---- 「作品に入れる」
    r = add_via_server(d, tlf)
    copied = r.get('copied') or []
    need = ['effects/html.py', 'html/kinetic/index.html', 'html/particles3d/index.html', 'html/shapes3d/index.html', 'html/vendor/three.module.min.js', 'html/vendor/three.LICENSE']
    check(r.get('ok') and all(x in copied for x in need) and all((d / x).is_file() for x in need), f'「作品に入れる」で、ひな形のページと three.js が html/ に入る（{len(copied)} ファイル）')

    # ---- 描ける・重ねる前と違う
    plain = d / 'plain.test.cut.json'
    write(plain, dict(tl, tracks=[t for t in tl['tracks'] if t['kind'] != 'effect']))
    r0 = stills(py, plain, '1.5,6.5,10.5', out / 'plain')
    r1 = stills(py, tlf, '1.5,6.5,10.5', out / 'a')
    ok = r0.returncode == 0 and r1.returncode == 0
    diff = [t for t in ('001.500', '006.500', '010.500') if ok and sha(out / 'plain' / f'still_{t}.png') != sha(out / 'a' / f'still_{t}.png')]
    check(ok and len(diff) == 3, f'ひな形 3 つ（文字・光る粒・立体の形）が描ける（重ねる前と違う：{diff}）' + ('' if ok else ' ' + (r0.stderr + r1.stderr)[-500:]))
    # ---- 同じ時刻は同じ絵
    r2 = stills(py, tlf, '1.5,6.5,10.5', out / 'b')
    r3 = stills(py, tlf, '9.0,5.0,0.5,10.5,6.5,1.5', out / 'c')
    same = all(sha(out / 'a' / f'still_{t}.png') == sha(out / x / f'still_{t}.png') for t in ('001.500', '006.500', '010.500') for x in ('b', 'c'))
    check(r2.returncode == 0 and r3.returncode == 0 and same, '同じ時刻は同じ絵（別のプロセスで 2 回・前のコマを描いてから）')
    r = run([py, '-X', 'utf8', '-B', '-m', 'mittler', 'video', tlf, out / 'v.mp4', '--jobs', '2', '--no-cache'], timeout=900)

    def fmd5(src, rng=None):
        cmd = ['ffmpeg', '-v', 'error', '-i', str(src)] + (['-pix_fmt', 'yuv420p'] if rng is None else []) + ['-map', '0:v', '-f', 'framemd5', '-']
        rr = subprocess.run(cmd, capture_output=True, text=True)
        return [ln.split(',')[-1].strip() for ln in rr.stdout.splitlines() if ln and not ln.startswith('#')]
    vid = fmd5(out / 'v.mp4', True) if r.returncode == 0 else []
    ok = r.returncode == 0 and len(vid) == 360 and all(fmd5(out / 'a' / f'still_{t}.png')[0] == vid[n] for t, n in (('001.500', 45), ('006.500', 195), ('010.500', 315)))
    check(ok, f'書き出し（並列 2・劣化なし）の同じコマが静止画と同じ（{len(vid)} コマ）' + ('' if r.returncode == 0 else ' ' + (r.stderr + r.stdout)[-500:]))
    # ---- 種・args
    t2 = json.loads(json.dumps(tl))
    t2['tracks'][0]['clips'][1]['params']['seed'] = 7
    t2['tracks'][0]['clips'][0]['params']['args']['text'] = 'ABC'
    f2 = d / 'seed.test.cut.json'
    write(f2, t2)
    r = stills(py, f2, '1.5,6.5', out / 's')
    check(r.returncode == 0 and sha(out / 's' / 'still_006.500.png') != sha(out / 'a' / 'still_006.500.png'), '種（seed）を変えると絵が変わる')
    check(r.returncode == 0 and sha(out / 's' / 'still_001.500.png') != sha(out / 'a' / 'still_001.500.png'), 'args がページに届く（字を変えると絵が変わる）')
    # ---- ためた絵の鍵
    from mittler import fcache
    from mittler.engine import Engine

    def key(t):
        eng = Engine(tlf)
        try:
            return fcache.key(eng, t)
        finally:
            eng.close()
    k0 = (key(1.5), key(6.5))
    time.sleep(0.05)
    (d / 'html' / 'kinetic' / 'note.txt').write_text('x', encoding='utf-8')
    k1 = (key(1.5), key(6.5))
    (d / 'html' / 'vendor' / 'extra.js').write_text('// x\n', encoding='utf-8')
    k2 = (key(1.5), key(6.5))
    (d / 'assets' / 'other.png').write_bytes((d / 'assets' / 'bg.png').read_bytes())
    k3 = (key(1.5), key(6.5))
    check(k1[0] != k0[0] and k1[1] == k0[1] and k2[0] != k1[0] and k2[1] != k1[1] and k3 == k2,
          'ためた絵の鍵：ページのフォルダを直すとそのページのコマだけ・vendor/ を直すと全部のページのコマが変わる・関係ない素材では変わらない')
    # ---- エラー
    (d / 'html' / 'bad').mkdir(exist_ok=True)
    (d / 'html' / 'bad' / 'index.html').write_text('<script>mittler.onFrame(t => { if (t > 0.5) undefinedFunction(); });</script>', encoding='utf-8')
    t3 = json.loads(json.dumps(tl))
    t3['tracks'][0]['clips'] = [{'id': 'b1', 'type': 'effect', 'effect': 'html', 'start': 0, 'dur': 2, 'params': {'page': 'html/bad/index.html'}},
                                {'id': 'b2', 'type': 'effect', 'effect': 'html', 'start': 2, 'dur': 2, 'params': {'page': 'html/nothing/index.html'}}]
    f3 = d / 'bad.test.cut.json'
    write(f3, t3)
    r = stills(py, f3, '1.0', out / 'e1')
    JA = json.loads((ROOT / 'editor' / 'i18n' / 'ja.json').read_text(encoding='utf-8'))  # 止まるときの文は辞書から（言い回しを直しても、この確かめを直さなくて済むように）
    head = lambda k: JA[k].split('（')[0]
    check(r.returncode != 0 and head('html.jsError') in r.stderr and 'undefinedFunction' in r.stderr, 'ページの JavaScript のエラーは理由つきで止まる')
    r = stills(py, f3, '3.0', out / 'e2')
    check(r.returncode != 0 and head('html.noPage') in r.stderr, 'ページが無いときは理由つきで止まる')
    r = stills(py, f3, '0.2', out / 'e3')
    check(r.returncode == 0, 'エラーになる前の時刻は描ける')
    # ---- ページのサーバーが配るもの
    from mittler import htmllayer
    srv = htmllayer._server(d)
    try:
        base = f'http://127.0.0.1:{srv.server_address[1]}/'

        def code(path):
            try:
                with urllib.request.urlopen(base + path, timeout=10) as rr:
                    return rr.status, rr.headers.get('Content-Type', '')
            except urllib.error.HTTPError as e:
                return e.code, ''
        c1, ty = code('html/vendor/three.module.min.js')
        c2, _ = code('assets/bg.png')
        c3, _ = code('smokehtml.test.cut.json')
        c4, _ = code('html/../smokehtml.test.cut.json')
        check(c1 == 200 and 'javascript' in ty and c2 == 200 and c3 == 403 and c4 == 403, f'ページのサーバーは html/・assets/ だけ（{c1} {ty}・{c2}・{c3}・{c4}）')
    finally:
        srv.shutdown()

    print(json.dumps({'ok': not fails, 'fails': fails, 'work': str(work)}, ensure_ascii=False))
    if not a.keep and not a.work:
        shutil.rmtree(work, ignore_errors=True)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
