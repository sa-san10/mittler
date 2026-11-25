"""同じ計算・同じ一覧が、言語をまたいでも同じかを確かめる（ブラウザもサーバーも要らない）。描画の python（numpy）で流す。
  <描画の python> -X utf8 tools/smoke_same.py [--node <node の場所>]
確かめること：
- 時間の付け替え warp：pyengine/mittler/warp.py の Points と editor/calc.js の warpMap（編集画面とサーバーが使う）が、決まった種の乱数の点で同じ値（1e-9 まで）
- 色の卓 grade：effects_lib/common/grade.py の apply と editor/calc.js の gradePixel（編集画面のおおよその色）が同じ式（0〜255 で 0.01 まで。Python は float32）。
  クリップの色（映像・画像・🎬 のクリップの grade）でエンジンが読む式も同じファイル（engine._grade_mod）
- 解析の種類：pyengine/mittler/analyze_kinds.json（1か所）の種類と名前が analyze.py の KINDS と同じ、server.js・editor/analyze.js に一覧を書き直していない
- 生成のエンジン：tools/engines.json（1か所）に編集画面（editor/plan.js）の動画化の選択肢と既定がある、アダプタが build・submit・poll・SUBMIT_ERROR を持つ
- ドラフト品質（ctx.draft）の形：Engine(tl) の既定で eng.draft is False、Engine(tl, draft=True) で Ctx(...).draft is True
- マスター書き出し（ctx.scale）の形：Engine(tl) の既定で scale 1（int）・大きさと fps はタイムラインのまま、Engine(tl, scale=2, fps=60, src_map=…) で 2 倍・60fps・差し替え、
  差し替え表の '@clips'（クリップだけの差し替え）
- 🏆 アップスケールの名前：pyengine/mittler/master.py の UPSCALE_KINDS と server/defaults.js の masterUpscale が同じ。
  アップスケールなし（none）の名前：master.py の UPSCALE_NONE と defaults.js の masterNoUpscale・editor/export.js の控え（サーバーが返さないとき）が同じ
node は PATH の node、無ければ（Windows）tools\\mittler.cmd node（VS Code に入っている Node）。
"""
import ast
import importlib.util
import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'pyengine'))
from mittler.warp import Points  # noqa: E402

fails = []


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


def node_cmd():
    if '--node' in sys.argv:
        return [sys.argv[sys.argv.index('--node') + 1]]
    n = shutil.which('node')
    if n:
        return [n]
    launcher = ROOT / 'tools' / 'mittler.cmd'
    if sys.platform == 'win32' and launcher.exists():
        return ['cmd', '/c', str(launcher), 'node']
    sys.exit('node が見つからない（--node で場所を渡す）')


rnd = random.Random(20261030)
# ---- 時間の付け替え ----
warp_cases = []
for i in range(40):
    n = 1 + i % 7
    ts = sorted(rnd.uniform(0, 10) for _ in range(n))
    if len(set(ts)) < n:
        continue
    pts = [[t, rnd.uniform(-2, 20)] for t in ts]
    rnd.shuffle(pts)
    sm = 0 if i % 3 == 0 else round(rnd.uniform(0.01, 0.6), 3)
    q = [round(rnd.uniform(-3, 13), 4) for _ in range(25)] + [p[0] for p in pts]
    warp_cases.append({'w': {'points': pts, 'smooth': sm}, 'ts': q})
# ---- 色の卓 ----
spec = importlib.util.spec_from_file_location('grade', ROOT / 'effects_lib' / 'common' / 'grade.py')
grade = importlib.util.module_from_spec(spec); spec.loader.exec_module(grade)
grade_cases = []
for i in range(12):
    p = {k: round(rnd.uniform(0.5, 1.5), 2) for k in 'bcvs' if rnd.random() < 0.8}
    px = [[rnd.randrange(256) / 255 for _ in range(3)] for _ in range(64)] + [[0, 0, 0], [1, 1, 1], [1, 0, 0], [0.5, 0.5, 0.5]]
    grade_cases.append({'px': px, 'p': p})

r = subprocess.run(node_cmd() + [str(ROOT / 'tools' / 'calc_cli.js')], input=json.dumps({'warp': warp_cases, 'grade': grade_cases}).encode('utf-8'),
                   capture_output=True, timeout=120)
if r.returncode:
    sys.exit('calc_cli.js が失敗：' + r.stderr.decode('utf-8', 'replace')[-800:])
js = json.loads(r.stdout.decode('utf-8'))
dw = max(abs(Points(c['w']['points'], c['w']['smooth'])(t) - y) for c, ys in zip(warp_cases, js['warp']) for t, y in zip(c['ts'], ys))
check(dw < 1e-9, f'warp：warp.py の Points と calc.js の warpMap（{len(warp_cases)} 通り×{sum(len(c["ts"]) for c in warp_cases) // len(warp_cases)} 時刻、いちばん大きい差 {dw:.2e}）')
dg = 0.0
for c, out in zip(grade_cases, js['grade']):
    f = (np.asarray(c['px'], np.float64)[None] * 255).astype(np.float32)  # 1×N の絵（0〜255）
    py = grade.apply(None, f, {'params': c['p']})[0]
    jj = np.clip(np.asarray(out, np.float64), 0, 1) * 255
    dg = max(dg, float(np.abs(py - jj).max()))
check(dg < 0.01, f'grade：grade.py の apply と calc.js の gradePixel（{len(grade_cases)} 通り×68 画素、0〜255 でいちばん大きい差 {dg:.2e}）')
# クリップの色（映像・画像・🎬 のクリップの grade、2026-10-31）：エンジンが読む式も同じ effects_lib/common/grade.py
from mittler.engine import _grade_mod  # noqa: E402
check(Path(_grade_mod().__file__).resolve() == (ROOT / 'effects_lib' / 'common' / 'grade.py').resolve(),
      f'クリップの色：エンジン（engine._grade_mod）が読む式は effects_lib/common/grade.py（{_grade_mod().__file__}）')

# ---- 解析の種類 ----
ak = json.loads((ROOT / 'pyengine' / 'mittler' / 'analyze_kinds.json').read_text(encoding='utf-8'))
kinds_json = {k for v in ak['by_type'].values() for k in v}
tree = ast.parse((ROOT / 'pyengine' / 'mittler' / 'analyze.py').read_text(encoding='utf-8'))
kinds_py = next({k.value for k in n.value.keys} for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == 'KINDS' for t in n.targets))
check(kinds_json == kinds_py == set(ak['labels']), f'解析の種類：analyze_kinds.json {sorted(kinds_json)}・名前 {sorted(ak["labels"])}・analyze.py の KINDS {sorted(kinds_py)}')
lists = {f: re.findall(r"\[\s*'beats'\s*,\s*'transcribe'|'pose'\s*,\s*'mask'\s*,\s*'cutout'", (ROOT / f).read_text(encoding='utf-8')) for f in ('server/server.js', 'editor/analyze.js')}
check(not any(lists.values()), f'server.js・editor/analyze.js に解析の種類の一覧を書き直していない（{lists}）')

# ---- 生成のエンジン ----
eng = json.loads((ROOT / 'tools' / 'engines.json').read_text(encoding='utf-8'))
ui = re.findall(r"\['(h3-[\w-]+|[\w-]+)', '", re.search(r'const ENGINES = (\[.*?\]\]);', (ROOT / 'editor' / 'plan.js').read_text(encoding='utf-8')).group(1))
ok_ui = bool(ui) and all(eng['engines'].get(e, {}).get('kind') == 'video' for e in ui)
ok_def = all(eng['engines'].get(eng['default'][k], {}).get('kind') == k for k in ('video', 'image'))
ok_ad = all((ROOT / 'tools' / (v['adapter'] + '.py')).is_file() for v in eng['engines'].values())
check(ok_ui and ok_def and ok_ad, f'生成のエンジン：編集画面の動画化の選択肢 {ui} が tools/engines.json にある・既定 {eng["default"]}・アダプタのファイルがある')
for name in sorted({v['adapter'] for v in eng['engines'].values()}):
    src = ast.parse((ROOT / 'tools' / (name + '.py')).read_text(encoding='utf-8'))
    fns = {n.name for n in src.body if isinstance(n, ast.FunctionDef)}
    has = {n.targets[0].id for n in src.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    check({'build', 'submit', 'poll'} <= fns and 'SUBMIT_ERROR' in has, f'アダプタ {name}.py の形（build・submit・poll・SUBMIT_ERROR）')

# ---- ドラフト品質（ctx.draft、機能追加案01）：既定は False、Engine(tl, draft=True) なら Ctx も True ----
import tempfile  # noqa: E402
from mittler.engine import Ctx, Engine  # noqa: E402
with tempfile.TemporaryDirectory(prefix='mittler_same_') as td:
    tlf = Path(td) / 'same.cut.json'
    tlf.write_text(json.dumps({'width': 64, 'height': 36, 'fps': 24, 'duration': 1, 'tracks': []}), encoding='utf-8')
    e0, e1 = Engine(tlf), Engine(tlf, draft=True)
    check(e0.draft is False and Ctx(e0, 0.5, 0.5, '').draft is False and e1.draft is True and Ctx(e1, 0.5, 0.5, '').draft is True,
          'ドラフト品質：Engine(tl) の既定で eng.draft is False・Ctx も False、Engine(tl, draft=True) で Ctx(...).draft is True')
    e1.load()
    check(e1.draft is True, 'ドラフト品質：読み直し（load）でも eng.draft は変わらない')
    # ---- マスター書き出し（ctx.scale・fps の上書き・素材の差し替え、機能追加案03 v2）----
    c0 = Ctx(e0, 0.5, 0.5, '')
    check(e0.scale == 1 and type(e0.scale) is int and c0.scale == 1 and (e0.W, e0.H, e0.fps) == (64, 36, 24) and (e0.W0, e0.H0, e0.tl_fps) == (64, 36, 24)
          and e0.src_path('a/b.mp4') == e0.root / 'a/b.mp4',
          'マスター：Engine(tl) の既定で scale 1（int）・Ctx も 1・W×H と fps はタイムラインのまま・素材は root から')
    e2 = Engine(tlf, scale=2, fps=60, src_map={'a/b.mp4': str(Path(td) / 'x.mkv')})
    c2 = Ctx(e2, 0.5, 0.5, '')
    check(e2.scale == 2 and type(e2.scale) is int and c2.scale == 2 and (c2.W, c2.H, c2.fps) == (128, 72, 60) and (e2.W0, e2.H0, e2.tl_fps) == (64, 36, 24)
          and c2.fi == 30 and e2.src_path('a/b.mp4') == Path(td) / 'x.mkv' and e2.src_path('c.mp4') == e2.root / 'c.mp4',
          'マスター：Engine(tl, scale=2, fps=60, src_map=…) でキャンバス 128×72・Ctx.scale 2・60fps のコマ番号・素材の差し替え')
    e2.load()
    check((e2.W, e2.H, e2.fps, e2.scale) == (128, 72, 60, 2), 'マスター：読み直し（load）でも倍率・fps は同じ')
    # クリップごとの差し替え（'@clips'。アップスケールのモデルをクリップで変えたもの、2026-10-31）
    e3 = Engine(tlf, scale=2, fps=60, src_map={'a/b.mp4': str(Path(td) / 'x.mkv'), '@clips': {'v2': {'a/b.mp4': str(Path(td) / 'y.mkv')}}})
    check(e3.src_path('a/b.mp4') == Path(td) / 'x.mkv' and e3.src_path('a/b.mp4', 'v1') == Path(td) / 'x.mkv' and e3.src_path('a/b.mp4', 'v2') == Path(td) / 'y.mkv'
          and e3.src_path('c.mp4', 'v2') == e3.root / 'c.mp4' and '@clips' not in e3.src_map and e0.clip_src_map == {},
          "マスター：差し替え表の '@clips' はそのクリップだけ（ほかのクリップ・ほかの素材は今までどおり）")
    e0.close()
    e1.close()
    e2.close()
    e3.close()

# ---- アップスケールの名前（🏆、2026-10-31）：master.py の UPSCALE_KINDS と server/defaults.js の masterUpscale が同じ・どのモデルも倍率の表にある ----
from mittler import master as _master  # noqa: E402
js = (ROOT / 'server' / 'defaults.js').read_text(encoding='utf-8')
m_js = re.search(r'masterUpscale:\s*\{([^}]*)\}', js)
kinds_js = dict(re.findall(r"(\w+):\s*'([^']+)'", m_js.group(1))) if m_js else {}
check(kinds_js == _master.UPSCALE_KINDS and all(m in _master.ESRGAN_MODELS for m in _master.UPSCALE_KINDS.values())
      and _master.DEFAULTS['esrgan_model'] == _master.UPSCALE_KINDS['anime'] and "esrganModel: 'realesr-animevideov3'" in js,
      f'アップスケールの名前：master.py の UPSCALE_KINDS {_master.UPSCALE_KINDS} と defaults.js の masterUpscale {kinds_js} が同じ・倍率の表にある・既定はアニメ')
m_none = re.search(r"masterNoUpscale:\s*'([^']+)'", js)
none_js = m_none.group(1) if m_none else None
none_ui = re.findall(r"mi\.noUpscale\) \|\| '(\w+)'", (ROOT / 'editor' / 'export.js').read_text(encoding='utf-8'))  # const NONE = (mi && mi.noUpscale) || 'none'（2026-10-31 夜の窓の作り直しから）
check(none_js == _master.UPSCALE_NONE and _master.UPSCALE_NONE not in _master.UPSCALE_KINDS and none_ui == [_master.UPSCALE_NONE],
      f'アップスケールなしの名前：master.py の UPSCALE_NONE「{_master.UPSCALE_NONE}」と defaults.js の masterNoUpscale「{none_js}」・編集画面の控え {none_ui} が同じ・モデルの名前と重ならない')

print('smoke_same:', 'OK' if not fails else f'FAIL {len(fails)}')
sys.exit(1 if fails else 0)
