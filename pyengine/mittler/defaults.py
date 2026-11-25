"""作者の PC の既定値（server/defaults.author.json）を Python の側で読む。無ければ空（一般の既定＝PATH・設定で指定）。
server/defaults.js と同じファイルを読む（1 か所）。公開用の書き出し（tools/export_public.py）にはこのファイルが入らない。標準ライブラリだけ。"""
import json
from pathlib import Path

AUTHOR_FILE = Path(__file__).resolve().parents[2] / 'server' / 'defaults.author.json'


def author(key, default=None):
    """defaults.author.json の key の値（無い・読めないときは default）"""
    try:
        v = json.loads(AUTHOR_FILE.read_text(encoding='utf-8')).get(key)
    except (OSError, ValueError):
        v = None
    return default if v in (None, '', [], {}) else v
