"""Mittler：編集画面に頼む道具の中継（作品の状態フォルダ .mittler/ に、拡張が作品を開くたびに書く。直さない。標準ライブラリだけ）。
  python .mittler/api.py . status        （作品のフォルダで。引数は Mittler の tools/mittler_api.py と同じ。使い方は AI 用ガイドの 7.53）
隣の env.json に書いてある Mittler の場所の tools/mittler_api.py を、そのまま動かす（作品に Mittler の絶対パスを書かないための中継）。
env.json の場所に Mittler が無い（拡張を更新して、まだ作品を開いていない）ときは、入っている Mittler の拡張のうち新しいものを使う。
"""
import json
import re
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # Mittler の置き場（拡張のフォルダ）に __pycache__ を書かない
HERE = Path(__file__).resolve().parent
TARGET = ('tools', 'mittler_api.py')


def mittler_dir():
    """Mittler の場所（TARGET があるもの）。env.json → 入っている拡張（新しい版から）。無ければ None"""
    cands = []
    try:
        d = json.loads((HERE / 'env.json').read_text(encoding='utf-8')).get('mittler_dir') or ''
        if d:
            cands.append(Path(d))
    except (OSError, ValueError):
        pass
    ver = lambda p: tuple(int(x) for x in re.findall(r'\d+', p.name.rsplit('-', 1)[-1]))  # sa-san10.mittler-0.3.0 → (0, 3, 0)
    for base in (Path.home() / '.vscode' / 'extensions', Path.home() / '.vscode-server' / 'extensions'):
        try:
            cands += sorted((p for p in base.iterdir() if p.name.lower().startswith('sa-san10.mittler-')), key=ver, reverse=True)
        except OSError:
            pass
    return next((c for c in cands if c.joinpath(*TARGET).is_file()), None)


if __name__ == '__main__':
    md = mittler_dir()
    if not md:
        sys.exit(f'mittler_api: Mittler の場所が分からない（{HERE / "env.json"}）。編集画面でこの作品の *.cut.json を開くと書かれる')
    sys.argv = [str(md.joinpath(*TARGET))] + sys.argv[1:]
    runpy.run_path(sys.argv[0], run_name='__main__')
