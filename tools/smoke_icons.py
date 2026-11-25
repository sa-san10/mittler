"""画面のアイコン（絵文字をやめて、モノグラムのアイコンで統一する）の確かめ。ファイルを読むだけ（ブラウザ・サーバーを使わない）。
  python -X utf8 tools/smoke_icons.py
アイコンは Lucide（ISC。editor/icons/*.svg をそのまま写したもの・editor/icons/LICENSE-lucide.txt）。出し方は editor/ui.js（MITTLER_ICON・辞書の {icon:名前}）と editor.css（.ic の一覧）。
確かめること：
  (a) 置き場   editor/icons/ の SVG は Lucide の配布物のまま（頭の @license の行・24 の枠・線 2・currentColor）・LICENSE-lucide.txt がある・THIRD_PARTY_NOTICES.md に Lucide
  (b) 名前     コード・辞書・解析の種類の名前（analyze_kinds.json）が使うアイコンの名前は、どれも SVG があり、editor.css の一覧にある。一覧と SVG は 1 対 1
  (c) 絵文字   画面に出る文（辞書・index.html・package.nls*.json・解析の種類の名前・エフェクトの名前）と、編集画面・サーバー・拡張のコード（コメントを除く）に絵文字が無い
               （エフェクトが絵として描く字は対象外：エフェクトのコードは名前（META の label）だけ見る）
  (d) 印       文字しか出せない所の文（ツールチップ＝鍵が .tip で終わるもの・押せない理由 why.*・トラックを足すボタンのツールチップ addtr.*）にアイコンの印 {icon:…} が無い
画面に絵文字・印が残っていないか（DOM）は tools/smoke_i18n.py の (g)（英語と日本語の主な場面）、上のバーのアイコンの大きさ・SVG が読めるかは tools/smoke_ui.py。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / 'editor' / 'icons'
fails = []


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


# 絵文字（Unicode の Extended_Pictographic のおもなところと U+FE0F）。tools/smoke_i18n.py の EMO と同じ並び
EMO_CLASS = (r'©®‼⁉™ℹ↔-↙↩↪⌚⌛⌨⏏⏩-⏳⏸-⏺Ⓜ▪▫▶◀'
             r'◻-◾☀-➿⤴⤵⬅-⬇⬛⬜⭐⭕〰〽㊗㊙️')
EMO = re.compile('[' + EMO_CLASS + '\U0001F000-\U0001FAFF]')
MARK = re.compile(r'\{icon:([a-z0-9-]+)\}')

# ---- (a) 置き場 ----
svgs = sorted(p.stem for p in ICONS.glob('*.svg'))
bad = []
for n in svgs:
    t = (ICONS / f'{n}.svg').read_text(encoding='utf-8')
    if not (t.startswith('<!-- @license lucide-static v') and 'viewBox="0 0 24 24"' in t and 'stroke-width="2"' in t and 'stroke="currentColor"' in t and f'lucide-{n}' in t):
        bad.append(n)
lic = ICONS / 'LICENSE-lucide.txt'
lic_ok = lic.exists() and lic.read_text(encoding='utf-8').startswith('ISC License') and 'Lucide Icons and Contributors' in lic.read_text(encoding='utf-8')
notice = (ROOT / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
check(svgs and not bad and lic_ok and 'Lucide' in notice and 'editor/icons/LICENSE-lucide.txt' in notice,
      f'(a) 置き場：editor/icons/ の SVG {len(svgs)} 個が Lucide のまま・LICENSE-lucide.txt（ISC）・THIRD_PARTY_NOTICES.md に Lucide' + (f' 違う：{bad}' if bad else ''))

# ---- (b) 名前 ----
css = (ROOT / 'editor' / 'editor.css').read_text(encoding='utf-8')
listed = re.findall(r'\.ic\[data-ic="([a-z0-9-]+)"\]\{--ic-src:url\(icons/([a-z0-9-]+)\.svg\)\}', css)
same_name = [a for a, b in listed if a != b]
listed = {a for a, _ in listed}
used = {}  # 名前 → 使っている場所


def use(name, where):
    used.setdefault(name, set()).add(where)


DICTS = [ROOT / 'editor' / 'i18n' / 'en.json', ROOT / 'editor' / 'i18n' / 'ja.json', ROOT / 'pyengine' / 'mittler' / 'analyze_kinds.json']
for f in DICTS:
    for n in MARK.findall(f.read_text(encoding='utf-8')):
        use(n, f.name)
for f in sorted((ROOT / 'editor').glob('*.js')) + [ROOT / 'editor' / 'index.html']:
    src = f.read_text(encoding='utf-8')
    for n in MARK.findall(src) + re.findall(r"MITTLER_ICON?\('([a-z0-9-]+)'", src) + re.findall(r'data-ic="([a-z0-9-]+)"', src):
        use(n, f.name)
    # 名前を表に持っているもの（トラックの種類・参照の種類・書き込みの道具・大きさ・トラックを足すボタン）：SVG の名前と同じ文字はアイコンの名前とみなす
    for n in re.findall(r"'([a-z][a-z0-9-]+)'", src):
        if n in svgs:
            use(n, f.name)
# editor.css が一覧の外で直に使う型の絵（知らせの種類の印 .tmark など）
for n in re.findall(r'url\(icons/([a-z0-9-]+)\.svg\)', re.sub(r'\.ic\[data-ic="[a-z0-9-]+"\]\{--ic-src:url\(icons/[a-z0-9-]+\.svg\)\}', '', css)):
    use(n, 'editor.css')
missing = sorted(n for n in used if n not in svgs or n not in listed)
orphan = sorted(set(svgs) - listed) + sorted(listed - set(svgs))
unused = sorted(set(svgs) - set(used))
check(not missing and not orphan and not same_name and not unused,
      f'(b) 名前：使っているアイコン {len(used)} 種に SVG と editor.css の一覧があり、一覧と SVG は 1 対 1・使っていない SVG が無い'
      + (f' 無い：{[(n, sorted(used[n])) for n in missing]}' if missing else '') + (f' 片方だけ：{orphan}' if orphan else '')
      + (f' 名前違い：{same_name}' if same_name else '') + (f' 使っていない：{unused}' if unused else ''))

# ---- (c) 絵文字 ----
hits = []
for f in [ROOT / 'editor' / 'i18n' / 'en.json', ROOT / 'editor' / 'i18n' / 'ja.json', ROOT / 'package.nls.json', ROOT / 'package.nls.ja.json', ROOT / 'package.json']:
    for i, ln in enumerate(f.read_text(encoding='utf-8').split('\n'), 1):
        if EMO.search(ln):
            hits.append(f'{f.relative_to(ROOT).as_posix()}:{i}')
ak = json.loads((ROOT / 'pyengine' / 'mittler' / 'analyze_kinds.json').read_text(encoding='utf-8'))
for k in ('labels', 'labels_en'):
    for kind, v in ak.get(k, {}).items():
        if EMO.search(v):
            hits.append(f'analyze_kinds.json {k}.{kind}')
# エフェクトの名前（右の欄・アセット窓に出る）
for f in sorted((ROOT / 'effects_lib').rglob('*.py')):
    m = re.search(r"META\s*=\s*\{(.*?)\n\S", f.read_text(encoding='utf-8'), re.S)
    if m:
        for lab in re.findall(r"'label(?:_en)?'\s*:\s*'([^']*)'", m.group(1)):
            if EMO.search(lab):
                hits.append(f'{f.relative_to(ROOT).as_posix()} META label {lab}')


def code_lines(f):
    """コメントを除いた行（行まるごとのコメント・/* */・行の終わりの // コメント）"""
    keep_lines = lambda m: '\n' * m.group(0).count('\n')  # noqa: E731（行の番号がずれないように、改行だけ残す）
    t = re.sub(r'/\*.*?\*/', keep_lines, f.read_text(encoding='utf-8'), flags=re.S)
    t = re.sub(r'<!--.*?-->', keep_lines, t, flags=re.S)
    for i, ln in enumerate(t.split('\n'), 1):
        s = ln.strip()
        if s.startswith('//'):
            continue
        yield i, re.split(r'\s//\s', ln)[0]


CODE = [*sorted((ROOT / 'editor').glob('*.js')), ROOT / 'editor' / 'index.html', ROOT / 'editor' / 'editor.css', *sorted((ROOT / 'server').glob('*.js')),
        ROOT / 'extension.js', ROOT / 'extension_setup.js', ROOT / 'tools' / 'new_project.js']
for f in CODE:
    for i, s in code_lines(f):
        if EMO.search(s):
            hits.append(f'{f.relative_to(ROOT).as_posix()}:{i}')
check(not hits, f'(c) 絵文字：画面の文（辞書・package.nls・解析とエフェクトの名前）と、編集画面・サーバー・拡張のコード（コメントを除く）に絵文字が無い' + (f' ある：{hits[:20]}' if hits else ''))

# ---- (d) 文字しか出せない所の文にアイコンの印が無い ----
bad = []
for f in (ROOT / 'editor' / 'i18n' / 'en.json', ROOT / 'editor' / 'i18n' / 'ja.json'):
    for k, v in json.loads(f.read_text(encoding='utf-8')).items():
        if (k.endswith('.tip') or '.tip' in k.split('.')[-2:-1] or k.startswith(('why.', 'addtr.', 'srv.', 'ext.', 'cmd.'))) and MARK.search(json.dumps(v, ensure_ascii=False)):
            bad.append(f'{f.name} {k}')
check(not bad, '(d) 印：ツールチップ・押せない理由・サーバーと拡張の文に、アイコンの印 {icon:…} が無い（文字しか出せない所は言葉だけ）' + (f' ある：{bad[:20]}' if bad else ''))

print('ALL OK' if not fails else f'FAIL {len(fails)}')
sys.exit(1 if fails else 0)
