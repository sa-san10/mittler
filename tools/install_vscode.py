"""Mittler を VS Code に入れる（Node・vsce なし）。開発する人向けの入れ方と、作った配布版（VSIX）を入れる口。
  python tools/install_vscode.py                     開発版：「このリポジトリの extension.js を読み込むだけの入口」の VSIX を作って code --install-extension で入れる
  python tools/install_vscode.py --vsix <VSIX>       配布版：tools/build_vsix.py で作った VSIX（中身を全部入れたもの）を入れる
  python tools/install_vscode.py --uninstall          Mittler の拡張（開発版でも配布版でも。ID は同じ sa-san10.mittler）を外す
  python tools/install_vscode.py --uninstall-old      前の名前の拡張（sa-san10.claude-cut）を外す
（どれも画面は開かない。入れたら VS Code で「ウィンドウの再読み込み」）
開発版と配布版は同じ拡張の ID（sa-san10.mittler）なので、どちらかを入れると、もう片方は置きかわる（入れかえの手順は docs/インストールガイド.md の 2）。
開発版：入れるのは「このリポジトリの extension.js を読み込むだけの入口（loader.js）」と package.json。
→ コードを直しても入れ直しは要らない（VS Code で「Developer: Restart Extension Host」かウィンドウの再読み込み）。
  package.json（customEditors・commands・設定）・package.nls*.json（その表示の文）を変えたときだけ、もう一度これを流す。
2026-11-12 に claude-cut から Mittler に改名して、拡張の ID が sa-san10.claude-cut → sa-san10.mittler になった。前の拡張が入ったままだと、
2つの拡張が *.cut.json を取り合う（どちらで開くかを VS Code に聞かれる・前の拡張で開いてしまう）ので、前の拡張は --uninstall-old で外す
（手順は docs/インストールガイド.md の 13）。入れたあと、前の拡張が残っていれば知らせる。
"""
import json, subprocess, sys, zipfile
from pathlib import Path

sys.dont_write_bytecode = True
CC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_vsix import content_types_xml, manifest_xml, zinfo  # noqa: E402（目録は配布版と同じもの）

OUT = CC / 'work' / 'mittler.vsix'
OLD_ID = 'sa-san10.claude-cut'  # 前の名前の拡張（古い名前の互換のための確かめ・外す用）
CODE = Path.home() / 'AppData' / 'Local' / 'Programs' / 'Microsoft VS Code' / 'bin' / 'code.cmd'
if not CODE.exists():  # ユーザーごとのインストールでなければ、全員用の場所か PATH の code
    import shutil
    CODE = next((p for p in [Path(r'C:\Program Files\Microsoft VS Code\bin\code.cmd')] if p.exists()), None) or Path(shutil.which('code') or 'code')


def build():
    """開発版の入口の VSIX（work/mittler.vsix）を作る"""
    pkg = json.loads((CC / 'package.json').read_text(encoding='utf-8'))
    pkg['main'] = './loader.js'
    # 表示の文（コマンドの名前・設定の説明）は package.nls.json（英語）・package.nls.ja.json（日本語）。VS Code が表示言語に合わせて %鍵% を引く
    nls = {n: (CC / n).read_text(encoding='utf-8') for n in ('package.nls.json', 'package.nls.ja.json') if (CC / n).is_file()}
    loader = ("// Mittler の入口（tools/install_vscode.py が作る開発版）。本体はリポジトリの extension.js\n"
              f"module.exports = require({json.dumps(str(CC / 'extension.js'))});\n")
    OUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(zinfo('[Content_Types].xml'), content_types_xml(['package.json', 'loader.js']))
        z.writestr(zinfo('extension.vsixmanifest'), manifest_xml(pkg))
        z.writestr(zinfo('extension/package.json'), json.dumps(pkg, ensure_ascii=False, indent=2))
        z.writestr(zinfo('extension/loader.js'), loader)
        for n, text in nls.items():
            z.writestr(zinfo('extension/' + n), text)
    return pkg


def code(*args, timeout=180):
    r = subprocess.run([str(CODE), *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    print(r.stdout.strip()); print(r.stderr.strip())
    return r.returncode


def warn_old():
    try:  # 前の名前の拡張が残っていれば知らせる（外すのは人が決める）
        ls = subprocess.run([str(CODE), '--list-extensions'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60).stdout.lower().split()
        if OLD_ID in ls:
            print(f'注意：前の名前の拡張 {OLD_ID} が入ったまま。*.cut.json を取り合うので外す：python tools/install_vscode.py --uninstall-old')
    except (OSError, subprocess.SubprocessError):
        pass


def main():
    if '--uninstall' in sys.argv:
        pkg = json.loads((CC / 'package.json').read_text(encoding='utf-8'))
        sys.exit(code('--uninstall-extension', f"{pkg['publisher']}.{pkg['name']}"))
    if '--uninstall-old' in sys.argv:  # 前の名前の拡張を外す
        sys.exit(code('--uninstall-extension', OLD_ID))
    if '--vsix' in sys.argv:  # 配布版の VSIX を入れる（作るのは tools/build_vsix.py）
        i = sys.argv.index('--vsix')
        vsix = Path(sys.argv[i + 1]).resolve() if i + 1 < len(sys.argv) else None
        if not vsix or not vsix.is_file():
            sys.exit('--vsix <VSIX のファイル>（python tools/build_vsix.py で dist/ に作る）')
        rc = code('--install-extension', str(vsix), '--force')
        warn_old(); sys.exit(rc)
    build()
    rc = code('--install-extension', str(OUT), '--force')
    warn_old(); sys.exit(rc)


if __name__ == '__main__':
    main()
