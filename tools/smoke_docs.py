"""公開する文書の確かめ（文書どうし・文書とコードの食い違いのうち、機械で見られるもの）。標準ライブラリだけ。サーバーもブラウザも要らない。
  python -X utf8 tools/smoke_docs.py [-v]      （-v：見つけた行を全部出す）
対象：追跡している *.md のうち、公開用のリポジトリに入るもの（`_非公開/` と `docs/作業記録/` の外）。
確かめること：
  LINK     Markdown のリンク [..](相対パス) の先が実在する
  PATH     バッククォートの中に出てくるこのリポジトリのパス（docs/・tools/・server/・editor/・pyengine/・setup/・skills/・templates/・effects_lib/・importers/ と根のファイル）が実在する
  SETTING  設定・コマンドの名前 mittler.*（古い名前 claudeCut.*）が package.json にある
  ENV      環境変数 MITTLER_* がコードにある
  API      /api/… がサーバーにある
  FLAG     道具の引数（--…）が、その道具のコードにある（mittler_setup.py・new_project.js・install_vscode.py・mittler.cmd serve・python -m mittler）
  SECTION  「インストールガイドの 12」「AI 用ガイドの 7」のような章の番号の先に、その見出しがある
  SMOKE    文書に出てくる smoke_*.py が tools/ にあり、tools/ の smoke_*.py は AI 用ガイドの 7 に全部出てくる
  OLDNAME  古い名前（claude-cut・ccpy・claudeCut・cc.cmd・CC_*・.claude-cut…）が、互換の説明（前の名前・古い名前・改名・互換…と書いてある行）の外に残っていない
  PERSONAL 作者の PC の言葉（ドライブ文字で始まるパスと、_非公開/公開の検査.json の作者の環境の言葉）が、入口の文書に残っていない。
           コードの既定値（server/defaults.js などに実際に書いてある、ドライブ文字で始まる値）を説明している行は数えない
入口でない文書（受け渡しの契約）の OLDNAME・PERSONAL は、落とさずに数だけ出す（INFO）。`_非公開/` を指している行も INFO（公開のときに消す行）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

CC = Path(__file__).resolve().parent.parent
VERBOSE = '-v' in sys.argv
fails, infos = [], []

PRIVATE = ('_非公開/', 'docs/作業記録/')
LOOSE = ('docs/H3受け渡し契約.md', 'docs/Suno受け渡し契約.md')  # OLDNAME・PERSONAL は数だけ（契約の実物の例）
DIRS = 'docs|tools|server|editor|pyengine|setup|skills|templates|effects_lib|importers'
ROOT_FILES = {'README.md', 'README.ja.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'AGENTS.md', 'CLAUDE.md', 'package.json', 'extension.js', 'extension_setup.js',
              '.gitignore', '.gitattributes'}
OLD = re.compile(r'claude-cut|claude cut|claudeCut|\bccpy\b|\bcc\.cmd\b|cc_state|cc_api|\bCC_[A-Z]+|X-CC-|CLAUDE_CUT_DIR|クロードカット')
OLD_OK_TOKENS = ['claude-cut/py1', 'claude-cut-h3', '"ccpy"', '`ccpy`）＝ファイルの形']
OLD_OK_WORDS = re.compile(r'前の名前|古い名前|改名|互換|受け口|当時の名前|変えていない|変わっていない|claude-cut から|claudeCut から|earlier name|old names?|compatib')

def _personal():
    """作者の PC の言葉：ドライブ文字で始まるパス（どこでも）＋ 作者の環境の言葉（_非公開/公開の検査.json の smoke_docs。言葉そのものが個人の情報なので
    公開用のリポジトリには入らない＝そこではドライブ文字のパスだけを見る）"""
    rx = [r'(?<![A-Za-z])[A-Z]:[/\\](?![/\\]?path|Windows|Program)']
    try:
        rx.append(json.loads((CC / '_非公開' / '公開の検査.json').read_text(encoding='utf-8'))['smoke_docs'])
    except (OSError, ValueError, KeyError):
        pass
    return re.compile('|'.join(rx))


PERSONAL = _personal()
DRIVE_TOKEN = re.compile(r'(?<![A-Za-z])[A-Z]:[/\\][^\s`）（、。|「」]*')
PATH_SKIP = {'docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md', 'tools/prepare_page.py', 'tools/detect_panels.py',  # 技術集が指す、ほかのリポジトリの中のパス
             'server/defaults.author.json'}  # その PC の置き方の既定値（無くてよいファイル。インストールガイドの 12）
EXTS = r'\.(?:md|py|js|json|txt|cmd|ps1|css|html|pth)'
FLAG_OWNERS = {  # この言葉のある行の --引数 は、右のファイルのどれかに書いてあること
    'mittler_setup.py': ['setup/mittler_setup.py'],
    'new_project.js': ['tools/new_project.js'],
    'install_vscode.py': ['tools/install_vscode.py'],
    'fix_hooks.py': ['tools/fix_hooks.py'],
    'mittler.cmd serve': ['server/main.js'],
    'server\\main.js': ['server/main.js'], 'server/main.js': ['server/main.js'],
    '-m mittler': ['pyengine/mittler/__main__.py', 'pyengine/mittler/enhance.py', 'pyengine/mittler/master.py'],
    'mittler master': ['pyengine/mittler/__main__.py', 'pyengine/mittler/master.py'],
    'mittler video': ['pyengine/mittler/__main__.py'], 'mittler stills': ['pyengine/mittler/__main__.py'], 'mittler serve': ['pyengine/mittler/__main__.py'],
    'mittler enhance': ['pyengine/mittler/enhance.py', 'pyengine/mittler/__main__.py', 'pyengine/mittler/master.py'],
    'enhance.cmd': ['pyengine/mittler/enhance.py', 'pyengine/mittler/__main__.py', 'pyengine/mittler/master.py'],
    'mittler_api.py': ['tools/mittler_api.py'],
    'smoke_plan.py': ['tools/smoke_plan.py'], 'smoke_export.py': ['tools/smoke_export.py'], 'smoke_bugs': ['tools/smoke_bugs.py', 'tools/smoke_bugs_ui.py'],
    'smoke_ui.py': ['tools/smoke_ui.py'], 'smoke_text.py': ['tools/smoke_text.py'], 'smoke_compat.py': ['tools/smoke_compat.py'], 'smoke_setup.py': ['tools/smoke_setup.py'],
    'av_ai_check.py': ['tools/av_ai_check.py'], 'smoke_3d.py': ['tools/smoke_3d.py'],
}
FLAG_SKIP = {'--scope', '--silent', '--disable-interactivity', '--index-url', '--extra-index-url', '--global', '--add', '--follow', '--uninstall-extension', '--install-extension',
             '--extensionDevelopmentPath', '--list-extensions', '--force', '--dangerously-skip-permissions', '--model', '--add-dir', '--print-timeout', '--print', '--version', '--porcelain'}


def read(rel):
    return (CC / rel).read_text(encoding='utf-8')


def tracked():
    """git で追跡しているファイル。git のリポジトリの根でなければ（公開用の書き出し）、フォルダをたどる（作業のフォルダは除く）"""
    top = subprocess.run(['git', '-C', str(CC), 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
    if not top or Path(top).resolve() != CC.resolve():
        skip = {'.git', '__pycache__', 'dist', 'work', '_trash', 'node_modules'}
        return sorted(p.relative_to(CC).as_posix() for p in CC.rglob('*') if p.is_file() and not skip & set(p.relative_to(CC).parts[:-1]))
    out = subprocess.run(['git', '-c', 'core.quotepath=false', '-C', str(CC), 'ls-files'], capture_output=True, text=True, encoding='utf-8').stdout
    return [l for l in out.splitlines() if l]


def result(name, bad, total, note=''):
    print(f"{'FAIL' if bad else 'OK  '} {name}：{len(bad)} 件" + (f'／{total}' if total else '') + (f'（{note}）' if note else ''), flush=True)
    for b in (bad if VERBOSE else bad[:12]):
        print('       ' + b)
    if len(bad) > 12 and not VERBOSE:
        print(f'       …ほか {len(bad) - 12} 件（-v で全部）')
    if bad:
        fails.append(name)


def main():
    files = tracked()
    fileset = set(files)
    dirset = {str(Path(f).parent).replace('\\', '/') + '/' for f in files} | {'/'.join(f.split('/')[:i]) + '/' for f in files for i in range(1, f.count('/') + 1)}
    mds = [f for f in files if f.endswith('.md') and not f.startswith(PRIVATE)]
    code = [f for f in files if f.endswith(('.js', '.py', '.cmd', '.ps1', '.json')) and not f.startswith(PRIVATE) and f != 'tools/smoke_docs.py']
    code_text = {f: read(f) for f in code}
    all_code = '\n'.join(code_text.values())
    all_code_slash = all_code.replace('\\\\', '/').replace('\\', '/')
    pkg = json.loads(read('package.json'))
    props = set(pkg['contributes']['configuration']['properties'])
    ids = props | {c['command'] for c in pkg['contributes']['commands']} | {e['viewType'] for e in pkg['contributes']['customEditors']} | {'claudeCut.timeline'}
    groups = {'.'.join(p.split('.')[:i]) for p in ids for i in range(1, p.count('.') + 1)}
    server = read('server/server.js')

    bad = {k: [] for k in ('LINK', 'PATH', 'SETTING', 'ENV', 'API', 'FLAG', 'SECTION', 'SMOKE', 'OLDNAME', 'PERSONAL')}
    n = {k: 0 for k in bad}
    loose_old, loose_personal, private_refs = {}, {}, []
    heads = {f: re.findall(r'^#{2,3} +(\d+(?:\.\d+)?)[.． ]', read(f), re.M) for f in mds}
    guide = {'インストールガイド': 'docs/インストールガイド.md', 'AI 用ガイド': 'docs/スターターガイド（AI用）.md', 'AI用ガイド': 'docs/スターターガイド（AI用）.md',
             '人間用ガイド': 'docs/スターターガイド（人間用）.md'}

    for f in mds:
        base = Path(f).parent
        loose = f.startswith(LOOSE)
        in_code = False
        compat_section = False  # 「古い名前」「claude-cut から」の章の中は、古い名前の説明そのもの
        in_private = False  # <!-- private:begin -->〜<!-- private:end --> の中（公開用の書き出しで落とす作者の環境の話）は PERSONAL・_非公開 を数えない
        for i, line in enumerate(read(f).splitlines(), 1):
            at = f'{f}:{i}'
            if re.match(r'\s*<!--\s*private:(begin|end)\b', line):
                in_private = 'begin' in line
                continue
            if line.strip().startswith('```'):
                in_code = not in_code
            if re.match(r'#{1,3} ', line) and not in_code:
                compat_section = bool(re.search(r'古い名前|前の名前|claude-cut', line))
            # LINK
            for m in re.finditer(r'\]\(([^)\s#]+)(#[^)]*)?\)', line):
                t = m.group(1)
                if re.match(r'[a-z]+:', t):
                    continue
                n['LINK'] += 1
                p = (base / t).as_posix()
                p = str(Path(p)).replace('\\', '/')
                norm = '/'.join(x for x in _norm(p))
                if norm not in fileset and norm.rstrip('/') + '/' not in dirset:
                    bad['LINK'].append(f'{at} → {t}')
            # PATH（バッククォートの中と、コードの囲みの中）
            spans = [line] if in_code else re.findall(r'`([^`]+)`', line)
            for s in spans:
                for tok in re.split(r'[\s"\'、。：;,]+', s):
                    t = tok.replace('\\', '/').lstrip('（(')
                    t = re.sub(r'^<(mittler|repo|cc|このリポジトリ)>/', '', t)
                    t = re.sub(r'^\.\./', '', t) if f.count('/') else t
                    if not (re.match(rf'^({DIRS})/', t) or t in ROOT_FILES) or t in PATH_SKIP:
                        continue
                    if re.search(r'[*<>…{}|$%]|\.\.\.', t) or t.endswith(('_', '-')):
                        continue
                    t = re.sub(r':\d+(-\d+)?(,\d+(-\d+)?)*$', '', t).rstrip('.,')
                    # 名前に全角のかっこが入るファイルがあるので、後ろに付いた字（「）の」など）は、拡張子の所で切った形も試す
                    cands = [t, t.rstrip('）)'), t.split('（')[0]] + [t[:m.end()] for m in re.finditer(EXTS, t)]
                    n['PATH'] += 1
                    if not any(c in fileset or c.rstrip('/') + '/' in dirset for c in cands):
                        bad['PATH'].append(f'{at} → {tok}')
            # SETTING
            for m in re.finditer(r'\b(mittler|claudeCut)\.([A-Za-z]+(?:\.[A-Za-z]+)*)(\.\*|\*)?', line):
                name, first = f'{m.group(1)}.{m.group(2)}', m.group(2).split('.')[0]
                if first in ('cmd', 'vsix', 'py', 'js', 'md', 'json', 'exe', 'cut', 'lib', 'helpers', 'onbeat', 'names', 'analyze') or line[m.start() - 1:m.start()] in ('/', '\\', '-', '_'):
                    continue
                n['SETTING'] += 1
                if name not in ids and name not in groups:
                    bad['SETTING'].append(f'{at} → {name}')
            # ENV
            for m in re.finditer(r'\bMITTLER_([A-Z][A-Z0-9_]*)\b', line):
                if m.group(1) in ('NOTIFY', 'ICO', 'THEME', 'SET_DISABLED', 'STATUS_LEVEL', 'NEWPROJECT', 'EDITOR', 'CALC', 'LANE_DBL', 'INSPECT_TRACK', 'DEBUG_META'):
                    continue  # 編集画面の window.MITTLER_*（環境変数ではない）
                n['ENV'] += 1
                if f'MITTLER_{m.group(1)}' not in all_code and not re.search(rf"['\"]{m.group(1)}['\"]", all_code):
                    bad['ENV'].append(f'{at} → MITTLER_{m.group(1)}')
            # API
            for m in re.finditer(r'(?<![\w.])/api/[a-z_/]+', line):
                t = m.group(0).rstrip('/')
                n['API'] += 1
                if f"'{t}'" not in server and f"'{t}/" not in server and f'{t}/' not in server:
                    bad['API'].append(f'{at} → {t}')
            # FLAG
            owners = [v for k, v in FLAG_OWNERS.items() if k in line]
            if owners:  # 1 行にいくつかの道具が出てくることがあるので、道具のコード全部のどこかにあればよい（書きまちがいは見つかる）
                text = '\n'.join(code_text.get(x, '') for v in FLAG_OWNERS.values() for x in v)
                for m in re.finditer(r'(?<![\w-])--[a-z][a-z0-9-]*', line):
                    if m.group(0) in FLAG_SKIP:
                        continue
                    n['FLAG'] += 1
                    if m.group(0) not in text:
                        bad['FLAG'].append(f'{at} → {m.group(0)}')
            # SECTION
            for label, target in guide.items():
                for m in re.finditer(re.escape(label) + r'(?:\.md)?[`）]*(?: の|の) ?(\d+(?:\.\d+)?)(?![\d.]*\s*(?:秒|倍|個|本|枚|人|GB|MB|fps|コマ|％|%))', line):
                    n['SECTION'] += 1
                    if m.group(1) not in heads.get(target, []):
                        bad['SECTION'].append(f'{at} → {label}の {m.group(1)}')
            # SMOKE
            for m in re.finditer(r'\bsmoke_[a-z0-9]+(?:_[a-z0-9]+)*', line):
                if m.group(0) in ('smoke_', 'smoke_test'):
                    continue
                n['SMOKE'] += 1
                if f'tools/{m.group(0)}.py' not in fileset:
                    bad['SMOKE'].append(f'{at} → {m.group(0)}')
            # OLDNAME
            rest = line
            for t in OLD_OK_TOKENS:
                rest = rest.replace(t, '')
            rest = re.sub(r'sa-san10[./]claude-cut|claude-cut-new-project|[\\/]claude-cut[\\/]|…[\\/]claude-cut', '', rest)
            if OLD.search(rest):
                if loose:
                    loose_old[f] = loose_old.get(f, 0) + 1
                else:
                    n['OLDNAME'] += 1
                    # 互換の説明とみなす行：その章の中／「前の名前」などの言葉がある／新しい名前（mittler）と並べて書いてある
                    if not (compat_section or OLD_OK_WORDS.search(line) or re.search(r'mittler', rest, re.I)):
                        bad['OLDNAME'].append(f'{at} → {OLD.search(rest).group(0)}：{line.strip()[:70]}')
            # PERSONAL
            if in_private or re.search(r'<!--\s*private:line\b', line):
                continue
            if '_非公開' in line:
                private_refs.append(at)
            if PERSONAL.search(re.sub(r'github\.com/sa-san10/mittler\b', '', line)):  # 公開用のリポジトリの URL（package.json・LICENSE と同じく公開の名前）は通す
                if loose:
                    loose_personal[f] = loose_personal.get(f, 0) + 1
                else:
                    n['PERSONAL'] += 1
                    toks = DRIVE_TOKEN.findall(line)
                    is_default = toks and all(t.replace('\\', '/').rstrip('/…') in all_code_slash for t in toks)
                    words = PERSONAL.sub('', re.sub(DRIVE_TOKEN, '', line)) != re.sub(DRIVE_TOKEN, '', line)
                    if not is_default or words:
                        bad['PERSONAL'].append(f'{at}：{line.strip()[:80]}')

    # tools/ の smoke は AI 用ガイドに全部出てくる
    ai = read('docs/スターターガイド（AI用）.md')
    for f in files:
        m = re.match(r'tools/(smoke_\w+)\.py$', f)
        if m:
            n['SMOKE'] += 1
            if m.group(1) not in ai:
                bad['SMOKE'].append(f'docs/スターターガイド（AI用）.md に {m.group(1)} が出てこない')

    print(f'smoke_docs: 公開する文書 {len(mds)} 本', flush=True)
    for k in bad:
        result(k, bad[k], n[k])
    if loose_old:
        print('INFO 古い名前が出てくる行（入口でない文書。数だけ）：' + '、'.join(f'{Path(k).name} {v}' for k, v in sorted(loose_old.items())))
    if loose_personal:
        print('INFO 作者の PC の言葉が出てくる行（入口でない文書。数だけ）：' + '、'.join(f'{Path(k).name} {v}' for k, v in sorted(loose_personal.items())))
    if private_refs:
        print('INFO `_非公開/` を指している行（公開用のリポジトリを作るときに消す）：' + '、'.join(private_refs))
    print(f'smoke_docs: {"FAIL " + "・".join(fails) if fails else "OK"}')
    sys.exit(1 if fails else 0)


def _norm(p):
    out = []
    for x in p.split('/'):
        if x in ('', '.'):
            continue
        if x == '..':
            if out:
                out.pop()
            continue
        out.append(x)
    return out


if __name__ == '__main__':
    main()
