"""画面に出る文の言葉（英語・日本語）。辞書の正本は editor/i18n/en.json・ja.json（編集画面・サーバーと同じ 1 か所）。

  from mittler.i18n import t
  t('py.an.stems')                    … 今の言葉の文
  t('py.an.beats', tempo='120.0', n=8) … {名前} を埋める。値が {one, other} なら n が 1 のとき one（英語の単数・複数）

今の言葉は環境変数 MITTLER_LANG（編集画面のサーバーが子のプロセスに渡す。'en'・'ja'）。無ければ日本語（コマンドラインの道具の出力は日本語のまま）。
鍵が無ければ、もう片方の言葉 → 鍵そのもの。辞書が読めなければ（エンジンだけを写した PC など）鍵そのもの。
絵には使わない（描く絵は言葉で変わらない。ここは知らせ・理由の文だけ）。
"""
import json
import os
import re
from pathlib import Path

LANGS = ('en', 'ja')
_DIR = Path(__file__).resolve().parents[2] / 'editor' / 'i18n'
_D = None


def _load():
    global _D
    if _D is None:
        _D = {}
        for l in LANGS:
            try:
                _D[l] = json.loads((_DIR / f'{l}.json').read_text(encoding='utf-8'))
            except Exception:
                _D[l] = {}
    return _D


def lang():
    v = (os.environ.get('MITTLER_LANG') or '').strip().lower()
    return v if v in LANGS else 'ja'


def pick(v, en=None):
    """エフェクトの説明・名前：日本語の値と英語の値（label_en・doc_en、または {'ja': …, 'en': …}）から、今の言葉のものを選ぶ"""
    if isinstance(v, dict) and ('ja' in v or 'en' in v):
        en, v = v.get('en'), v.get('ja')
    return en if (lang() == 'en' and en) else v


def t(key, _lang=None, **kw):
    d = _load(); l = _lang if _lang in LANGS else lang(); o = 'en' if l == 'ja' else 'ja'
    v = d[l].get(key, d[o].get(key, key))
    if isinstance(v, dict):
        v = v.get('one') if (str(kw.get('n')) == '1' and v.get('one') is not None) else v.get('other', '')
    v = re.sub(r'\{icon:[a-z0-9-]+\} ?', '', str(v))  # 辞書のアイコンの印（編集画面がアイコンにする）は、エンジンの文では外す
    return re.sub(r'\{(\w+)\}', lambda m: str(kw[m.group(1)]) if m.group(1) in kw else m.group(0), v)  # None も 'None' と出す（{code} のまま出さない）
