"""ディスクにためる絵（pyengine/mittler/fcache.py）の確かめ。2026-11-16
  <描画の python> -X utf8 tools/smoke_fcache.py [--work <フォルダ>] [--keep]

試しの作品（320×180・10fps・10 秒・画像 2 枚・エフェクト 2 本）で：
- 鍵：読み直しても同じ・数の書き方（3 と 3.0）で変わらない・遠くのクリップを直しても変わらない・近くのクリップ・設定・エフェクトのコードを直すと変わる・
  clips_of で読むほかのエフェクトのクリップを直すと変わる・音のトラックを直しても変わらない・ドラフト・マスターはためない
- 書き出し（mittler video）が全部のコマをためる・描画サーバーがそれを出す（X-Mittler-Cache: disk）・ためた絵と描いた絵がほぼ同じ（JPEG）・
  クリップを直すと、その区間だけ描き直す
"""
import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'pyengine'))
fails = []


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


TINT = '''"""試し：絵に色を足す"""
STAGE = 'v7'


def apply(ctx, f, clip):
    f[..., 0] += float(clip['params'].get('add', 20))
    return f
'''
READER = '''"""試し：tint のクリップの数だけ明るく（clips_of で読む）"""
STAGE = 'v7'


def apply(ctx, f, clip):
    return f + 10.0 * len(ctx.clips_of('tint'))
'''


def make(d):
    (d / 'effects' / '_lib').mkdir(parents=True, exist_ok=True)
    (d / 'assets').mkdir(exist_ok=True)
    (d / 'effects' / 'tint.py').write_text(TINT, encoding='utf-8')
    (d / 'effects' / 'reader.py').write_text(READER, encoding='utf-8')
    (d / 'effects' / '_lib' / 'helper.py').write_text('X = 1\n', encoding='utf-8')
    ff = ['ffmpeg', '-y', '-v', 'error']
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=10', '-frames:v', '1', str(d / 'assets' / 'a.png')], check=True)
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'mandelbrot=s=320x180:r=10', '-frames:v', '1', str(d / 'assets' / 'b.png')], check=True)
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'sine=frequency=330:duration=10', '-ar', '48000', '-ac', '2', str(d / 'assets' / 'tone.wav')], check=True)
    tl = {'format': 'mittler/py1', 'engine': 'mittler', 'name': 'smokefc', 'width': 320, 'height': 180, 'fps': 10, 'duration': 10.0, 'root': '.',
          'settings': {'export': {'video': {'preset': 'ultrafast', 'crf': 0}}}, 'meta': [],
          'tracks': [
              {'id': 't_fx', 'name': 'fx', 'kind': 'effect', 'clips': [
                  {'id': 'r1', 'type': 'effect', 'effect': 'reader', 'start': 1.0, 'dur': 1.0, 'params': {}},
                  {'id': 'k1', 'type': 'effect', 'effect': 'tint', 'start': 7.0, 'dur': 1.0, 'params': {'add': 30.0}}]},
              {'id': 't_v', 'name': 'v', 'kind': 'video', 'clips': [
                  {'id': 'v1', 'type': 'image', 'src': 'assets/a.png', 'start': 0, 'dur': 5},
                  {'id': 'v2', 'type': 'image', 'src': 'assets/b.png', 'start': 5, 'dur': 5}]},
              {'id': 't_a', 'name': 'a', 'kind': 'audio', 'clips': [{'id': 'a1', 'type': 'audio', 'src': 'assets/tone.wav', 'start': 0, 'dur': 10, 'gain': -12}]}]}
    f = d / 'smokefc.test.cut.json'
    f.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return f, tl


def write(f, tl, js=False):
    """js=True：編集画面（JS）の保存と同じに、整数の値の小数を整数で書く"""
    s = json.dumps(tl, ensure_ascii=False, indent=1)
    if js:
        from mittler.fcache import canon
        s = json.dumps(canon(tl), ensure_ascii=False, indent=1)
    f.write_text(s + '\n', encoding='utf-8')
    time.sleep(0.02)


def keys(f, ts=(1.5, 4.0, 6.0, 7.5)):
    from mittler import fcache
    from mittler.engine import Engine
    eng = Engine(f)
    try:
        return {t: fcache.key(eng, t) for t in ts}
    finally:
        eng.close()


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get(port, t):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/frame?t={t}&q=95', timeout=120) as r:
        return r.headers.get('X-Mittler-Cache'), r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', default='')
    ap.add_argument('--keep', action='store_true')
    a = ap.parse_args()
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix='mittler_smokefc_'))
    d = work / 'proj'
    shutil.rmtree(d, ignore_errors=True)
    f, tl = make(d)
    from mittler import fcache
    from mittler.engine import Engine

    # ---- 鍵
    k0 = keys(f)
    check(all(k0.values()) and len(set(k0.values())) == 4, '鍵：コマごとに作れて、時刻で違う')
    check(keys(f) == k0, '鍵：読み直しても同じ')
    write(f, tl, js=True)
    check(keys(f) == k0, '鍵：数の書き方（3.0 と 3）で変わらない')
    tl['tracks'][1]['clips'][1]['src'] = 'assets/a.png'  # v2（5〜10 秒）
    write(f, tl)
    k1 = keys(f)
    check(k1[1.5] == k0[1.5] and k1[4.0] != k0[4.0] and k1[6.0] != k0[6.0] and k1[7.5] != k0[7.5],
          '鍵：v2（5〜10 秒）を直すと、前後 2 秒（4・6・7.5 秒）だけ変わる（1.5 秒は同じ）')
    tl['tracks'][0]['clips'][1]['params']['add'] = 31.0  # tint（7〜8 秒）。reader（1〜2 秒）が clips_of('tint') で読む
    write(f, tl)
    k2 = keys(f)
    check(k2[7.5] != k1[7.5] and k2[1.5] != k1[1.5] and k2[4.0] == k1[4.0], '鍵：clips_of で読むエフェクトのクリップを直すと、読む側の区間も変わる（4 秒は同じ）')
    (d / 'effects' / 'reader.py').write_text(READER.replace("len(ctx.clips_of('tint'))", "len(ctx.eng.tl['tracks'])"), encoding='utf-8')  # タイムラインを読む（そのコマの時刻のつもり）
    ka = keys(f)
    tl['tracks'][0]['clips'][1]['params']['add'] = 32.0
    write(f, tl)
    kb = keys(f)
    check(kb[1.5] == ka[1.5] and kb[7.5] != ka[7.5], '鍵：タイムライン（.tl）を読むだけのエフェクトは、前後 2 秒のクリップで決める（遠くの tint を直しても 1.5 秒は同じ）')
    (d / 'effects' / 'reader.py').write_text(READER.replace("len(ctx.clips_of('tint'))", "len(ctx.eng.tl['tracks'])") + "\nCACHE = 'all'\n", encoding='utf-8')
    ka = keys(f)
    tl['tracks'][0]['clips'][1]['params']['add'] = 33.0
    write(f, tl)
    kb = keys(f)
    check(kb[1.5] != ka[1.5] and kb[4.0] == ka[4.0], "鍵：CACHE = 'all' と書いたエフェクトは、どこを直しても変わる（かかっていない 4 秒は同じ）")
    (d / 'effects' / 'reader.py').write_text(READER, encoding='utf-8')
    k2 = keys(f)
    tl['tracks'][2]['clips'][0]['gain'] = -6  # 音
    write(f, tl)
    check(keys(f) == k2, '鍵：音のトラックを直しても変わらない')
    time.sleep(0.05)
    (d / 'effects' / 'tint.py').write_text(TINT.replace('20', '21'), encoding='utf-8')
    k3 = keys(f)
    check(k3[7.5] != k2[7.5] and k3[1.5] != k2[1.5] and k3[4.0] == k2[4.0], '鍵：エフェクトのコードを直すと、使う区間（と読む側）だけ変わる')
    (d / 'effects' / '_lib' / 'helper.py').write_text('X = 2\n', encoding='utf-8')
    k4 = keys(f)
    check(all(k4[t] != k3[t] for t in k3), '鍵：effects/_lib を直すと全部変わる')
    tl['settings']['grain'] = 1
    write(f, tl)
    k5 = keys(f)
    check(all(k5[t] != k4[t] for t in k4), '鍵：settings を直すと全部変わる')
    tl['settings']['cache'] = {'frames_gb': 2}
    write(f, tl)
    check(keys(f) == k5, '鍵：settings.cache（ためる上限）は鍵に入らない')
    eng = Engine(f, draft=True)
    check(fcache.key(eng, 1.5) is None, 'ドラフトの描き方はためない')
    eng.close()
    eng = Engine(f, scale=2)
    check(fcache.key(eng, 1.5) is None, 'マスター（倍率 2）はためない')
    eng.close()

    eng = Engine(f, draft=True)
    check(fcache.key(eng, 1.5, draft_ok=True) is not None, 'ドラフトの描き方でも、ためた本番の絵は読める（draft_ok）')
    eng.close()

    # ---- 書き出しがためる（劣化なしの PNG・小さな JPEG）・差分書き出し
    py = sys.executable
    fc = d / 'work' / 'cache' / 'frames'
    shutil.rmtree(fc, ignore_errors=True)

    def export(name, *extra):
        r = subprocess.run([py, '-X', 'utf8', '-B', '-m', 'mittler', 'video', str(f), str(d / 'output' / name), '--jobs', '2', *extra],
                           cwd=str(ROOT / 'pyengine'), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
        m = re.search(r'^CACHED (\d+) (\d+)', r.stdout, re.M)
        return r, (int(m.group(1)) if m else None)

    def fmd5(name):
        r = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(d / 'output' / name), '-map', '0:v', '-f', 'framemd5', '-'], capture_output=True, text=True)
        return [ln.split(',')[-1].strip() for ln in r.stdout.splitlines() if ln and not ln.startswith('#')]

    def count(ext):
        return len(list(fc.glob(f'*/*{ext}')))
    r, c1 = export('o1.mp4')
    check(r.returncode == 0 and c1 == 0 and count('.png') == 100 and count('.p.jpg') == 100,
          f"書き出し（並列 2）が全部のコマを PNG と小さな JPEG でためた（{count('.png')}・{count('.p.jpg')}・使ったコマ {c1}）" + ('' if r.returncode == 0 else ' ' + r.stderr[-400:]))
    eng = Engine(f)
    same = all(np.array_equal(fcache.get(eng, t)[0], eng.render(t)) for t in (0.0, 1.5, 7.5))
    eng.close()
    check(same, 'ためた PNG が、描いた絵とビット単位で同じ')
    r, c2 = export('o2.mp4')
    check(r.returncode == 0 and c2 == 100 and fmd5('o1.mp4') == fmd5('o2.mp4') and len(fmd5('o1.mp4')) == 100,
          f'差分書き出し：直していなければ全部のコマ（{c2}）をためた絵から。書き出しのコマも同じ')
    tl['tracks'][1]['clips'][1]['src'] = 'assets/b.png'  # v2（5〜10 秒。上の鍵の確かめで a.png にしてある）。前後 2 秒の 3.1 秒より後が変わる
    write(f, tl)
    r, c3 = export('o3.mp4')
    r4, c4 = export('o4.mp4', '--no-cache')
    check(r.returncode == 0 and c3 == 31 and c4 == 0 and fmd5('o3.mp4') == fmd5('o4.mp4'),
          f'差分書き出し：v2 を直すと、変わらない頭の 31 コマだけ使う（{c3}）。全部描いた書き出し（--no-cache・使ったコマ {c4}）とコマが同じ')
    r, c5 = export('o5.mp4', '--draft', '--step', '2', '--scale', '0.5')
    check(r.returncode == 0 and c5 == 50, f'ドラフトの書き出しも、ためた本番の絵を使う（50 コマのうち {c5}）')

    # ---- 描画サーバー：ためた絵を出す・覚えた絵は直した区間だけ捨てる・ためた絵の地図
    port = free_port()
    sv = subprocess.Popen([py, '-X', 'utf8', '-B', '-m', 'mittler', 'serve', str(f), '--port', str(port), '--ahead', '0'], cwd=str(ROOT / 'pyengine'),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/info', timeout=2).read()
                break
            except OSError:
                time.sleep(0.2)
        h1, b1 = get(port, 1.5)
        h2, b2 = get(port, 6.0)
        check(h1 == 'disk' and h2 == 'disk', f'描画サーバー：書き出しでためた絵を出す（{h1}・{h2}）')
        from io import BytesIO

        from PIL import Image
        eng = Engine(f)
        ref = eng.render(1.5)
        eng.close()
        b = BytesIO()
        Image.fromarray(ref).save(b, 'JPEG', quality=95)
        check(Image.open(BytesIO(b1)).tobytes() == Image.open(b).tobytes(), 'ためた絵から出した JPEG が、描いた絵の JPEG と同じ')
        cm = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/cachemap', timeout=60).read())
        check(len(cm['keys']) == 100 and all(cm['keys']) and cm['fps'] == 10, f"ためた絵の地図：100 コマ全部に鍵（{sum(map(bool, cm['keys']))}）")
        n0 = count('.png')
        tl['tracks'][1]['clips'][1]['label'] = 'v2 new'  # まだためていない状態（上の書き出しで a.png・b.png の両方をためてある）
        write(f, tl)
        h1, _ = get(port, 1.5)
        h2, _ = get(port, 6.0)
        check(h1 == 'disk' and h2 is None, f'v2 を直したあと：1.5 秒はためた絵（覚えた絵も残る）、6 秒は描き直す（{h1}・{h2}）')
        h3, _ = get(port, 6.1)
        check(h3 is None and count('.png') == n0 + 2, f"描画サーバーが描いたコマもためる（{count('.png') - n0}）")
        h4, _ = get(port, 6.0)
        check(h4 == 'disk', f'描いたコマは次からためた絵（{h4}）')
        cm = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/cachemap', timeout=60).read())
        miss = [i for i, k in enumerate(cm['keys']) if not k]
        check(len(miss) == 67 and 60 not in miss and 61 not in miss and 30 not in miss,
              f'ためた絵の地図：直した区間の、まだ描いていないコマだけ空（{len(miss)}）')
        # ---- 裏で先に描く（bake）：止める印があれば描かない・無ければ残りを全部
        stop = d / 'work' / 'bake.stop'
        stop.write_text('x', encoding='utf-8')
        bake = [py, '-X', 'utf8', '-B', '-m', 'mittler', 'bake', str(f), '--from', '3', '--jobs', '2', '--chunk', '10', '--stop', str(stop)]
        r = subprocess.run(bake, cwd=str(ROOT / 'pyengine'), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
        check(r.returncode == 0 and 'BAKE_DONE' in r.stdout and count('.png') == n0 + 2, f"bake：止める印があれば描かない（{count('.png') - n0 - 2}）")
        stop.unlink()
        r = subprocess.run(bake, cwd=str(ROOT / 'pyengine'), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
        cm = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/cachemap', timeout=60).read())
        check(r.returncode == 0 and 'BAKE 67 67' in r.stdout and all(cm['keys']),
              f"bake：残りの 67 コマを描いてためた（地図の空き {cm['keys'].count('')}・{r.stdout.strip().splitlines()[-2:]}）" + ('' if r.returncode == 0 else r.stderr[-300:]))
        h5, _ = get(port, 8.0)
        check(h5 == 'disk', f'bake でためたコマを描画サーバーが出す（{h5}）')
    finally:
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/quit', timeout=5).read()
        except OSError:
            pass
        try:
            sv.wait(timeout=20)
        except subprocess.TimeoutExpired:
            sv.kill()

    # ---- bake の一時停止（<止める印>.pause があるあいだ、区間のプロセスを止める。消すと描きかけから続く）：1 コマ 0.12 秒の遅いエフェクトで
    (d / 'effects' / 'slow.py').write_text('"""試し：遅い"""\nimport time\nSTAGE = "v7"\n\n\ndef apply(ctx, f, clip):\n    time.sleep(0.12)\n    return f\n', encoding='utf-8')
    tl['tracks'][0]['clips'].append({'id': 's1', 'type': 'effect', 'effect': 'slow', 'start': 0, 'dur': 10, 'params': {}})
    write(f, tl)
    stop = d / 'work' / 'bake2.stop'
    pause = Path(str(stop) + '.pause')
    pr = subprocess.Popen([py, '-X', 'utf8', '-B', '-m', 'mittler', 'bake', str(f), '--from', '0', '--jobs', '2', '--chunk', '10', '--stop', str(stop)],
                          cwd=str(ROOT / 'pyengine'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    base = count('.png')
    try:
        t0 = time.time()
        while count('.png') < base + 8 and time.time() - t0 < 60:
            time.sleep(0.1)
        pause.write_text('pause', encoding='utf-8')
        time.sleep(0.6)  # 止まるまで（0.1 秒ごとに見る＋描きかけのコマの書き込み）
        a1 = count('.png')
        time.sleep(2.0)
        a2 = count('.png')
        check(a2 - a1 <= 1 and a1 - base < 100, f'bake の一時停止：止めているあいだは描かない（{a1 - base} → {a2 - base} コマ）')
        pause.unlink()
        out, _ = pr.communicate(timeout=300)
        check(pr.returncode == 0 and 'BAKE_PAUSED' in out and 'BAKE_RESUMED' in out and count('.png') == base + 100,
              f"bake の一時停止：消すと続けて、最後まで描く（{'BAKE_PAUSED' in out}・{'BAKE_RESUMED' in out}）")
        eng = Engine(f)
        left = [n for n in range(100) if not fcache.has(eng, n / 10)[1]]
        eng.close()
        check(not left, f'bake の一時停止：止めて続けても、全部のコマがためてある（残り {len(left)}）')
    finally:
        if pr.poll() is None:
            pr.kill()
    eng = Engine(f)
    st = fcache.stats(eng)
    n = fcache.clear(eng)
    check(n == st['frames'] and not list(fc.glob('*/*')), f'ためた絵を消せる（{n}）')
    eng.close()

    print(json.dumps({'ok': not fails, 'fails': fails, 'work': str(work)}, ensure_ascii=False))
    if not a.keep and not a.work:
        shutil.rmtree(work, ignore_errors=True)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
