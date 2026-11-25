"""古い名前の互換：フック tools/cc_state.py（2026-11-12 に tools/mittler_state.py に改名した）。
今までの作品の .claude/settings.json のフックは `python "<このリポジトリ>/tools/cc_state.py"` を名指ししているので、同じ場所に受け口を残してある。
中身は無い：隣の mittler_state.py をそのまま動かすだけ（引数・標準出力・終わりの番号も同じ）。新しい作品のフックは mittler_state.py を呼ぶ
（古いフックを書き直すなら `python tools/fix_hooks.py <作品>`）。互換を外すときは、このファイルを消す。
"""
import runpy
from pathlib import Path

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parent / 'mittler_state.py'), run_name='__main__')
