"""古い名前の互換：tools/cc_api.py（2026-11-12 に tools/mittler_api.py に改名した）。
今までの作品の CLAUDE.md・手順・古いスキルは `python <このリポジトリ>/tools/cc_api.py <作品> …` と書いてあるので、同じ場所に受け口を残してある。
中身は無い：隣の mittler_api.py をそのまま動かすだけ（引数・標準出力・終わりの番号も同じ）。新しく書くものは mittler_api.py を使う。
互換を外すときは、このファイルを消す。
"""
import runpy
from pathlib import Path

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parent / 'mittler_api.py'), run_name='__main__')
