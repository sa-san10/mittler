"""Mittler：描画エンジンの中継（作品の状態フォルダ .mittler/ に、拡張が作品を開くたびに書く。直さない。標準ライブラリだけ）。
  python .mittler/engine.py stills <作品>.cut.json --at 5,12.5 --out work/stills     （どのフォルダからでも。引数は `python -m mittler` と同じ）
隣の env.json に書いてある「描く python」（この PC で編集画面が使っているもの）で、Mittler の pyengine の `python -X utf8 -B -m mittler …` を動かす。
ffmpeg のフォルダ（env.json の ffmpeg_dir）は PATH の頭に足す。終わりの番号はエンジンのもの。
env.json の場所に Mittler が無い（拡張を更新して、まだ作品を開いていない）ときは、入っている Mittler の拡張のうち新しいものを使う。
描く python が env.json に無い（編集画面でまだ一度も描いていない）ときは、サーバーと同じ順（Mittler の既定の場所（server/defaults.js。値は server/defaults.author.json。あれば）→ PATH の python）で
numpy・opencv・Pillow を読めるものを探す。
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
TARGET = ('pyengine', 'mittler', '__main__.py')


def env_json():
    try:
        return json.loads((HERE / 'env.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def mittler_dir(env):
    """Mittler の場所（TARGET があるもの）。env.json → 入っている拡張（新しい版から）。無ければ None"""
    cands = [Path(env['mittler_dir'])] if env.get('mittler_dir') else []
    ver = lambda p: tuple(int(x) for x in re.findall(r'\d+', p.name.rsplit('-', 1)[-1]))  # sa-san10.mittler-0.3.0 → (0, 3, 0)
    for base in (Path.home() / '.vscode' / 'extensions', Path.home() / '.vscode-server' / 'extensions'):
        try:
            cands += sorted((p for p in base.iterdir() if p.name.lower().startswith('sa-san10.mittler-')), key=ver, reverse=True)
        except OSError:
            pass
    return next((c for c in cands if c.joinpath(*TARGET).is_file()), None)


def find_python(md):
    """env.json に描く python が無いとき：既定の描く python（server/defaults.js の renderPython＝server/defaults.author.json の値。あれば）→
    PATH の python のうち、numpy・opencv・Pillow を読めるもの"""
    cands = []
    try:
        p = json.loads((md / 'server' / 'defaults.author.json').read_text(encoding='utf-8')).get('renderPython') or ''
        if p and Path(p).is_file():
            cands.append(p)
    except (OSError, ValueError):
        pass
    # PATH の python は場所に直してから（名前だけで起動すると、Windows は先にこの python 自身のフォルダを探すので、PATH の python と違うものになることがある）
    cands.append(shutil.which('python') or 'python')
    for py in cands:
        try:
            if subprocess.run([py, '-c', 'import numpy, cv2, PIL'], capture_output=True, timeout=120).returncode == 0:
                return py
        except (OSError, subprocess.SubprocessError):
            pass
    return 'python'


if __name__ == '__main__':
    env = env_json()
    md = mittler_dir(env)
    if not md:
        sys.exit(f'mittler engine: Mittler の場所が分からない（{HERE / "env.json"}）。編集画面でこの作品の *.cut.json を開くと書かれる')
    py = env.get('render_python') or find_python(md)
    e = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    e['PYTHONPATH'] = str(md / 'pyengine') + (os.pathsep + e['PYTHONPATH'] if e.get('PYTHONPATH') else '')
    if env.get('cache_dir') and not e.get('MITTLER_CACHE_DIR'):  # ためた絵の置き場（PC の設定 mittler.cache.dir。編集画面と同じ所を使う）
        e['MITTLER_CACHE_DIR'] = env['cache_dir']
    if env.get('ffmpeg_dir'):
        e['PATH'] = env['ffmpeg_dir'] + os.pathsep + e.get('PATH', '')
    try:
        sys.exit(subprocess.call([py, '-X', 'utf8', '-B', '-m', 'mittler'] + sys.argv[1:], env=e))
    except OSError as err:
        sys.exit(f'mittler engine: 描く python を起動できない（{py}：{err}）。VS Code のコマンド「Mittler: 初期設定」で確かめる')
