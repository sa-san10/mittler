"""Mittler：フックの中継（作品の状態フォルダ .mittler/ に、拡張が作品を開くたびに書く。直さない。標準ライブラリだけ）。
作品の .claude/settings.json のフック（UserPromptSubmit）から呼ばれ、隣の env.json に書いてある Mittler の場所の tools/mittler_state.py を
この作品について動かす（話しかけるたびに、編集画面の今を Claude にそえる）。作品に Mittler の絶対パスを書かないための中継。
- env.json の場所に Mittler が無い（拡張を更新して、まだ作品を開いていない）ときは、入っている Mittler の拡張のうち新しいものを使う。
- 見つからない・失敗したときも、話しかけるのは止めない（終わりの番号はいつも 0）。
"""
import json
import re
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # Mittler の置き場（拡張のフォルダ）に __pycache__ を書かない
HERE = Path(__file__).resolve().parent
TARGET = ('tools', 'mittler_state.py')


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


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    md = mittler_dir()
    if not md:
        print(f'【Mittler】Mittler の場所が分からない（{HERE / "env.json"}）。編集画面でこの作品の *.cut.json を開くと書かれる。')
        return
    sys.argv = [str(md.joinpath(*TARGET)), str(HERE.parent)]
    try:
        runpy.run_path(sys.argv[0], run_name='__main__')
    except SystemExit:
        pass
    except Exception as e:  # noqa: BLE001（話しかけるのを止めない）
        print(f'【Mittler】編集画面の今を読めなかった：{type(e).__name__}: {e}')


if __name__ == '__main__':
    main()
    sys.exit(0)
