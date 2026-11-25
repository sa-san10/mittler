"""Mittler の初期設定の確かめ（Python の標準ライブラリだけ。どの python でもよい）。
  python setup/mittler_setup.py                 確かめるだけ（何も変えない。--check と同じ）
  python setup/mittler_setup.py --json          同じ結果を JSON で（エージェント向け）
  python setup/mittler_setup.py --python <描く python> [--ffmpeg-dir <ffmpeg の bin>]   この python・ffmpeg で確かめる
  python setup/mittler_setup.py --no-render     試しの1枚を描かない（速い）
  python setup/mittler_setup.py --install-venv <フォルダ>    描画用の venv を作って setup/requirements-engine.txt を入れる（パッケージを取ってくる）
  … --install-venv <フォルダ> --with-3d                       同じ venv に setup/requirements-3d.txt（GPU の 3D：moderngl・glcontext）も入れる
  python setup/mittler_setup.py --install-extension         VS Code に Mittler を入れる（開発版：tools/install_vscode.py を呼ぶ。配布版では使わない）
  python setup/mittler_setup.py --install-skill             Claude Code のスキル（skills/ の中身）を ~/.claude/skills/ に写す
  … --dry-run                                               --install-* が何を流すかだけ見せる（何も入れない）
  … --work <フォルダ>                                        試しの作品をここに作って残す（付けなければ一時フォルダに作って、終わったら消す）
確かめること：VS Code・Git・ffmpeg／ffprobe・描く python（numpy・opencv・Pillow）・Mittler の拡張・前の名前の拡張・Claude Code のスキル・
試しの作品を作って静止画を1枚描けるか。3D（なくてもよい）：描く python の moderngl・Blender（--blender で場所を指定できる。入れはしない）。
決まり：--install-* を付けない限り、何も入れない・何も書きかえない（VS Code の設定も書かない。書く値を見せるだけ）。
既定の場所（server/defaults.js）で見つかったものは「見つかった（設定は要らない）」と出すだけ。
終わりの番号：0＝足りないものなし、1＝足りないものがある、2＝使い方のまちがい。確かめは tools/smoke_setup.py。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # 配布版（VSIX）の拡張の置き場から動かしても、そこに __pycache__ を書かない
REPO = Path(__file__).resolve().parent.parent
REQ = REPO / 'setup' / 'requirements-engine.txt'
REQ_3D = REPO / 'setup' / 'requirements-3d.txt'
PACKAGED = (REPO / 'mittler_build.json').is_file()  # 配布版（tools/build_vsix.py が入れる印）。開発版（リポジトリ）は False
OLD_EXT = 'sa-san10.claude-cut'      # 前の名前の拡張（古い名前の互換のための確かめ）
OLD_SKILL = 'claude-cut-new-project'  # 前の名前のスキル（同じ）
OK, WARN, MISSING, INFO = 'ok', 'warn', 'missing', 'info'
MARK = {OK: '[OK]  ', WARN: '[注意]', MISSING: '[不足]', INFO: '[--]  '}


def run(cmd, timeout=60, **kw):
    """コマンドを流して (終わりの番号, 標準出力, 標準エラー)。起動できなければ (None, '', 理由)。"""
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, **kw)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return None, '', f'{type(e).__name__}: {e}'


def author_defaults():
    """作者の PC の既定値（server/defaults.author.json。server/defaults.js が読むものと同じ）。無ければ {}（一般の既定＝PATH・設定で指定）"""
    try:
        return json.loads((REPO / 'server' / 'defaults.author.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def defaults_js():
    """既定値（server/defaults.js）のうち、描く python と ffmpeg のフォルダ。値は server/defaults.author.json から（JS を動かさずに）。無ければ ('', [])"""
    a = author_defaults()
    return a.get('renderPython') or '', list(a.get('ffmpegDirs') or [])


def package():
    return json.loads((REPO / 'package.json').read_text(encoding='utf-8'))


def find_vscode():
    """(code のコマンド, Code.exe)。無ければ ''。install_vscode.py・tools/mittler.cmd と同じ場所を見る。"""
    local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'Programs' / 'Microsoft VS Code'
    cli = next((p for p in [local / 'bin' / 'code.cmd', Path(r'C:\Program Files\Microsoft VS Code\bin\code.cmd')] if p.is_file()), None)
    cli = str(cli) if cli else (shutil.which('code') or '')
    exe = local / 'Code.exe'
    return cli, (str(exe) if exe.is_file() else '')


def extensions():
    """VS Code に入っている拡張のフォルダの名前（VS Code を動かさずに、拡張の置き場を読む）。Remote-SSH の接続先の置き場も見る。"""
    found = []
    for base in (Path.home() / '.vscode' / 'extensions', Path.home() / '.vscode-server' / 'extensions'):
        if base.is_dir():
            found += [p for p in base.iterdir() if p.is_dir()]
    return found


def loader_target(ext_dir):
    """入っている拡張（入口だけ）が、どのリポジトリの extension.js を読むか。分からなければ ''。"""
    try:
        s = (ext_dir / 'loader.js').read_text(encoding='utf-8')
        m = re.search(r'require\((".*?")\)', s)
        return json.loads(m.group(1)) if m else ''
    except (OSError, ValueError):
        return ''


def probe_python(py):
    """その python で numpy・cv2・PIL が読めるか。(読めたか, {名前: 版}, 理由)"""
    code = ("import json,sys\nv={'python':sys.version.split()[0]}\n"
            "import numpy;v['numpy']=numpy.__version__\nimport cv2;v['opencv']=cv2.__version__\n"
            "import PIL;v['pillow']=PIL.__version__\nprint(json.dumps(v))")
    rc, out, err = run([py, '-c', code], timeout=90)
    if rc == 0:
        try:
            return True, json.loads(out.splitlines()[-1]), ''
        except (ValueError, IndexError):
            return False, {}, out[-200:]
    last = (err.splitlines() or ['起動できない'])[-1]
    return False, {}, last[-200:]


def find_blender(arg):
    """Blender（Blender の 3D）を探す：--blender → 環境変数 MITTLER_BLENDER → 既定（server/defaults.js の blenderPath）→ PATH。→ (場所, どこで)。無ければ ('', '')"""
    for p, origin in ((arg, 'arg'), (os.environ.get('MITTLER_BLENDER', ''), 'env'), (author_defaults().get('blenderPath') or '', 'default')):
        if p and os.path.isfile(p):
            return p, origin
    w = shutil.which('blender')
    return (w, 'path') if w else ('', '')


def wanted_versions():
    """requirements-engine.txt の版（目安）。{名前: 版}"""
    w = {}
    try:
        for line in REQ.read_text(encoding='utf-8').splitlines():
            m = re.match(r'\s*([A-Za-z0-9_.-]+)==([^\s#]+)', line)
            if m:
                w[m.group(1).lower()] = m.group(2)
    except OSError:
        pass
    return w


def find_render_python(arg_py, default_py):
    """描く python を探す。サーバー（server/pyrender.js）と同じ考え方：指定 → 既定（defaults.js）→ PATH。そのあと、この道具を動かしている python。
    → (見つけた python, どこで見つけたか, 版, 試したものの一覧)"""
    cands = []
    if arg_py:  # 指定されたら、それだけを確かめる（だめなら「だめ」と言う。黙ってほかのものに替えない）
        cands.append((arg_py, 'arg'))
    else:
        for name in ('MITTLER_PYTHON', 'CC_PYTHON'):  # CC_PYTHON は古い名前の互換
            if os.environ.get(name):
                cands.append((os.environ[name], 'env'))
        if default_py and Path(default_py).is_file():
            cands.append((default_py, 'default'))
        on_path = shutil.which('python')
        if on_path:
            cands.append((on_path, 'path'))
        cands.append((sys.executable, 'self'))
    tried, seen = [], set()
    for py, origin in cands:
        key = os.path.normcase(os.path.abspath(py)) if os.path.sep in py or '/' in py else py
        if key in seen:
            continue
        seen.add(key)
        ok, vers, why = probe_python(py)
        tried.append({'python': py, 'origin': origin, 'ok': ok, 'versions': vers, 'why': why})
        if ok:
            return py, origin, vers, tried
    return '', '', {}, tried


def find_ffmpeg(arg_dir, default_dirs):
    """(ffmpeg, ffprobe, フォルダ（PATH なら ''）, どこで見つけたか)"""
    dirs = []
    if arg_dir:
        dirs.append((arg_dir, 'arg'))
    for name in ('MITTLER_FFMPEG_DIR', 'CC_FFMPEG_DIR'):  # CC_FFMPEG_DIR は古い名前の互換
        if os.environ.get(name):
            dirs.append((os.environ[name], 'env'))
    dirs += [(d, 'default') for d in default_dirs]
    for d, origin in dirs:
        f, p = Path(d) / 'ffmpeg.exe', Path(d) / 'ffprobe.exe'
        if f.is_file() and p.is_file():
            return str(f), str(p), str(Path(d)), origin
    f, p = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if f and p:
        return f, p, '', 'path'
    return '', '', '', ''


def render_check(py, ffdir, work):
    """試しの作品を作って、静止画を1枚描く。(できたか, 説明, 作品のフォルダ)"""
    proj = Path(work) / 'mittler-setup-check'
    (proj / 'effects').mkdir(parents=True, exist_ok=True)
    (proj / 'out').mkdir(exist_ok=True)
    tl = json.loads((REPO / 'templates' / 'project' / 'project.cut.json').read_text(encoding='utf-8'))
    tl.update(name='初期設定の確かめ', width=640, height=360, duration=2)
    sub = next(t for t in tl['tracks'] if t['kind'] == 'subtitle')
    sub['clips'] = [{'id': 'sub_check', 'start': 0, 'dur': 2, 'text': 'Mittler OK'}]
    (proj / 'mittler-setup-check.cut.json').write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (proj / 'characters.json').write_text((REPO / 'templates' / 'project' / 'characters.json').read_text(encoding='utf-8'), encoding='utf-8')
    for f in (REPO / 'effects_lib' / 'common').glob('*.py'):
        shutil.copyfile(f, proj / 'effects' / f.name)
    env = dict(os.environ)
    if ffdir:
        env['PATH'] = ffdir + os.pathsep + env.get('PATH', '')
    rc, out, err = run([py, '-X', 'utf8', '-B', '-m', 'mittler', 'stills', proj / 'mittler-setup-check.cut.json', '--at', '1', '--out', proj / 'out'],
                       timeout=240, cwd=str(REPO / 'pyengine'), env=env)
    pngs = sorted((proj / 'out').glob('still_*.png'))
    if rc == 0 and pngs and pngs[0].stat().st_size > 1000:
        return True, f'{pngs[0].name}（{pngs[0].stat().st_size} バイト）', proj
    last = ((err or out).splitlines() or ['出力なし'])[-1]
    return False, f'終わりの番号 {rc}：{last[-300:]}', proj


def main(argv=None):
    ap = argparse.ArgumentParser(prog='mittler_setup', description='Mittler の初期設定の確かめ（付けなければ何も変えない）')
    ap.add_argument('--check', action='store_true', help='確かめるだけ（既定）')
    ap.add_argument('--json', action='store_true', help='結果を JSON で出す')
    ap.add_argument('--python', default='', help='描く python（numpy・opencv・Pillow の入ったもの）')
    ap.add_argument('--ffmpeg-dir', default='', help='ffmpeg.exe・ffprobe.exe のあるフォルダ')
    ap.add_argument('--no-render', action='store_true', help='試しの1枚を描かない')
    ap.add_argument('--blender', default='', help='Blender の 3D で使う blender.exe（確かめるだけ）')
    ap.add_argument('--work', default='', help='試しの作品を作るフォルダ（残す）')
    ap.add_argument('--install-venv', default='', metavar='DIR', help='描画用の venv を作ってパッケージを入れる')
    ap.add_argument('--with-3d', action='store_true', help='--install-venv のとき、GPU の 3D（moderngl・glcontext）も入れる')
    ap.add_argument('--install-extension', action='store_true', help='VS Code に Mittler を入れる')
    ap.add_argument('--install-skill', action='store_true', help='Claude Code のスキルを入れる')
    ap.add_argument('--dry-run', action='store_true', help='--install-* が流すものを見せるだけ')
    a = ap.parse_args(argv)
    say = (lambda *x: None) if a.json else (lambda *x: print(*x, flush=True))
    items, actions = [], []

    def item(key, level, title, detail='', fix=None):
        items.append({'id': key, 'level': level, 'title': title, 'detail': detail, 'fix': fix or []})

    def act(title, cmd):
        """--install-* の1手。--dry-run なら流さない。"""
        line = subprocess.list2cmdline([str(c) for c in cmd])
        if a.dry_run:
            actions.append({'title': title, 'command': line, 'ran': False}); say(f'[dry-run] {title}\n    {line}')
            return True
        say(f'… {title}\n    {line}')
        rc, out, err = run(cmd, timeout=1800)
        actions.append({'title': title, 'command': line, 'ran': True, 'returncode': rc, 'tail': (err or out)[-400:]})
        if rc != 0:
            say(f'    失敗（終わりの番号 {rc}）：{(err or out)[-400:]}')
        return rc == 0

    pkg = package()
    ext_id = f"{pkg['publisher']}.{pkg['name']}"
    default_py, default_ff = defaults_js()
    item('repo', INFO, f"Mittler {pkg.get('version', '?')}（{'配布版' if PACKAGED else '開発版'}）", str(REPO))

    # --- 入れる（明示のときだけ）。確かめの前に済ませて、下の確かめに映す ---
    arg_py = a.python
    if a.install_venv:
        vdir = Path(a.install_venv).resolve()
        vpy = vdir / 'Scripts' / 'python.exe'
        ok = True
        if not vpy.is_file():
            ok = act(f'描画用の venv を作る：{vdir}', [sys.executable, '-m', 'venv', vdir])
        if ok:
            ok = act('描画のパッケージを入れる（numpy・opencv・Pillow・onnxruntime）', [vpy, '-m', 'pip', 'install', '-r', REQ])
        if ok and a.with_3d:
            ok = act('GPU の 3D のパッケージを入れる（moderngl・glcontext）', [vpy, '-m', 'pip', 'install', '--only-binary=:all:', '-r', REQ_3D])
        if ok and not a.dry_run and not arg_py:
            arg_py = str(vpy)
    if a.install_extension:
        if PACKAGED:  # 配布版の中から動かしている：拡張はもう入っている（入れ直すなら VSIX から。docs/インストールガイド.md の 2）
            actions.append({'title': 'VS Code に Mittler を入れる', 'command': '', 'ran': False, 'note': '配布版の拡張から動いているので入れない'})
        else:
            act('VS Code に Mittler を入れる', [sys.executable, REPO / 'tools' / 'install_vscode.py'])
    if a.install_skill:
        dst = Path.home() / '.claude' / 'skills'
        for s in sorted(p for p in (REPO / 'skills').iterdir() if p.is_dir()):
            line = f'{s} -> {dst / s.name}'
            if a.dry_run:
                actions.append({'title': 'スキルを写す', 'command': line, 'ran': False}); say(f'[dry-run] スキルを写す\n    {line}')
            else:
                shutil.copytree(s, dst / s.name, dirs_exist_ok=True)
                (dst / s.name / 'mittler_dir.txt').write_text(str(REPO) + '\n', encoding='utf-8')  # スキルが Mittler の場所を知るため（SKILL.md の 1）
                actions.append({'title': 'スキルを写す', 'command': line, 'ran': True, 'returncode': 0}); say(f'… スキルを写した\n    {line}')

    # --- 確かめ ---
    cli, exe = find_vscode()
    if cli or exe:
        item('vscode', OK, 'VS Code', cli or exe)
        if not exe:
            item('vscode_node', WARN, 'VS Code がユーザー単位の場所に無い', r'tools\mittler.cmd（VS Code の中の Node で動かす道具）は %LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe を使う',
                 [r'道具（tools\mittler.cmd）を使うなら、VS Code をユーザー単位で入れるか、Node を入れて node で動かす（編集画面には関係ない）'])
    else:
        item('vscode', MISSING, 'VS Code が見つからない', '', ['winget install Microsoft.VisualStudioCode --scope user'])

    rc, out, _ = run(['git', '--version'], timeout=20)
    if rc == 0:
        item('git', OK, 'Git', out)
    else:
        item('git', WARN, 'Git が見つからない', '新しい作品の最初のコミット・直しを戻すのに使う（無くても作品は作れる）', ['winget install Git.Git --scope user'])

    ff, fp, ffdir, ff_origin = find_ffmpeg(a.ffmpeg_dir, default_ff)
    if ff:
        rc, out, _ = run([ff, '-version'], timeout=20)
        ver = (out.splitlines() or [''])[0][:80]
        where = {'arg': '--ffmpeg-dir', 'env': '環境変数', 'default': '既定の場所（設定は要らない）', 'path': 'PATH（設定は要らない）'}[ff_origin]
        item('ffmpeg', OK, 'ffmpeg・ffprobe', f'{ff}（{where}）{ver}')
        rc, out, _ = run([ff, '-hide_banner', '-filters'], timeout=30)
        if rc == 0 and not re.search(r'\bass\b', out):
            item('ffmpeg_ass', WARN, 'この ffmpeg には libass が無い', 'ASS の字幕（settings.subtitle.renderer = "ass"）は焼けない。ふつうの字幕は出る', ['full build の ffmpeg を入れる'])
    else:
        item('ffmpeg', MISSING, 'ffmpeg・ffprobe が見つからない', '書き出し・サムネ・波形・動画の読み込みに使う',
             ['winget install Gyan.FFmpeg --scope user', '入れたあと、新しいターミナルで ffmpeg -version が動くこと（PATH）。別の場所なら設定 mittler.render.ffmpegDir'])

    py, py_origin, vers, tried = find_render_python(arg_py, default_py)
    want = wanted_versions()
    if py:
        where = {'arg': '指定した python', 'env': '環境変数', 'default': '既定の場所（設定は要らない）', 'path': 'PATH の python（設定は要らない）', 'self': 'この道具を動かしている python'}[py_origin]
        v = '・'.join(f'{k} {vers[k]}' for k in ('python', 'numpy', 'opencv', 'pillow') if k in vers)
        item('render_python', OK, '描く python（numpy・opencv・Pillow）', f'{py}（{where}）{v}')
        diff = [f"{k} {vers.get(k)}（目安 {want[n]}）" for k, n in (('numpy', 'numpy'), ('opencv', 'opencv-python-headless'), ('pillow', 'pillow'))
                if n in want and vers.get(k) and not str(vers[k]).startswith(want[n].rsplit('.', 1)[0])]
        if diff:
            item('render_versions', INFO, 'パッケージの版が目安と違う（動けばそのままでよい）', '、'.join(diff))
    else:
        why = '／'.join(f"{t['python']}：{t['why']}" for t in tried)[:500]
        item('render_python', MISSING, '描ける python が見つからない（numpy・opencv・Pillow が入ったもの）', why,
             ['VS Code のコマンド「Mittler: 初期設定」の「描く python を入れる」（拡張の保存場所に venv を作って入れ、設定 mittler.render.python も書く）',
              f'python {Path("setup") / "mittler_setup.py"} --install-venv <venv を作るフォルダ>   （venv を作ってパッケージを入れる）',
              'または、今ある python に：python -m pip install -r setup\\requirements-engine.txt',
              'そのあと、この道具に --python <その python> を付けて確かめる'])

    exts = extensions()
    mine = [p for p in exts if p.name.lower().startswith(ext_id.lower() + '-')]
    old = [p for p in exts if p.name.lower().startswith(OLD_EXT + '-')]
    install_cmd = f'python {Path("tools") / "install_vscode.py"}'
    if mine:
        target = loader_target(mine[-1])
        here = str(REPO / 'extension.js')
        if target and os.path.normcase(target) != os.path.normcase(here):
            item('extension', WARN, 'Mittler の拡張は入っているが、別の場所のリポジトリを読んでいる', f'{target}（このリポジトリは {here}）', [install_cmd + '   （このリポジトリを読むように入れ直す）'])
        else:
            item('extension', OK, 'Mittler の拡張', mine[-1].name)
    elif PACKAGED:
        item('extension', MISSING, 'Mittler の拡張が VS Code に入っていない', f'拡張の ID：{ext_id}',
             ['code --install-extension <mittler-<版>.vsix>   （VS Code の「拡張機能」→「…」→「VSIX からのインストール…」でも同じ。docs/インストールガイド.md の 2）'])
    else:
        item('extension', MISSING, 'Mittler の拡張が VS Code に入っていない', f'拡張の ID：{ext_id}',
             [install_cmd + '   （または python setup\\mittler_setup.py --install-extension）', 'そのあと VS Code で「ウィンドウの再読み込み」'])
    if old:
        item('old_extension', WARN, f'前の名前の拡張 {OLD_EXT} が入ったまま', '2つの拡張が *.cut.json を取り合う', [install_cmd + ' --uninstall-old'])

    skills = Path.home() / '.claude' / 'skills'
    names = [p.name for p in (REPO / 'skills').iterdir() if p.is_dir()]
    lacking = [n for n in names if not (skills / n / 'SKILL.md').is_file()]
    if not lacking:
        item('skill', OK, 'Claude Code のスキル', '、'.join(names))
    else:
        item('skill', INFO, 'Claude Code のスキルが入っていない（Claude Code を使うなら）', '、'.join(lacking),
             ['python setup\\mittler_setup.py --install-skill   （skills\\ の中身を ~/.claude/skills/ に写す）'])
    if (skills / OLD_SKILL).is_dir():
        item('old_skill', INFO, f'前の名前のスキル {OLD_SKILL} が残っている', '動くが、名前が2つ出る', [f'{skills / OLD_SKILL} を手で消す'])

    if a.no_render:
        item('render', INFO, '試しの1枚は描いていない（--no-render）')
    elif not py:
        item('render', MISSING, '試しの1枚を描けない', '描ける python が無い')
    else:
        tmp = None
        work = a.work
        if not work:
            tmp = tempfile.mkdtemp(prefix='mittler_setup_')
            work = tmp
        try:
            ok, detail, proj = render_check(py, ffdir, work)
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
        if ok:
            item('render', OK, '試しの作品で静止画を1枚描けた', detail + (f'（{proj}）' if a.work else ''))
        else:
            item('render', MISSING, '試しの1枚が描けなかった', detail, ['上の「描く python」「ffmpeg」を直してから、もう一度'])

    # --- 3D（なくてもよい。3D のエフェクトを使う作品だけ。2026-11-13）：moderngl（GPU の 3D）と Blender（Blender の 3D）。入れはしない ---
    bl, bl_origin = find_blender(a.blender)
    if py:
        rc, out, err = run([py, '-c', 'import moderngl,glcontext;print(moderngl.__version__)'], timeout=60)
        if rc == 0:
            item('gl3d', OK, '3D のエフェクト（GPU の 3D・moderngl）', f'moderngl {out.splitlines()[-1] if out else "?"}')
        else:
            item('gl3d', INFO, '3D のエフェクト（gl_*）を使うなら：描く python に moderngl が無い', '3D を使わない作品には要らない',
                 [f'{py} -m pip install --only-binary=:all: -r setup\\requirements-3d.txt   （3D を使うときだけ。docs/インストールガイド.md の 14）'])
    if py:  # HTML のレイヤー（なくてもよい。2026-11-18）：描く python の Playwright と、ヘッドレスの Chromium が起動できるか
        env = dict(os.environ)  # Chromium の置き場：環境変数 → 作者の PC の既定（playwrightBrowsers。あれば。htmllayer.py と同じ）
        bp = author_defaults().get('playwrightBrowsers') or ''
        if bp and os.path.isdir(bp) and not env.get('PLAYWRIGHT_BROWSERS_PATH'):
            env['PLAYWRIGHT_BROWSERS_PATH'] = bp
        # Chromium は自分の注意の行を、作業フォルダ（ここを流したフォルダ。リポジトリの根など）の debug.log に書くことがある → 致命的なものだけにして、書くなら一時フォルダへ（pyengine/mittler/htmllayer.py と同じ）
        chromium_log = os.path.join(tempfile.gettempdir(), 'mittler_chromium.log')
        rc, out, err = run([py, '-c', 'import sys\nfrom playwright.sync_api import sync_playwright\nwith sync_playwright() as p:\n b = p.chromium.launch(args=["--log-level=3", "--log-file=" + sys.argv[1]]); print(b.version); b.close()', chromium_log],
                           timeout=120, env=env, cwd=tempfile.gettempdir())
        if rc == 0:
            item('html', OK, 'HTML のレイヤー（Playwright・Chromium）', f'Chromium {out.splitlines()[-1] if out else "?"}')
        else:
            item('html', INFO, 'HTML のレイヤー（html）を使うなら：描く python で Playwright の Chromium が起動しない', 'HTML のレイヤーを使わない作品には要らない',
                 [f'{py} -m pip install playwright', f'{py} -m playwright install chromium-headless-shell   （docs/インストールガイド.md の 16）'])
    if bl:
        rc, out, _ = run([bl, '-b', '--factory-startup', '--version'], timeout=120)
        ver = next((ln.strip() for ln in out.splitlines() if ln.strip().startswith('Blender')), '')
        where = {'arg': '--blender', 'env': '環境変数 MITTLER_BLENDER', 'default': '既定の場所（設定は要らない）', 'path': 'PATH（設定は要らない）'}[bl_origin]
        if rc == 0 and ver:
            item('blender', OK, 'Blender の 3D（Blender）', f'{bl}（{where}）{ver}')
        else:
            item('blender', WARN, 'Blender が動かない', f'{bl}：{(out or "")[-200:]}', ['blender.org の公式の zip（LTS）を置き直す'])
    else:
        item('blender', INFO, 'Blender の 3D（blender3d）を使うなら：Blender が見つからない', '3D を使わない作品には要らない',
             ['blender.org の公式の zip（LTS。インストーラーでなくポータブル版）を置いて、公式の SHA-256 と照らす（docs/インストールガイド.md の 14）',
              'VS Code の設定 mittler.blender.path に blender.exe の場所を書く'])

    # --- 設定に書く値（書きかえない。見せるだけ）---
    settings = {}
    if bl and bl_origin in ('arg', 'env'):
        settings['mittler.blender.path'] = bl
    if py and py_origin in ('arg', 'env', 'self'):
        settings['mittler.render.python'] = py
    if ff and ff_origin in ('arg', 'env'):
        settings['mittler.render.ffmpegDir'] = ffdir
    # 好みで書く設定（見せるだけ。settings と違って「書くべき値」ではない。ユーザーが選んだときだけ書く）：画面の言葉（既定は英語）
    hints = {'mittler.language': {'value': 'ja', 'note': '編集画面を日本語にするなら（既定は英語。編集画面の上のバーの右端の「日本語」を押しても同じ）'}}
    missing = [i for i in items if i['level'] == MISSING]
    result = {'ok': not missing, 'repo': str(REPO), 'version': pkg.get('version'), 'kind': 'vsix' if PACKAGED else 'dev',
              'render_python': py, 'render_python_origin': py_origin, 'items': items, 'settings': settings, 'hints': hints, 'actions': actions,
              'next': [f for i in items if i['level'] in (MISSING, WARN) for f in i['fix']]}
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result['ok'] else 1

    say('')
    say('==== Mittler の初期設定の確かめ ====')
    for i in items:
        say(f"{MARK[i['level']]} {i['title']}" + (f"：{i['detail']}" if i['detail'] else ''))
        for f in i['fix']:
            say(f'         → {f}')
    say('')
    if settings:
        say('VS Code の設定（settings.json。その PC だけ）に書く：')
        for k, v in settings.items():
            say(f'  {json.dumps(k)}: {json.dumps(v)},')
        say('  （書いたら VS Code で「ウィンドウの再読み込み」。この道具は設定を書きかえない）')
    else:
        say('VS Code の設定：書くものは無い（既定の場所か PATH で見つかった、または足りないものがある）。')
    for k, h in hints.items():  # 好みの設定（書かない。見せるだけ）
        say(f'好みで：{h["note"]}：{json.dumps(k)}: {json.dumps(h["value"])}')
    say('')
    if missing:
        say(f'足りないものが {len(missing)} つある。上の → を済ませてから、もう一度流す。')
    else:
        say('足りないものは無い。*.cut.json を VS Code で開けば編集画面が出る（新しい作品は、編集画面の「＋ 新規」か、コマンド「Mittler: 新しい作品を作る」）。')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
