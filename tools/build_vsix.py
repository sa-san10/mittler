"""Mittler の配布版（中身を全部入れた VSIX）を作る。Python の標準ライブラリだけ（Node・npm・vsce は要らない）。2026-11-13 パッケージ化。
  python tools/build_vsix.py                 dist/mittler-<版>.vsix を作る（<版>＝package.json の version）
  python tools/build_vsix.py --list          入れるファイルの一覧と大きさだけ出す（作らない）
  python tools/build_vsix.py --out <ファイル>  作る場所を変える
入れるのは、git に入っているファイル（git ls-files）のうち下の INCLUDE に当たり EXCLUDE に当たらないもの（中身は作業ツリーのまま。コミットしていない直しも入る）。
git が使えない（リポジトリでない）ときは、フォルダをたどって同じ決まりで選ぶ。
- 拡張の置き場（VS Code が展開する所）だけで全部動く形：拡張・サーバー・編集画面・エンジン（pyengine）・エフェクトの部品（common・beatfx・偽マリアのエフェクト集 false_maria）・
  実行時の道具・ひな形・公開の文書・初期設定・スキル・LICENSE・THIRD_PARTY_NOTICES・アイコン。
- 入れないもの：work/・_trash/・dist/・__pycache__・.git、確かめ（tools/smoke_*.py・calc_cli.js）、開発の道具（install_vscode.py・build_vsix.py・export_public.py）、
  作者の作業用・作者の作品専用のもの（下の EXCLUDE。公開用の書き出しには元から無い）。理由は docs/配布.md。
- 作者の PC の既定値（server/defaults.author.json）は、あれば入る（作者用の VSIX。公開用の書き出しから作った VSIX には無い）。
- 印 mittler_build.json（拡張の置き場の根）：配布版の目印（server/project_env.js・server/defaults.js・setup/mittler_setup.py が見る）。版・コミット。
- 同じ中身なら同じ VSIX（ファイルの並び・時刻・圧縮をそろえる。時刻は 2026-01-01 に固定）。SHA-256 を出す。
入れ方は docs/インストールガイド.md の 2（code --install-extension <vsix>、または VS Code の「VSIX からのインストール…」）。
"""
import argparse
import fnmatch
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
# 入れるもの（ファイルそのものか、フォルダ。/ で終わるものはフォルダ）
INCLUDE = [
    'extension.js', 'extension_setup.js', 'package.json', 'package.nls.json', 'package.nls.ja.json',
    'README.md', 'README.ja.md', 'AGENTS.md', 'CLAUDE.md', 'LICENSE', 'LICENSE.md', 'THIRD_PARTY_NOTICES.md', 'images/icon.png',
    'server/', 'editor/', 'pyengine/', 'effects_lib/common/', 'effects_lib/beatfx/', 'effects_lib/false_maria/', 'effects_lib/library.json',
    'tools/', 'templates/', 'docs/', 'setup/', 'skills/',
]
# 入れないもの（INCLUDE に当たっても外す。fnmatch の形・パスは / 区切り）
EXCLUDE = [
    'work/*', '_trash/*', 'dist/*', '*/__pycache__/*', '*.pyc', '.git*', '*/.git*',
    'tools/smoke_*.py', 'tools/calc_cli.js', 'tools/install_vscode.py', 'tools/build_vsix.py', 'tools/export_public.py',
    'お掃除候補*',
]
STAMP = (2026, 1, 1, 0, 0, 0)  # zip の中のファイルの時刻（同じ中身なら同じ VSIX にするため固定）
MIME = {'.json': 'application/json', '.js': 'application/javascript', '.vsixmanifest': 'text/xml', '.md': 'text/markdown', '.py': 'text/x-python',
        '.html': 'text/html', '.css': 'text/css', '.txt': 'text/plain', '.xml': 'text/xml', '.svg': 'image/svg+xml', '.png': 'image/png',
        '.jpg': 'image/jpeg', '.cmd': 'text/plain', '.ps1': 'text/plain', '.pth': 'text/plain'}


def _git(*a):
    return subprocess.run(['git', '-C', str(ROOT), *a], capture_output=True, text=True, encoding='utf-8', errors='replace')


def _own_repo():
    """ROOT が git のリポジトリの根か（公開用の書き出しを、作者のリポジトリの dist/ の中で動かしたときに、外のリポジトリを読まないように）"""
    try:
        top = _git('rev-parse', '--show-toplevel').stdout.strip()
        return bool(top) and Path(top).resolve() == ROOT
    except OSError:
        return False


OWN = _own_repo()


def git(*a):
    """ROOT が自分のリポジトリのときだけ git を流す（でなければ空の結果）"""
    if not OWN:
        return subprocess.CompletedProcess(a, 1, '', '')
    return _git(*a)


def wanted(rel):
    inc = any(rel == p or (p.endswith('/') and rel.startswith(p)) for p in INCLUDE)
    return inc and not any(fnmatch.fnmatch(rel, x) or fnmatch.fnmatch('/' + rel, '*/' + x) for x in EXCLUDE)


def files():
    """入れるファイル（ROOT からの / 区切りのパス）を名前の順に"""
    r = git('ls-files', '-z')
    if r.returncode == 0 and r.stdout:
        names = [n for n in r.stdout.split('\0') if n]
    else:  # リポジトリでない（公開用の書き出しなど）：フォルダをたどる
        names = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()]
    return sorted(n for n in names if wanted(n) and (ROOT / n).is_file())


def description(pkg):
    """目録の説明：package.json の description（%鍵% なら package.nls.json の英語の文）"""
    desc = pkg.get('description', '')
    if desc.startswith('%') and desc.endswith('%'):
        try:
            desc = json.loads((ROOT / 'package.nls.json').read_text(encoding='utf-8')).get(desc[1:-1], desc)
        except (OSError, ValueError):
            pass
    return desc


def manifest_xml(pkg, details=False):
    """extension.vsixmanifest（VS Code が拡張を入れるときに読む目録。tools/install_vscode.py の開発版の入口も同じものを使う）"""
    e = lambda s: escape(str(s), {'"': '&quot;'})
    assets = '<Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />'
    if details:
        assets += '\n    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true" />'
    return f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{e(pkg['name'])}" Version="{e(pkg['version'])}" Publisher="{e(pkg['publisher'])}"/>
    <DisplayName>{e(pkg.get('displayName', pkg['name']))}</DisplayName>
    <Description xml:space="preserve">{e(description(pkg))}</Description>
    <Categories>Other</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{e(pkg['engines']['vscode'])}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace" />
      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value="" />
    </Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets>
    {assets}
  </Assets>
</PackageManifest>
'''


def content_types_xml(names):
    """[Content_Types].xml：入れるファイルの拡張子ごとの種類（無い拡張子は application/octet-stream）"""
    exts = sorted({Path(n).suffix.lower() for n in names if Path(n).suffix} | {'.json', '.js', '.vsixmanifest'})
    rows = ''.join(f'<Default Extension="{escape(x)}" ContentType="{MIME.get(x, "application/octet-stream")}"/>' for x in exts)
    return f'<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">{rows}</Types>'


def zinfo(name):
    zi = zipfile.ZipInfo(name, STAMP)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.create_system = 0
    zi.external_attr = 0
    return zi


def build(out=None):
    pkg = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
    names = files()
    head = git('rev-parse', 'HEAD').stdout.strip()
    dirty = bool(git('status', '--porcelain', '--untracked-files=no').stdout.strip())
    info = {'name': pkg['name'], 'publisher': pkg['publisher'], 'version': pkg['version'], 'commit': head, 'dirty': dirty,
            'about': '配布版（tools/build_vsix.py で作った VSIX）の印。拡張の置き場はこの中身だけで動き、実行中にここへは書かない'}
    out = Path(out) if out else ROOT / 'dist' / f"{pkg['name']}-{pkg['version']}.vsix"
    out.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(zinfo('[Content_Types].xml'), content_types_xml(names))
        z.writestr(zinfo('extension.vsixmanifest'), manifest_xml(pkg, details='README.md' in names))
        for n in names:
            z.writestr(zinfo('extension/' + n), (ROOT / n).read_bytes())
        z.writestr(zinfo('extension/mittler_build.json'), json.dumps(info, ensure_ascii=False, indent=1) + '\n')
    data = buf.getvalue()
    out.write_bytes(data)
    return out, names, hashlib.sha256(data).hexdigest(), info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--list', action='store_true', help='入れるファイルの一覧だけ')
    ap.add_argument('--out', default='', help='作る VSIX の場所（既定 dist/mittler-<版>.vsix）')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    if a.list:
        total = 0
        for n in files():
            sz = (ROOT / n).stat().st_size; total += sz
            print(f'{sz:>10}  {n}')
        print(f'{total:>10}  （合計。圧縮の前）')
        return
    out, names, sha, info = build(a.out or None)
    print(f'作った：{out}（{out.stat().st_size:,} バイト・ファイル {len(names) + 1} 個・版 {info["version"]}・コミット {info["commit"][:7]}{"＋直しあり" if info["dirty"] else ""}）')
    print(f'SHA-256 {sha}')
    print(f'入れ方：code --install-extension "{out}"（VS Code の「拡張機能」→「…」→「VSIX からのインストール…」でも同じ）')


if __name__ == '__main__':
    main()
