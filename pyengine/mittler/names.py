"""Mittler の名前と、古い名前（claude-cut）の互換（Python 側の1か所。JS 側は server/names.js。標準ライブラリだけ・numpy などは読まない）。
2026-11-12 に claude-cut を Mittler に改名した。**新しい名前が正**で、古い名前は「読める」だけ残してある（今までの作品と PC の設定を直さずに動かすため）。
古い名前を読むところは、ここと server/names.js、古い名前の入口（pyengine/ccpy/・tools/cc.cmd・tools/cc_state.py・tools/cc_api.py）にまとめてある。
互換を外すときは、この「古い名前の互換」の印が付いたところを消す。

| もの | 新しい名前 | 古い名前（読むだけ） |
|---|---|---|
| 環境変数 | MITTLER_<名前> | CC_<名前>（env()。両方あれば新しいほう） |
| 作品の中の状態フォルダ | .mittler/ | .claude-cut/（state_dir_name()。古い作品はそのまま .claude-cut/ を使う） |
| HTTP のトークンのヘッダ | X-Mittler-Token | X-CC-Token（サーバーが両方受ける。server/names.js） |
| Python のパッケージ | mittler | ccpy（pyengine/ccpy/ が mittler に読み替える） |
"""
import hashlib
import os
import re
from pathlib import Path

ENV_PREFIX = 'MITTLER_'
OLD_ENV_PREFIX = 'CC_'            # 古い名前の互換
STATE_DIR = '.mittler'
OLD_STATE_DIR = '.claude-cut'     # 古い名前の互換
TOKEN_HEADER = 'X-Mittler-Token'  # サーバーは古い X-CC-Token も受ける（server/names.js）


def env(name, default=None):
    """環境変数 MITTLER_<name>。無ければ（空も）古い名前 CC_<name>（古い名前の互換）。どちらも無ければ default"""
    return os.environ.get(ENV_PREFIX + name) or os.environ.get(OLD_ENV_PREFIX + name) or default


def state_dir_name(project):
    """作品の状態フォルダの名前（server.json・state.json・current_frame.jpg・annotations・サムネなどの置き場）。server/names.js の stateDirName と同じ決まり：
    .mittler/ があればそれ。無くて .claude-cut/ があれば .claude-cut（古い名前の互換：今までの作品のフック・CLAUDE.md がそこを読む）。
    どちらも無いとき（clone したばかりなど）は、作品の .gitignore に .claude-cut だけが書いてあれば .claude-cut（古い作品。.mittler/ を作ると git に見えてしまう）、ほかは .mittler"""
    p = Path(project)
    if (p / STATE_DIR).is_dir():
        return STATE_DIR
    if (p / OLD_STATE_DIR).is_dir():
        return OLD_STATE_DIR
    try:
        lines = {ln.strip().strip('/') for ln in (p / '.gitignore').read_text(encoding='utf-8', errors='replace').splitlines()}
    except OSError:
        lines = set()
    return OLD_STATE_DIR if OLD_STATE_DIR in lines and STATE_DIR not in lines else STATE_DIR


def state_dir(project):
    return Path(project) / state_dir_name(project)


def cache_root(project):
    """作り直せる大きなもの（コマの絵 cache/frames・マスターの中間 master・Blender の 3D の絵 3d）の置き場の根（2026-11-22）。server/names.js の cacheRoot と同じ決まり：
    環境変数 MITTLER_CACHE_DIR（PC の設定 mittler.cache.dir。サーバーが子のプロセスに渡す）が無ければ作品の work/。
    あれば <そこ>/<作品のフォルダの名前>-<作品の場所の印 8 字>/（作品を Google ドライブなどで同期していても、ためた絵を送らないため）。
    初めて使うとき、そこに _project.txt（どの作品のものか）を書く"""
    p = Path(project)
    base = env('CACHE_DIR')
    if not base:
        return p / 'work'
    full = os.path.abspath(str(p))
    key = full.replace('\\', '/').rstrip('/').lower()
    name = re.sub(r'[^A-Za-z0-9_.-]', '_', os.path.basename(full.rstrip('\\/'))) or 'project'
    root = Path(base) / f"{name}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:8]}"
    mark = root / '_project.txt'
    if not mark.exists():
        try:
            root.mkdir(parents=True, exist_ok=True)
            mark.write_text(full + '\n', encoding='utf-8')
        except OSError:
            pass
    return root
