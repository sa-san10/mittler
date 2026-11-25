"""配布版（中身を全部入れた VSIX）の確かめ（2026-11-13 パッケージ化。ブラウザ・VS Code は要らない。描画の python（numpy・opencv・Pillow）で流す）。
  <描画の python> -X utf8 tools/smoke_package.py [--work <フォルダ>] [--vsix <作った VSIX>]
  （--work：試しの作品と展開した拡張を残す場所。無ければ一時フォルダに作って消す。--vsix：作らずに、その VSIX を確かめる）
確かめること：
1. tools/build_vsix.py で VSIX を作る（2 回作って同じ SHA）。目録・[Content_Types].xml・package.json の版・印 mittler_build.json・入れないもの（smoke・開発の道具・作者の作業用と作品専用のもの）が無い
2. 一時フォルダに展開して、そこを拡張の置き場とみなす（VS Code の代わり。中のファイルの一覧と大きさ・時刻を、始める前と終わったあとで比べる＝1 つも増えない・変わらない）
3. 展開した new_project.js で作品を作る：作品のファイル（AGENTS.md・CLAUDE.md・README.md・.claude/settings.json・.gitignore・タイムライン・characters.json・pronunciation.json）に
   絶対パス（ドライブ文字で始まるもの）・拡張の置き場・リポジトリの場所が無い。.mittler/ に env.json（mittler_dir＝展開した置き場・kind vsix）・guide.md・中継
4. 展開した server/main.js でサーバーを立てる（VS Code の中の Node）：描画サーバーが起動・プレビューの1コマ・📷・書き出し（一部）・編集画面の「＋ 新規」（作った作品にも絶対パスが無い）・
   env.json に描く python が入る・/api/quit で止まる・部品の置き場に偽マリアのエフェクト集が出て「作品に入れる」で写せ、素材の無い作品で描ける（2026-11-13 公開の準備）
5. フック（作品の .claude/settings.json の文字列そのもの。cmd で、CLAUDE_PROJECT_DIR あり／なしで作品の中のフォルダから）・python .mittler/api.py . status・
   python .mittler/engine.py stills（📷 と同じ PNG）・まだ開いていない作品ではフックが何も出さずに終わる
6. 前からの作品の形（.claude-cut/・絶対パスのフック）を展開した置き場で開く：.claude-cut/ に env.json・中継を書き、.mittler/ を作らない・作品のファイルを書きかえない
7. 拡張（extension.js）を、vscode の代わりの偽物で展開した置き場から読む：コマンド mittler.setup の登録・「Mittler: 初期設定」の確かめ（描ける python のとき／描ける python が無いとき：
   「描く python を入れる…」が出る。押さない）・作品を開いて描く python が無いときの案内（日本語・英語）
8. tools/fix_hooks.py の今の書き方が tools/new_project.js の HOOK_CMD と同じ
サーバーのログ・作品に書かれたファイルに、リポジトリの場所が出てこない（展開した置き場だけで動いている）ことも見る。
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
fails = []
sys.path.insert(0, str(ROOT / 'tools'))
import build_vsix  # noqa: E402


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


def node_cmd():
    n = shutil.which('node')
    if n:
        return [n], {}
    exe = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Microsoft VS Code' / 'Code.exe'
    if exe.is_file():
        return [str(exe)], {'ELECTRON_RUN_AS_NODE': '1'}
    sys.exit('node が見つからない（VS Code の Code.exe も無い）')


NODE, NODE_ENV = node_cmd()


def clean_env(**kw):
    e = {k: v for k, v in os.environ.items() if not k.startswith(('CC_', 'MITTLER_', 'CLAUDE_PROJECT_DIR'))}
    e.update(NODE_ENV)
    e.update({k: str(v) for k, v in kw.items()})
    return e


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def snapshot(d):
    """フォルダの中身：{相対パス: (大きさ, 更新時刻)}（フォルダも入れる）"""
    out = {}
    for p in sorted(Path(d).rglob('*')):
        st = p.stat()
        out[p.relative_to(d).as_posix() + ('/' if p.is_dir() else '')] = (0 if p.is_dir() else st.st_size, 0 if p.is_dir() else st.st_mtime_ns)
    return out


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close()
    return p


ABS = re.compile(r'(?<![A-Za-z])[A-Za-z]:[\\/]')


def no_abs(files, also=()):
    """ファイルの中に、ドライブ文字で始まるパスと also の文字（展開した置き場・リポジトリ）が無いか → 見つかったものの一覧"""
    bad = []
    for f in files:
        t = Path(f).read_text(encoding='utf-8')
        if ABS.search(t):
            bad.append(f'{Path(f).name}: {ABS.search(t).group(0)}…')
        for a in also:
            for v in {a, a.replace('\\', '/'), a.replace('\\', '\\\\')}:
                if v and v in t:
                    bad.append(f'{Path(f).name}: {v}')
    return bad


class Server:
    """展開した置き場の server/main.js（VS Code の中の Node）。止めるのは /api/quit"""

    def __init__(self, ext, tl, log):
        self.log = open(log, 'w', encoding='utf-8')
        self.p = subprocess.Popen(NODE + [str(ext / 'server' / 'main.js'), str(tl), '--port', str(free_port()), '--render-python', PY, '--lang', 'ja'],
                                  stdout=subprocess.PIPE, stderr=self.log, env=clean_env(MITTLER_NO_REVEAL=1), cwd=str(tl.parent),
                                  text=True, encoding='utf-8', errors='replace')
        self.url = self.p.stdout.readline().strip()
        if not self.url.startswith('http://127.0.0.1:'):
            raise SystemExit(f'サーバーが起動しない：{self.url}')
        self.token = re.search(r'token=(\w+)', self.url).group(1)
        self.base = self.url.split('/editor/')[0]

    def call(self, path, body=None, timeout=180):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode('utf-8'),
                                     method='POST' if body is not None else 'GET', headers={'X-Mittler-Token': self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def json(self, path, body=None, timeout=180):
        return json.loads(self.call(path, body, timeout)[1])

    def ready(self):
        st = {}
        for _ in range(240):
            st = self.json('/api/status')
            if st.get('ready') or st.get('error'):
                return st
            time.sleep(0.5)
        return st

    def quit(self):
        code = self.call('/api/quit', body={})[0]
        try:
            self.p.wait(timeout=45)
        except subprocess.TimeoutExpired:
            print('サーバーが止まらない pid', self.p.pid)
        self.log.close()
        return code


def part_build(work, given):
    if given:
        vsix = Path(given).resolve()
    else:
        vsix, names, s1, info = build_vsix.build(work / 'a' / 'mittler.vsix')
        vsix2, _, s2, _ = build_vsix.build(work / 'b' / 'mittler.vsix')
        check(s1 == s2 and vsix.read_bytes() == vsix2.read_bytes(), f'同じ中身なら同じ VSIX（SHA-256 {s1[:16]}…・{vsix.stat().st_size:,} バイト・{len(names) + 1} 個）')
    pkg = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(vsix) as z:
        names = z.namelist()
        mani = z.read('extension.vsixmanifest').decode('utf-8')
        types = z.read('[Content_Types].xml').decode('utf-8')
        vpkg = json.loads(z.read('extension/package.json'))
        build = json.loads(z.read('extension/mittler_build.json'))
        notices = z.read('extension/THIRD_PARTY_NOTICES.md').decode('utf-8') if 'extension/THIRD_PARTY_NOTICES.md' in names else ''
    check(f'Version="{pkg["version"]}"' in mani and f'Id="{pkg["name"]}"' in mani and f'Publisher="{pkg["publisher"]}"' in mani and vpkg['main'] == './extension.js'
          and vpkg['version'] == pkg['version'] and build['version'] == pkg['version'],
          f'目録（extension.vsixmanifest）・package.json（main ./extension.js・版 {vpkg["version"]}）・印 mittler_build.json')
    check(vpkg.get('license') == 'MIT' and 'private' not in vpkg and 'extension/' + vpkg.get('icon', '?') in names and 'sa-san10' in str(vpkg.get('repository')),
          f"公開の項目（license {vpkg.get('license')}・private なし・icon {vpkg.get('icon')} が入っている・repository）")
    exts = {Path(n).suffix.lower() for n in names if Path(n).suffix and n.startswith('extension/')}
    check(all(f'Extension="{x}"' in types for x in exts), f'[Content_Types].xml に入れたファイルの拡張子が全部ある（{len(exts)} 種類）')
    must = ['extension/extension.js', 'extension/extension_setup.js', 'extension/server/server.js', 'extension/server/project_env.js', 'extension/editor/index.html',
            'extension/pyengine/mittler/__main__.py', 'extension/pyengine/ccpy/__init__.py', 'extension/effects_lib/common/subtitle.py', 'extension/tools/new_project.js',
            'extension/tools/mittler_state.py', 'extension/tools/mittler_api.py', 'extension/tools/cc_state.py', 'extension/templates/project/AGENTS.md', 'extension/templates/state/hook.py',
            'extension/docs/スターターガイド（AI用）.md', 'extension/setup/mittler_setup.py', 'extension/setup/requirements-engine.txt', 'extension/skills/mittler-new-project/SKILL.md',
            'extension/package.nls.json', 'extension/package.nls.ja.json', 'extension/README.md', 'extension/README.ja.md',
            # 公開の準備（2026-11-13）：ライセンス・表示・アイコン・偽マリアのエフェクト集（コードだけで描くもの）と置き場の並び
            'extension/LICENSE', 'extension/THIRD_PARTY_NOTICES.md', 'extension/images/icon.png', 'extension/effects_lib/library.json',
            *[f'extension/effects_lib/false_maria/{n}.py' for n in FM]]
    lacking = [m for m in must if m not in names]
    check(not lacking, f'要るものが入っている（{lacking or len(must)}）')
    # 編集画面のアイコン（2026-11-14。Lucide、ISC）：リポジトリの editor/icons/ の SVG 全部と、ライセンスの本文が入っている
    icons = sorted(p.name for p in (ROOT / 'editor' / 'icons').glob('*.svg'))
    lack_ic = [n for n in icons if f'extension/editor/icons/{n}' not in names]
    check(icons and not lack_ic and 'extension/editor/icons/LICENSE-lucide.txt' in names and 'Lucide' in notices,
          f'アイコン（Lucide）の SVG {len(icons)} 個と LICENSE-lucide.txt が入っている・THIRD_PARTY_NOTICES.md に Lucide' + (f' 無い：{lack_ic}' if lack_ic else ''))
    # 作者の PC の既定値：今のリポジトリ（あれば）から作る作者用の VSIX には入り、公開用の書き出し（無い）から作る VSIX には無い
    author = (ROOT / 'server' / 'defaults.author.json').is_file()
    check(('extension/server/defaults.author.json' in names) == author,
          f"作者の PC の既定値（server/defaults.author.json）：{'元にあるので入っている' if author else '元に無いので入っていない（公開用）'}")
    not_in = r'/tools/smoke_|/work/|/_trash/|__pycache__|\.pyc$|/\.git|/dist/|install_vscode\.py|build_vsix\.py|export_public\.py'
    bad = [n for n in names if re.search(not_in, n)]
    check(not bad, f'入れないものが無い（{bad[:5] or "なし"}）')
    return vsix


def make_project(ext, d, title='試し', lang='ja'):
    r = subprocess.run(NODE + [str(ext / 'tools' / 'new_project.js'), str(d), '--title', title, '--lang', lang, '--width', '320', '--height', '180', '--duration', '4', '--no-git', '--json'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=clean_env(), timeout=120)
    if r.returncode:
        raise SystemExit('new_project 失敗: ' + r.stdout + r.stderr)
    tl = d / f'{d.name}.cut.json'
    t = json.loads(tl.read_text(encoding='utf-8'))
    tr = {x['id']: x for x in t['tracks']}
    tr['t_sub_0']['clips'] = [{'id': 'sub_1', 'type': 'subtitle', 'start': 0.5, 'dur': 3, 'text': 'パッケージの確かめ', 'style': {'size': 24}}]
    tl.write_text(json.dumps(t, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    return tl


def project_files(d):
    fs = [d / n for n in ('AGENTS.md', 'CLAUDE.md', 'README.md', '.gitignore', 'characters.json', 'pronunciation.json', '.claude/settings.json')] + list(d.glob('*.cut.json'))
    return [f for f in fs if f.is_file()]


def part_project(ext, work):
    d = work / 'proj' / 'pkgtest'
    tl = make_project(ext, d)
    bad = no_abs(project_files(d), (str(ext), str(ROOT), str(Path.home())))
    check(not bad, f'新しい作品のファイル（AGENTS.md・CLAUDE.md・README.md・.gitignore・settings.json・タイムラインほか {len(project_files(d))} 個）に絶対パスが無い（{bad[:4] or "なし"}）')
    bad = no_abs([], ()) + [f.name for f in (d / 'effects').glob('*.py') if str(ext) in f.read_text(encoding='utf-8') or str(ROOT) in f.read_text(encoding='utf-8')]
    check(not bad, f'作品の effects/*.py に拡張の置き場・リポジトリの場所が無い（{bad or "なし"}）')
    env = json.loads((d / '.mittler' / 'env.json').read_text(encoding='utf-8'))
    relays = all((d / '.mittler' / n).is_file() for n in ('guide.md', 'hook.py', 'api.py', 'engine.py'))
    check(Path(env['mittler_dir']) == ext and env['mittler_kind'] == 'vsix' and relays and (d / '.mittler' / 'guide.md').read_text(encoding='utf-8').count('# Mittler スターターガイド（AI用') == 1,
          f"new_project が .mittler/ に env.json（mittler_dir＝展開した置き場・kind {env['mittler_kind']}）・guide.md・中継を書いた")
    claude = (d / 'CLAUDE.md').read_text(encoding='utf-8')
    check('@AGENTS.md' in claude and '@.mittler/guide.md' in claude, 'CLAUDE.md は @AGENTS.md と @.mittler/guide.md を読み込む')
    # まだ編集画面で開いていない（env.json に描く python が無い）：engine.py は PATH の python のうち描けるものを探す（ここでは描画の python を PATH の頭に置く）
    e = clean_env(PATH=str(Path(PY).parent) + os.pathsep + os.environ.get('PATH', ''))
    r = subprocess.run([PY, '-X', 'utf8', str(Path('.mittler') / 'engine.py'), 'stills', tl.name, '--at', '1.0', '--out', 'work/stills0'], cwd=str(d),
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=e, timeout=300)
    check(r.returncode == 0 and (d / 'work' / 'stills0' / 'still_001.000.png').is_file() and not env['render_python'],
          f'まだ開いていない作品（env.json の描く python が空）でも python .mittler/engine.py stills が描ける python を探して描く（{r.stderr.strip()[-120:]}）')
    return d, tl


def run_hook(cmd, cwd, project_env):
    e = clean_env(PYTHONIOENCODING='utf-8')
    if project_env:
        e['CLAUDE_PROJECT_DIR'] = str(project_env)
    return subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, encoding='utf-8', errors='replace', env=e, timeout=60)


def part_server(ext, work, d, tl):
    srv = Server(ext, tl, work / 'server.log')
    stills = {}
    try:
        st = srv.ready()
        check(st.get('ready') is True, f'展開した置き場の server/main.js で描画サーバーが起動する（{st.get("error") or "ready"}）')
        s, body = srv.call('/api/frame?t=1.5&token=' + srv.token)
        check(s == 200 and body[:2] == b'\xff\xd8', f'プレビューの1コマ（JPEG {len(body)} バイト）')
        r = srv.json('/api/still', {'t': 1.5})
        stills['api'] = sha(d / r['path']) if r.get('ok') else None
        check(bool(stills['api']), f"📷 PNG（{r.get('path') or r.get('error')}）")
        srv.call('/api/export', {'name': 'pkg_part', 'from': 0, 'to': 1, 'jobs': 2})
        j = {}
        for _ in range(600):
            j = srv.json('/api/export')
            if j.get('state') in ('done', 'error', 'failed', 'cancelled'):
                break
            time.sleep(0.2)
        res = j.get('result') or {}
        check(j.get('state') == 'done' and (d / 'output' / 'pkg_part.mp4').is_file(), f"書き出し（0〜1 秒・{j.get('state')}・{res.get('bytes')} バイト・{str(res.get('sha256'))[:12]}）")
        env = json.loads((d / '.mittler' / 'env.json').read_text(encoding='utf-8'))
        check(Path(env.get('render_python') or '.') == Path(PY) and env.get('written_by') == 'server' and Path(env['mittler_dir']) == ext,
              f"サーバーが env.json を書き直す（描く python {env.get('render_python')}・by {env.get('written_by')}）")
        srv.call('/api/state', {'name': '試し', 'time': {'t': 1.5, 'frame': 45}, 'selection': {'id': 'sub_1', 'label': 'パッケージの確かめ', 'type': 'subtitle', 'track': {'name': '字幕'},
                                'start': 0.5, 'end': 3.5}, 'at_time': [], 'frame_t': 1.5})
        hook = json.loads((d / '.claude' / 'settings.json').read_text(encoding='utf-8'))['hooks']['UserPromptSubmit'][0]['hooks'][0]['command']
        r1 = run_hook(hook, d / 'effects', d)
        r2 = run_hook(hook, d / 'assets' / 'images', None)
        ok = lambda r: r.returncode == 0 and '【Mittler の編集画面の今' in r.stdout and 'sub_1' in r.stdout
        check(ok(r1) and ok(r2), f'フック（settings.json の文字列を cmd で）：CLAUDE_PROJECT_DIR あり（作品の中のフォルダから）・なし（上にたどる）で要約が出る（{(r1.stdout or r1.stderr).splitlines()[:1]}）')
        r = subprocess.run([PY, '-X', 'utf8', str(d / '.mittler' / 'api.py'), '.', 'status'], cwd=str(d), capture_output=True, text=True, encoding='utf-8', errors='replace', env=clean_env(), timeout=60)
        check(r.returncode == 0 and '"ready": true' in r.stdout, f'python .mittler/api.py . status（{(r.stdout or r.stderr).strip()[:60]}）')
        r = subprocess.run([PY, '-X', 'utf8', str(Path('.mittler') / 'engine.py'), 'stills', tl.name, '--at', '1.5', '--out', 'work/stills'], cwd=str(d),
                           capture_output=True, text=True, encoding='utf-8', errors='replace', env=clean_env(), timeout=300)
        png = d / 'work' / 'stills' / 'still_001.500.png'
        stills['relay'] = sha(png) if png.is_file() else None
        check(r.returncode == 0 and stills['relay'] == stills['api'], f'python .mittler/engine.py stills（作品のフォルダで・相対パス）が 📷 と同じ PNG（{str(stills["relay"])[:12]}・{r.stderr.strip()[-120:]}）')
        # 編集画面の「＋ 新規」（POST /api/new_project）
        r = srv.json('/api/new_project', {'parent': str(work / 'proj'), 'id': 'pkgnew', 'title': '新規の試し', 'lang': 'en', 'git': False, 'open': False})
        d2 = work / 'proj' / 'pkgnew'
        bad = no_abs(project_files(d2), (str(ext), str(ROOT))) if r.get('ok') else ['作れない ' + str(r.get('error'))]
        check(r.get('ok') and not bad and (d2 / '.mittler' / 'env.json').is_file(), f'編集画面の「＋ 新規」で作った作品にも絶対パスが無い・.mittler/ がある（{bad[:3] or "なし"}）')
        pr = srv.json('/api/presets/characters')
        check(not pr.get('characters') and pr.get('error'), f"配布版の既定では、キャラのプリセットは無い（理由：{str(pr.get('error'))[:50]}…）")
        part_fx_lib(srv, ext, d, tl)
    finally:
        code = srv.quit()
    check(code == 200 and not (d / '.mittler' / 'server.json').exists(), '/api/quit で止まり、server.json を消す')
    log = (work / 'server.log').read_text(encoding='utf-8', errors='replace')
    check(str(ROOT) not in log and str(ROOT).replace('\\', '/') not in log, 'サーバーのログにリポジトリの場所が出てこない（展開した置き場だけで動いた）')
    # まだ編集画面で開いていない作品（.mittler/ が無い）：フックは何も出さずに終わる
    empty = work / 'proj' / 'unopened'; empty.mkdir(parents=True)
    r = run_hook(hook, empty, empty)
    check(r.returncode == 0 and not r.stdout.strip() and not r.stderr.strip(), f'.mittler/ の無い作品ではフックは何も出さずに 0 で終わる（{r.returncode}・{r.stdout.strip()[:40]}）')


FM = ['fm_edge_neon', 'fm_hearts', 'fm_light', 'fm_match', 'fm_shutter_flash', 'fm_tail_credits']  # 偽マリアのエフェクト集（effects_lib/false_maria。コードだけで描くもの）


def part_fx_lib(srv, ext, d, tl):
    """部品の置き場（/api/effects_lib）に偽マリアのエフェクト集が出る → 「作品に入れる」（/api/effects/add）→ 素材の無い作品で描ける"""
    lib = srv.json('/api/effects_lib')
    fm = {n: v for n, v in lib.items() if v.get('pack') == 'false_maria'}
    named = all(v.get('meta', {}).get('label_en') and v.get('doc_en') and not v.get('error') for v in fm.values())
    check(sorted(fm) == FM and named and lib.get('gl_cards3d', {}).get('pack') == 'common' and 'gl_text3d' not in lib,
          f'部品の置き場に偽マリアのエフェクト集（pack false_maria・英語の名前と説明つき）と common が出る（{sorted(fm)}）')
    added = [srv.json('/api/effects/add', {'name': n}) for n in FM]
    same = all((d / 'effects' / f'{n}.py').read_bytes() == (ext / 'effects_lib' / 'false_maria' / f'{n}.py').read_bytes() for n in FM)
    again = srv.json('/api/effects/add', {'name': 'fm_match'})
    check(all(r.get('ok') for r in added) and same and not again.get('ok'), f'「作品に入れる」で作品の effects/ に写す（同じ中身・2 回目は上書きしない：{str(again.get("error"))[:30]}）')
    check(not any(n in srv.json('/api/effects_lib') for n in FM), '入れたものは部品の置き場の一覧から消える')
    # 素材の無い作品（字幕だけ）に、入れたエフェクトのクリップを置いて描く（写しのタイムラインで。編集画面の「この時刻に置く」と同じく META の defaults）
    t = json.loads(tl.read_text(encoding='utf-8'))
    for i, n in enumerate(FM):
        spec = importlib_meta(d / 'effects' / f'{n}.py')
        start = 0.0 if n != 'fm_tail_credits' else 1.0
        params = json.loads(json.dumps(spec.get('defaults', {})))
        w = spec.get('window') or {}
        if w.get('start'):
            params[w['start']] = start
        t['tracks'].insert(0, {'id': f't_{n}', 'name': n, 'kind': 'effect', 'effect': n, 'clips': [{'id': f'c_{n}', 'type': 'effect', 'effect': n, 'start': start,
                                                                                                     'dur': spec.get('dur', 2), 'params': params}]})
    ft = d / 'fm.test.cut.json'
    ft.write_text(json.dumps(t, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    r = subprocess.run([PY, '-X', 'utf8', str(Path('.mittler') / 'engine.py'), 'stills', ft.name, '--at', '0.0,1.5,3.0', '--out', 'work/stills_fm'], cwd=str(d),
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=clean_env(), timeout=300)
    pngs = [d / 'work' / 'stills_fm' / f'still_{x}.png' for x in ('000.000', '001.500', '003.000')]
    ok = r.returncode == 0 and all(p.is_file() for p in pngs)
    check(ok and len({sha(p) for p in pngs}) == 3, f'入れた {len(FM)} 本を置いた作品（素材なし）を描ける：0 秒・1.5 秒（暗転の途中）・3 秒（クレジット）が別の絵（{r.stderr.strip()[-160:]}）')


def importlib_meta(p):
    """エフェクトのファイルの META（読むだけ。mittler の部品を import するので pyengine をパスに）"""
    import importlib.util
    env =json.loads((Path(p).parents[1] / '.mittler' / 'env.json').read_text(encoding='utf-8'))
    pe = str(Path(env['mittler_dir']) / 'pyengine')
    if pe not in sys.path:
        sys.path.insert(0, pe)
    spec = importlib.util.spec_from_file_location('fx_' + Path(p).stem, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(getattr(mod, 'META', {}))


def part_old(ext, work):
    """前からの作品の形：.claude-cut/・.gitignore は .claude-cut だけ・フックは絶対パスの cc_state.py"""
    d = work / 'proj' / 'oldwork'
    tl = make_project(ext, d)
    shutil.rmtree(d / '.mittler')
    (d / '.gitignore').write_text('assets/\nwork/\noutput/\n.claude-cut/\n*.tmp\n', encoding='utf-8', newline='\n')
    old_hook = 'python "D:/studio/claude-cut/tools/cc_state.py"'  # 前の形（絶対パスのフック）。動かさない（ファイルが変わらないことだけ見る）
    (d / '.claude' / 'settings.json').write_text(json.dumps({'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': old_hook}]}]}}, indent=2) + '\n', encoding='utf-8')
    (d / 'CLAUDE.md').write_text('# 前からの作品\n@../../claude-cut/docs/スターターガイド（AI用）.md\n', encoding='utf-8')
    (d / '.claude-cut').mkdir()
    before = {p.relative_to(d).as_posix(): sha(p) for p in d.rglob('*') if p.is_file() and '.claude-cut' not in p.parts}
    srv = Server(ext, tl, work / 'server_old.log')
    try:
        st = srv.ready()
    finally:
        srv.quit()
    after = {p.relative_to(d).as_posix(): sha(p) for p in d.rglob('*') if p.is_file() and '.claude-cut' not in p.parts}
    check(st.get('ready') is True and (d / '.claude-cut' / 'env.json').is_file() and (d / '.claude-cut' / 'hook.py').is_file() and not (d / '.mittler').exists(),
          '前からの作品（.claude-cut/）を開く：.claude-cut/ に env.json・中継を書き、.mittler/ を作らない')
    check(before == after, f'前からの作品のファイル（CLAUDE.md・settings.json・タイムラインほか {len(before)} 個）を書きかえない')


def part_extension(ext, work):
    """extension.js を、vscode の代わりの偽物で、展開した置き場から読む"""
    js = work / 'ext_check.js'
    js.write_text(r'''const path = require('path'), Module = require('module');
const EXT = process.argv[2], PY = process.argv[3], STORAGE = process.argv[4];
const shown = [], cfg = {};
let lang = 'ja';
const fake = {
  workspace: { isTrusted: true, getConfiguration: sec => ({
    get: k => (k === 'language' ? lang : undefined),
    inspect: k => ({ defaultValue: k === 'language' ? 'en' : '', globalValue: k === 'language' ? lang : (sec === 'mittler' ? cfg[k] : undefined) }),
    update: (k, v) => { cfg[k] = v; return Promise.resolve(); } }) },
  window: {
    registerCustomEditorProvider: () => ({ dispose() { } }),
    createOutputChannel: () => ({ clear() { }, show() { }, appendLine: s => shown.push(['out', s]) }),
    withProgress: (o, f) => f(),
    showInformationMessage: (m, ...b) => { shown.push(['info', m, b]); return Promise.resolve(undefined); },
    showWarningMessage: (m, ...b) => { shown.push(['warn', m, b.filter(x => typeof x === 'string')]); return Promise.resolve(undefined); },
    showErrorMessage: (m, ...b) => { shown.push(['error', m, b]); return Promise.resolve(undefined); },
  },
  commands: { registerCommand: (id, fn) => { cmds[id] = fn; return { dispose() { } }; }, executeCommand: () => Promise.resolve() },
  env: { clipboard: { writeText: () => Promise.resolve() } },
  ProgressLocation: { Notification: 15 }, ConfigurationTarget: { Global: 1 },
  Uri: { file: f => ({ fsPath: f }) },
};
const cmds = {};
const load = Module._load; Module._load = function (req) { return req === 'vscode' ? fake : load.apply(this, arguments); };
const ext = require(path.join(EXT, 'extension.js'));
ext.activate({ subscriptions: [], globalStorageUri: { fsPath: STORAGE }, extension: { packageJSON: require(path.join(EXT, 'package.json')) } });
(async () => {
  const out = { cmds: Object.keys(cmds).sort() };
  cfg['render.python'] = PY; shown.length = 0;
  await cmds['mittler.setup']();
  out.okRun = shown.filter(s => s[0] !== 'out').map(s => [s[0], s[1], s[2]]);
  out.okOut = shown.filter(s => s[0] === 'out').map(s => s[1]).join('\n');
  cfg['render.python'] = path.join(STORAGE, 'no_such', 'python.exe'); shown.length = 0;
  await cmds['mittler.setup']();
  out.badRun = shown.filter(s => s[0] !== 'out').map(s => [s[0], s[1], s[2]]);
  // 作品を開いて描く python が無いとき（サーバーの renderReady が理由の鍵）：日本語・英語
  for (const l of ['ja', 'en']) {
    lang = l; shown.length = 0;
    delete require.cache[require.resolve(path.join(EXT, 'extension.js'))];
    const e2 = require(path.join(EXT, 'extension.js'));
    e2.hintSetup({ renderReady: Promise.resolve('srv.py.noRenderPython') }); e2.hintSetup({ renderReady: Promise.resolve('srv.py.noRenderPython') });
    await new Promise(r => setTimeout(r, 50));
    out['hint_' + l] = shown.map(s => [s[0], s[1], s[2]]);
  }
  // 入れた直後の 1 回の知らせ（extension_setup.js の firstRun）：globalState の偽物と、版を変えた packageJSON で
  lang = 'ja';
  delete require.cache[require.resolve(path.join(EXT, 'extension.js'))];
  const e3 = require(path.join(EXT, 'extension.js'));
  const mem = {};
  const state = { get: k => mem[k], update: (k, v) => { mem[k] = v; return Promise.resolve(); } };
  const ctxOf = v => ({ subscriptions: [], globalStorageUri: { fsPath: STORAGE }, globalState: state, extension: { packageJSON: Object.assign({}, require(path.join(EXT, 'package.json')), { version: v }) } });
  const step = async (name, v, py) => { cfg['render.python'] = py; shown.length = 0; const r = await e3.firstRun(ctxOf(v)); out['first_' + name] = { shown: r.shown, msgs: shown.map(s => [s[0], s[1], s[2]]), seen: mem['mittler.seenVersion'] }; };
  await step('fresh_ok', '9.0.0', PY);          // 初めて・足りている → 歓迎
  await step('again', '9.0.0', PY);             // 同じ版の 2 回目 → 何も出さない
  await step('update_ok', '9.1.0', PY);         // 版が上がった・足りている → 何も出さない
  const bad = path.join(STORAGE, 'no_such', 'python.exe');
  await step('update_lack', '9.2.0', bad);      // 版が上がった・足りない → 知らせ（初期設定・あとで）
  await step('update_lack_again', '9.2.0', bad); // その版ではもう出さない（「あとで」を押したのと同じ）
  delete mem['mittler.seenVersion'];
  await step('fresh_lack', '9.2.0', bad);       // 初めて・足りない → 準備の知らせ
  // activate からも呼ばれる（起動のたびに。待たずに）：同じ版ならすぐ終わる
  shown.length = 0; e3.activate(ctxOf('9.2.0')); out.first_activate = await e3.lastFirstRun();
  console.log(JSON.stringify(out));
})().catch(e => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
''', encoding='utf-8', newline='\n')
    storage = work / 'globalStorage'; storage.mkdir(exist_ok=True)
    r = subprocess.run(NODE + [str(js), str(ext), PY, str(storage)], capture_output=True, text=True, encoding='utf-8', errors='replace', env=clean_env(), timeout=900)
    try:
        o = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        check(False, f'拡張を偽物の vscode で読む（{(r.stdout + r.stderr)[-400:]}）'); return
    if o.get('error'):
        check(False, f"拡張を偽物の vscode で読む：{o['error'][:400]}"); return
    check('mittler.setup' in o['cmds'] and 'claudeCut.setup' in o['cmds'], f"コマンド mittler.setup の登録（{len(o['cmds'])} 個）")
    ok_msgs = o['okRun']
    check(len(ok_msgs) == 1 and ok_msgs[0][0] in ('info', 'warn') and '描く python を入れる…' not in ok_msgs[0][2] and '[OK]' in o['okOut'] and '配布版' in o['okOut'],
          f"「Mittler: 初期設定」（描ける python の設定）：確かめを出力に並べ、入れるボタンは出さない（{ok_msgs[0][1][:60] if ok_msgs else '知らせなし'}）")
    bad = o['badRun']
    check(len(bad) == 1 and bad[0][0] == 'warn' and '描く python を入れる…' in bad[0][2], f"描ける python が無いとき：「描く python を入れる…」が出る（押さない）（{bad[0][1][:70] if bad else '知らせなし'}）")
    hj, he = o['hint_ja'], o['hint_en']
    check(len(hj) == 1 and 'Mittler: 初期設定' in hj[0][2] and len(he) == 1 and 'Mittler: Setup' in he[0][2] and 'Setup' in he[0][1],
          f'作品を開いて描く python が無いとき：「初期設定」への案内を 1 回だけ（日本語「{hj[0][1][:20] if hj else ""}…」・英語「{he[0][1][:20] if he else ""}…」）')
    check(not storage.joinpath('render-venv').exists(), '押していないので、拡張の保存場所に venv を作っていない')
    f = {k[6:]: v for k, v in o.items() if k.startswith('first_')}
    fo, fl = f.get('fresh_ok', {}), f.get('fresh_lack', {})
    ok = (fo.get('shown') == 'welcome' and fo['msgs'] and fo['msgs'][0][0] == 'info' and '新しい作品を作る' in fo['msgs'][0][2] and fo.get('seen') == '9.0.0'
          and f['again']['shown'] == '' and not f['again']['msgs'] and f['update_ok']['shown'] == '' and not f['update_ok']['msgs']
          and f['update_lack']['shown'] == 'lack' and f['update_lack']['msgs'][0][0] == 'warn' and f['update_lack']['msgs'][0][2] == ['Mittler: 初期設定', 'あとで']
          and '9.2.0' in f['update_lack']['msgs'][0][1] and f['update_lack_again']['shown'] == '' and not f['update_lack_again']['msgs']
          and fl.get('shown') == 'lack' and '描く python' in fl['msgs'][0][1] and fl['msgs'][0][2] == ['Mittler: 初期設定', 'あとで']
          and f['activate'].get('shown') == '')
    check(ok, '入れた直後の 1 回の知らせ：初めて＝足りていれば歓迎（新しい作品を作る）・足りなければ「初期設定」「あとで」、同じ版の 2 回目と、版が上がって足りているときは出さない、'
              f"版が上がって足りないときは出す・その版ではもう出さない（{ {k: v.get('shown') for k, v in f.items()} }・{(fl.get('msgs') or [['', '']])[0][1][:50]}…）")


def main():
    keep = sys.argv[sys.argv.index('--work') + 1] if '--work' in sys.argv else None
    given = sys.argv[sys.argv.index('--vsix') + 1] if '--vsix' in sys.argv else None
    ctx = None if keep else tempfile.TemporaryDirectory(prefix='mittler_pkg_', ignore_cleanup_errors=True)
    work = Path(keep).resolve() if keep else Path(ctx.name)
    if keep:
        if work.exists() and any(work.iterdir()):
            sys.exit(f'--work は空のフォルダにする：{work}')
        work.mkdir(parents=True, exist_ok=True)
    try:
        vsix = part_build(work, given)
        root = work / 'installed' / 'sa-san10.mittler-x'
        with zipfile.ZipFile(vsix) as z:
            z.extractall(root.parent / '_unzip')
        shutil.move(str(root.parent / '_unzip' / 'extension'), str(root))
        ext = root
        before = snapshot(ext)
        d, tl = part_project(ext, work)
        part_server(ext, work, d, tl)
        part_old(ext, work)
        part_extension(ext, work)
        after = snapshot(ext)
        added = sorted(set(after) - set(before)); changed = sorted(k for k in before if k in after and after[k] != before[k]); gone = sorted(set(before) - set(after))
        check(not added and not changed and not gone, f'展開した拡張の置き場に、1 つもファイルが増えていない・変わっていない（{len(before)} 個。増えた {added[:5]}・変わった {changed[:5]}・消えた {gone[:5]}）')
        js = subprocess.run(NODE + ['-e', "process.stdout.write(require(process.argv[1]).HOOK_CMD)", str(ROOT / 'tools' / 'new_project.js')],
                            capture_output=True, text=True, encoding='utf-8', env=clean_env(), timeout=60).stdout
        import fix_hooks
        check(js == fix_hooks.CMD, 'tools/fix_hooks.py の今の書き方 ＝ tools/new_project.js の HOOK_CMD')
    finally:
        if ctx:
            ctx.cleanup()
    print(f'smoke_package: {"FAIL " + str(len(fails)) if fails else "OK"}')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
