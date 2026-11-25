"""3D のエフェクト（GPU の 3D・moderngl の gl_*、Blender の 3D・blender3d）の確かめ（2026-11-13）。サーバーもブラウザも要らない。描画の python で流す。
  <描画の python> -X utf8 tools/smoke_3d.py [--work <フォルダ>] [--require-gl] [--blender <blender.exe>] [--keep]
自分で試しの作品（lavfi の素材）を作り、エンジンのコマンド（python -m mittler stills・video）で確かめる。ユーザーの作品には触らない。
いつも確かめること（GL・Blender が無い PC でも）：
- 3D を使わない作品は、moderngl が無くても（MITTLER_NO_GL=1 でも）描ける。3D のエフェクトのファイルが作品にあっても、かかっていない時刻は描ける
- GL が使えないと、3D のエフェクトがかかる時刻は「3D の描画が使えない（理由）」で止まる（黙って抜かさない）
- Blender が見つからないと、Blender の 3D がかかる時刻・書き出しは「Blender が見つからない」で止まる
- 名前の決まり：pyengine/mittler/blender.py の BLENDER_DEFAULT と server/defaults.js の blenderPath が同じ。効果のファイルの META に gl3d・blender の印
--require-gl（GPU のある PC）：3 本の gl_* が描ける・同じ時刻の静止画が 2 回とも同じ・静止画と書き出し（並列 1 と 3）の同じコマが同じ（crf 0 の書き出しで比べる）・
  ドラフト（--draft）でも 2 回とも同じ
--blender <exe>（Blender のある PC）：Blender のクリップの静止画が描ける・2 回目はためた絵（同じ絵）・書き出しの前にまとめて描く（PHASE blender）・
  静止画と書き出し（並列 1 と 3）の同じコマが同じ・プレビュー（eng.preview）は下描きの品質の別のフォルダ・書き出しを .cancel で止めると Blender も止まる
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = []


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(cmd, env=None, timeout=900, cwd=None):
    e = dict(os.environ, MITTLER_LANG='ja', PYTHONUNBUFFERED='1')
    e.update(env or {})
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding='utf-8', errors='replace', env=e, timeout=timeout,
                          cwd=str(cwd or ROOT / 'pyengine'))


def make_project(d, blender):
    """試しの作品：640×360・30fps・4 秒。映像は lavfi の絵、3D のエフェクト 3 本（1〜3 秒）、Blender（2〜3 秒、--blender のとき）"""
    (d / 'effects').mkdir(parents=True, exist_ok=True)
    (d / 'assets').mkdir(exist_ok=True)
    for n in ('gl_cards3d', 'gl_particles3d', 'gl_lightrays', 'blender3d', 'fade'):
        shutil.copyfile(ROOT / 'effects_lib' / 'common' / f'{n}.py', d / 'effects' / f'{n}.py')
    (d / '3d').mkdir(exist_ok=True)
    shutil.copyfile(ROOT / 'templates' / '3d' / 'logo.py', d / '3d' / 'logo.py')
    ff = ['ffmpeg', '-y', '-v', 'error']
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=30', '-frames:v', '1', str(d / 'assets' / 'bg.png')], check=True)
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'mandelbrot=s=320x180:r=30', '-t', '2', '-pix_fmt', 'yuv420p', str(d / 'assets' / 'clip.mp4')], check=True)
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'sine=frequency=330:duration=4', '-ar', '48000', '-ac', '2', str(d / 'assets' / 'tone.wav')], check=True)
    fx = lambda i, n, s, du, p: {'id': f't_{n}', 'name': n, 'kind': 'effect', 'effect': n, 'clips': [{'id': f'{n}{i}', 'type': 'effect', 'effect': n, 'start': s, 'dur': du, 'params': p}]}
    tracks = []
    if blender:
        tracks.append(fx(1, 'blender3d', 2.0, 1.0, {'scene': '3d/logo.py', 'args': {'text': 'Mi'}, 'samples': 8, 'draft_samples': 2, 'draft_scale': 0.5}))
    tracks += [fx(1, 'gl_lightrays', 1.0, 2.0, {'count': 80}), fx(1, 'gl_particles3d', 1.0, 2.0, {'count': 300}),
               fx(1, 'gl_cards3d', 1.0, 2.0, {'sources': ['assets/clip.mp4', '@frame', 'assets/bg.png']}),
               {'id': 't_v', 'name': '映像', 'kind': 'video', 'clips': [{'id': 'v1', 'type': 'image', 'src': 'assets/bg.png', 'start': 0, 'dur': 4}]},
               {'id': 't_a', 'name': '音', 'kind': 'audio', 'role': 'bgm', 'clips': [{'id': 'a1', 'type': 'audio', 'src': 'assets/tone.wav', 'start': 0, 'dur': 4, 'in': 0, 'gain': -12}]}]
    tl = {'format': 'mittler/py1', 'engine': 'mittler', 'name': 'smoke3d', 'width': 640, 'height': 360, 'fps': 30, 'duration': 4.0, 'root': '.',
          'settings': {'export': {'video': {'preset': 'ultrafast', 'crf': 0}}}, 'meta': [], 'tracks': tracks}
    f = d / 'smoke3d.test.cut.json'
    f.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    plain = dict(tl, tracks=[t for t in tracks if t['kind'] != 'effect'])  # 3D のエフェクトを置かない写し（effects/ には 3D のファイルがある）
    f2 = d / 'plain.test.cut.json'
    f2.write_text(json.dumps(plain, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return f, f2


def stills(py, tl, at, out, env=None, extra=()):
    return run([py, '-X', 'utf8', '-B', '-m', 'mittler', 'stills', tl, '--at', at, '--out', out] + list(extra), env=env)


def framemd5(mp4):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(mp4), '-map', '0:v', '-f', 'framemd5', '-'], capture_output=True, text=True)
    return [ln.split(',')[-1].strip() for ln in r.stdout.splitlines() if ln and not ln.startswith('#')]


def png_md5(png):
    """静止画を、書き出しと同じ RGB → yuv420p の変換にかけたコマの md5（書き出しのコマと比べる）"""
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(png), '-pix_fmt', 'yuv420p', '-f', 'framemd5', '-'], capture_output=True, text=True)
    return [ln.split(',')[-1].strip() for ln in r.stdout.splitlines() if ln and not ln.startswith('#')][0]


def toolhelp_names():
    """動いているプロセスの exe の名前の数（Toolhelp。WMI が断られるサービス用のアカウントでも見える）"""
    sys.path.insert(0, str(ROOT / 'pyengine'))
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('pid', wintypes.DWORD), ('heapId', ctypes.c_void_p),
                    ('moduleId', wintypes.DWORD), ('threads', wintypes.DWORD), ('ppid', wintypes.DWORD), ('basePri', ctypes.c_long),
                    ('flags', wintypes.DWORD), ('exe', ctypes.c_wchar * 260)]
    k = ctypes.WinDLL('kernel32')
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(2, 0)
    e = PE(); e.dwSize = ctypes.sizeof(PE)
    out = []
    ok = k.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out.append(e.exe.lower())
        ok = k.Process32NextW(snap, ctypes.byref(e))
    k.CloseHandle(snap)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', default='')
    ap.add_argument('--require-gl', action='store_true')
    ap.add_argument('--blender', default='')
    ap.add_argument('--keep', action='store_true')
    a = ap.parse_args()
    py = sys.executable
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix='mittler_smoke3d_'))
    work.mkdir(parents=True, exist_ok=True)
    d = work / 'proj'
    if d.exists():
        shutil.rmtree(d)
    tl, plain = make_project(d, bool(a.blender))
    out = work / 'out'
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    nogl = {'MITTLER_NO_GL': '1'}
    nobl = {'MITTLER_BLENDER': str(work / 'no_blender.exe')}

    # ---- 名前の決まり
    sys.path.insert(0, str(ROOT / 'pyengine'))
    from mittler import blender as B
    # server/defaults.js の blenderPath を Node で読む（値は defaults.author.json から。無ければ空）
    nd = shutil.which('node')
    r = subprocess.run(([nd] if nd else ['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node']) +
                       ['-e', 'process.stdout.write(JSON.stringify(require(process.argv[1]).blenderPath))', str(ROOT / 'server' / 'defaults.js')],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    js = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    check(js is not None and js == B.BLENDER_DEFAULT, f'Blender の既定の場所が JS と Python で同じ（{B.BLENDER_DEFAULT or "空＝PATH の blender"}）')
    for n in ('gl_cards3d', 'gl_particles3d', 'gl_lightrays'):
        s = (ROOT / 'effects_lib' / 'common' / f'{n}.py').read_text(encoding='utf-8')
        check("'gl3d': True" in s and 'label_en' in s and 'DOC_EN' in s, f'{n} の META に gl3d の印・label_en・DOC_EN')
    check("'blender': True" in (ROOT / 'effects_lib' / 'common' / 'blender3d.py').read_text(encoding='utf-8'), 'blender3d の META に blender の印')

    # ---- ためた絵の鍵（Blender なしで、場所と版を差しかえて）：数の書き方 3 と 3.0 で鍵が変わらない・前の鍵のフォルダを付けかえて使い回す
    kp = work / 'keyproj'
    shutil.rmtree(kp, ignore_errors=True)
    (kp / '3d').mkdir(parents=True)
    (kp / '3d' / 's.py').write_text('# key test\n', encoding='utf-8')
    fe = types.SimpleNamespace(root=kp, dir=kp, W=640, H=360, fps=30.0)
    fake = work / 'fake_blender.exe'
    fake.write_bytes(b'')
    find0, ver0 = B.find, B.version
    B.find, B.version = (lambda: str(fake)), (lambda exe: 'Blender 0.0.0 test')
    try:
        ca = {'id': 'k1', 'start': 0.0, 'dur': 2.0, 'params': {'scene': '3d/s.py', 'samples': 64.0, 'args': {'a': 3.0, 'b': [1.0, 0.5], 'c': {'z': 0.0}}}}
        cb = {'id': 'k1', 'start': 0, 'dur': 2, 'params': {'scene': '3d/s.py', 'samples': 64, 'args': {'a': 3, 'b': [1, 0.5], 'c': {'z': 0}}}}
        cc = {'id': 'k1', 'start': 0, 'dur': 2, 'params': {'scene': '3d/s.py', 'samples': 64, 'args': {'a': 3.5, 'b': [1, 0.5], 'c': {'z': 0}}}}
        spa, da = B.spec(fe, ca, 'full')
        _, db = B.spec(fe, cb, 'full')
        _, dc = B.spec(fe, cc, 'full')
        check(da == db and da != dc, f'Blender の鍵：3 と 3.0 は同じ鍵・違う値（3.5）は別の鍵（{da.name}・{dc.name}）')
        check(spa['args']['a'] == 3.0 and isinstance(spa['args']['a'], float), 'Blender の鍵：Blender に渡す値は書いたまま（3.0 は 3.0）')
        old = da.parent / B._key(dict({k: v for k, v in spa.items() if k not in ('exe', 'scene_path', 'root', 'out', 'kit_dir')}))
        old.mkdir(parents=True)
        (old / '000000.png').write_bytes(b'x')
        _, dm = B.spec(fe, ca, 'full')
        check(dm == da and (dm / '000000.png').exists() and not old.exists(), 'Blender の鍵：前の鍵（数の書き方で変わっていたもの）のフォルダを付けかえて使い回す')
    finally:
        B.find, B.version = find0, ver0
        shutil.rmtree(kp, ignore_errors=True)

    # ---- GL・Blender が無いとき
    r = stills(py, plain, '0.5,2.5', out / 'plain', env=dict(nogl, **nobl))
    check(r.returncode == 0 and len(list((out / 'plain').glob('*.png'))) == 2, '3D を置かない作品は、GL も Blender も無くても描ける' + ('' if r.returncode == 0 else ' ' + r.stderr[-300:]))
    r = stills(py, tl, '0.5', out / 'before', env=dict(nogl, **nobl))
    check(r.returncode == 0, '3D のエフェクトがかかっていない時刻は、GL・Blender が無くても描ける' + ('' if r.returncode == 0 else ' ' + r.stderr[-300:]))
    r = stills(py, tl, '1.5', out / 'nogl', env=dict(nogl, **nobl))
    gl_off = json.loads((ROOT / 'editor' / 'i18n' / 'ja.json').read_text(encoding='utf-8'))['gl3d.off'].split('：')[0]  # 止まるときの文の頭は辞書から（言い回しを直しても、この確かめを直さなくて済むように）
    check(r.returncode != 0 and gl_off in r.stderr, 'GL が使えないと、3D のエフェクトの時刻は理由つきで止まる' + ('' if r.returncode else '（描けてしまった）'))
    if a.blender:
        r = stills(py, tl, '2.5', out / 'nobl', env=nobl)
        check(r.returncode != 0 and 'Blender が見つからない' in r.stderr, 'Blender が無いと、Blender の時刻は「Blender が見つからない」で止まる')
        r = run([py, '-X', 'utf8', '-B', '-m', 'mittler', 'video', tl, out / 'nobl.mp4', '--jobs', '2', '--from', '2', '--to', '2.5'], env=nobl)
        check(r.returncode != 0 and 'Blender が見つからない' in (r.stderr + r.stdout), 'Blender が無いと、書き出しも理由つきで止まる')

    # ---- GL があるとき
    if a.require_gl:
        at = '1.0,1.5,2.0,2.9'
        r1 = stills(py, tl, at, out / 'g1', env=nobl if not a.blender else None)
        r2 = stills(py, tl, at, out / 'g2', env=nobl if not a.blender else None)
        ok = r1.returncode == 0 and r2.returncode == 0
        check(ok, 'GL：3D のエフェクトの静止画が描ける' + ('' if ok else ' ' + (r1.stderr + r2.stderr)[-400:]))
        if ok:
            same = all(sha(p) == sha(out / 'g2' / p.name) for p in (out / 'g1').glob('*.png'))
            check(same, 'GL：同じ時刻の静止画が 2 回とも同じ（4 時刻）')
            r = stills(py, tl, '1.5', out / 'd1', extra=['--draft']); r2 = stills(py, tl, '1.5', out / 'd2', extra=['--draft'])
            check(r.returncode == 0 and r2.returncode == 0 and sha(out / 'd1' / 'still_001.500.png') == sha(out / 'd2' / 'still_001.500.png'), 'GL：ドラフトでも 2 回とも同じ')
            if True:  # 書き出しと静止画（1〜2 秒。Blender のクリップは 2 秒から＝かからない。Blender は下で）
                vids = {}
                for j in (1, 3):
                    r = run([py, '-X', 'utf8', '-B', '-m', 'mittler', 'video', tl, out / f'g_j{j}.mp4', '--jobs', str(j), '--from', '1', '--to', '2'], env=nobl)
                    check(r.returncode == 0, f'GL：書き出し（並列 {j}）' + ('' if r.returncode == 0 else ' ' + (r.stderr + r.stdout)[-400:]))
                    vids[j] = framemd5(out / f'g_j{j}.mp4') if r.returncode == 0 else []
                check(vids[1] and vids[1] == vids[3], f'GL：並列 1 と 3 の書き出しのコマが同じ（{len(vids[1])} コマ）')
                if vids[1]:
                    check(png_md5(out / 'g1' / 'still_001.500.png') == vids[1][15], 'GL：静止画（1.5 秒）と書き出しの同じコマが同じ')

    # ---- Blender があるとき
    if a.blender:
        env = {'MITTLER_BLENDER': a.blender}
        t0 = time.time()
        r = stills(py, tl, '2.5', out / 'b1', env=env)
        t1 = time.time()
        check(r.returncode == 0, f'Blender：静止画が描ける（{t1 - t0:.1f} 秒）' + ('' if r.returncode == 0 else ' ' + r.stderr[-600:]))
        r2 = stills(py, tl, '2.5', out / 'b2', env=env)
        t2 = time.time()
        if r.returncode == 0 and r2.returncode == 0:
            check(sha(out / 'b1' / 'still_002.500.png') == sha(out / 'b2' / 'still_002.500.png'), f'Blender：2 回目はためた絵で同じ（{t2 - t1:.1f} 秒）')
        keys = [p for p in (d / 'work' / '3d' / 'blender3d1').iterdir() if p.is_dir()] if (d / 'work' / '3d' / 'blender3d1').exists() else []
        check(len(keys) == 1 and (keys[0] / '000015.png').exists(), 'Blender：作品の work/3d/<クリップ>/<鍵>/ にためた（コマ 15）')
        # プレビュー（描画サーバーの JPEG と同じ：eng.preview）：本番の絵がためてあるコマはそれ、無いコマは下描き
        code = ("import sys;sys.path.insert(0,r'%s');from mittler.engine import Engine;import hashlib;e=Engine(r'%s');e.preview=True;"
                "a=e.render(2.5);b=e.render(2.8);print(hashlib.sha256(a.tobytes()).hexdigest())") % (ROOT / 'pyengine', tl)
        r = run([py, '-X', 'utf8', '-c', code], env=env)
        kd = sorted(p.name for p in (d / 'work' / '3d' / 'blender3d1').iterdir() if p.is_dir())
        check(r.returncode == 0 and len(kd) == 2, f'Blender：プレビューは、ためていないコマを下描きの別のフォルダに描く（{kd}）' + ('' if r.returncode == 0 else r.stderr[-400:]))
        # 書き出し：区間の前にまとめて描く・並列 1 と 3 が同じ・静止画と同じ
        vids = {}
        for j in (1, 3):
            r = run([py, '-X', 'utf8', '-B', '-m', 'mittler', 'video', tl, out / f'b_j{j}.mp4', '--jobs', str(j), '--from', '2', '--to', '3'], env=env)
            ph = 'PHASE blender' in r.stdout
            check(r.returncode == 0 and (j == 3 or ph), f'Blender：書き出し（並列 {j}）{"・区間の前にまとめて描いた" if ph else "（もうためてあった）"}' + ('' if r.returncode == 0 else ' ' + (r.stderr + r.stdout)[-600:]))
            vids[j] = framemd5(out / f'b_j{j}.mp4') if r.returncode == 0 else []
        check(vids[1] and vids[1] == vids[3], f'Blender：並列 1 と 3 の書き出しのコマが同じ（{len(vids[1])} コマ）')
        if vids[1]:
            check(png_md5(out / 'b1' / 'still_002.500.png') == vids[1][15], 'Blender：静止画（2.5 秒）と書き出しの同じコマが同じ')
        # 止める：ためた絵を消して、サンプルの多い書き出しを途中で .cancel
        shutil.rmtree(d / 'work' / '3d')
        tj = json.loads(tl.read_text(encoding='utf-8'))
        tj['tracks'][0]['clips'][0]['params']['samples'] = 256
        tl.write_text(json.dumps(tj, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        before = toolhelp_names().count('blender.exe')
        e = dict(os.environ, MITTLER_LANG='ja', PYTHONUNBUFFERED='1', MITTLER_BLENDER=a.blender)
        mp4 = out / 'b_cancel.mp4'
        pr = subprocess.Popen([py, '-X', 'utf8', '-B', '-m', 'mittler', 'video', str(tl), str(mp4), '--jobs', '2', '--from', '2', '--to', '3'], cwd=str(ROOT / 'pyengine'),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', env=e)
        seen = False
        t0 = time.time()
        for ln in pr.stdout:
            if ln.startswith('PHASE blender') and not seen:
                seen = True
                time.sleep(1.5)
                Path(str(mp4) + '.cancel').write_text('1')
            if time.time() - t0 > 300:
                break
        pr.wait(timeout=120)
        time.sleep(1.0)
        after = toolhelp_names().count('blender.exe')
        check(seen and pr.returncode == 3 and after <= before, f'Blender：書き出しを止めると Blender も止まる（終わりの番号 {pr.returncode}・blender.exe {before}→{after}）')
        tmp = [p for p in (d / 'work' / '3d').rglob('_tmp_*')] if (d / 'work' / '3d').exists() else []
        check(not tmp, 'Blender：止めたあとに描きかけのファイルが残らない')

    print(json.dumps({'ok': not fails, 'fails': fails, 'work': str(work)}, ensure_ascii=False))
    if not a.keep and not a.work:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
