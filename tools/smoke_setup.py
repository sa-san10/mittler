"""初期設定の確かめ（setup/mittler_setup.py）の確かめ。ブラウザもサーバーも要らない。
  <描画の python> -X utf8 tools/smoke_setup.py [--work <フォルダ>]（--work：試しのものを残す場所。無ければ一時フォルダに作って消す）
描画の python（numpy・opencv・Pillow）で流すと、試しの1枚を描くところまで確かめる。ほかの python なら、描くところは飛ばす。
本物のホーム・本物の VS Code・本物の venv には触らない：ホームは環境変数 USERPROFILE を一時フォルダに向けた偽物、
入れる道（--install-venv・--install-extension）は --dry-run でだけ流す。
確かめること：
1. --json の形（項目の id・level・ok と終わりの番号が合う）、何も付けないときの人向けの出力
2. 試しの作品で静止画を1枚描ける（--python・--work）。指定した python のときは、設定に書く値 mittler.render.python を見せる
3. 無い python を指定すると「足りない」になり、黙ってほかの python に替えない
4. --install-venv・--install-extension・--install-skill は --dry-run では何も作らない・何も入れない（流すコマンドだけ見せる）
5. 偽のホームで：--install-skill が skills/ を写す、拡張の置き場の読み方（入っている／別のリポジトリを読んでいる／前の名前の拡張が残っている）
6. 見せる設定の名前が package.json にある、server/defaults.js の既定値を読めている、リポジトリの中に何も作らない
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CC = Path(__file__).resolve().parent.parent
SETUP = CC / 'setup' / 'mittler_setup.py'
fails = []


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


def setup(*args, home=None, timeout=400):
    env = dict(os.environ)
    for k in ('MITTLER_PYTHON', 'CC_PYTHON', 'MITTLER_FFMPEG_DIR', 'CC_FFMPEG_DIR'):
        env.pop(k, None)
    if home:
        env['USERPROFILE'] = str(home)
        env['HOME'] = str(home)
    r = subprocess.run([sys.executable, '-X', 'utf8', str(SETUP), *[str(x) for x in args]], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=timeout, env=env, cwd=str(CC))
    return r.returncode, r.stdout, r.stderr


def setup_json(*args, home=None):
    rc, out, err = setup(*args, '--json', home=home)
    try:
        return rc, json.loads(out)
    except ValueError:
        return rc, {'_bad': out[-300:] + err[-300:], 'items': []}


def by_id(res):
    return {i['id']: i for i in res.get('items', [])}


def tree(p):
    return sorted(str(x.relative_to(p)) for x in Path(p).rglob('*')) if Path(p).exists() else []


def main():
    args = sys.argv[1:]
    keep = args[args.index('--work') + 1] if '--work' in args else ''
    ctx = None
    if keep:
        work = Path(keep).resolve(); work.mkdir(parents=True, exist_ok=True)
    else:
        ctx = tempfile.TemporaryDirectory(prefix='smoke_setup_'); work = Path(ctx.name)
    try:
        before = subprocess.run(['git', '-C', str(CC), 'status', '--porcelain', '--', 'setup', 'tools', 'skills'], capture_output=True, text=True).stdout
        can_draw = subprocess.run([sys.executable, '-c', 'import numpy, cv2, PIL'], capture_output=True).returncode == 0
        home = work / 'home'; home.mkdir(exist_ok=True)

        # 1. 形
        rc, res = setup_json('--no-render', home=home)
        ids = by_id(res)
        need = ['repo', 'vscode', 'git', 'ffmpeg', 'render_python', 'extension', 'skill', 'render']
        check(all(k in ids for k in need), f'--json に項目が全部ある（{[k for k in need if k not in ids] or "全部"}）')
        check(all(i['level'] in ('ok', 'warn', 'missing', 'info') and isinstance(i['fix'], list) for i in res['items']), '--json の level・fix の形')
        miss = [i['id'] for i in res['items'] if i['level'] == 'missing']
        check(res.get('ok') == (not miss) and rc == (1 if miss else 0), f'ok と終わりの番号が「足りないもの」と合う（足りない：{miss}・番号 {rc}）')
        check(ids.get('extension', {}).get('level') == 'missing' and ids.get('skill', {}).get('level') == 'info', '空の偽のホームでは、拡張は「足りない」・スキルは「入っていない」')
        check(ids.get('render', {}).get('level') == 'info', '--no-render なら描かない')
        rc2, out, err = setup('--no-render', home=home)
        check(rc2 == rc and '==== Mittler の初期設定の確かめ ====' in out and '[不足]' in out and '→' in out, '人向けの出力（見出し・不足・次にやること）')
        rc3, out3, _ = setup('--check', '--no-render', home=home)
        check(out3 == out, '--check は、何も付けないときと同じ')

        # 2. 描く
        if can_draw:
            rc, res = setup_json('--python', sys.executable, '--work', work / 'w', home=home)
            ids = by_id(res)
            png = list((work / 'w' / 'mittler-setup-check' / 'out').glob('still_*.png'))
            check(ids.get('render_python', {}).get('level') == 'ok' and ids.get('render', {}).get('level') == 'ok' and len(png) == 1 and png[0].stat().st_size > 1000,
                  f"試しの作品で静止画を1枚描けた（{ids.get('render', {}).get('detail', '')[:60]}）")
            check(res.get('settings', {}).get('mittler.render.python') == sys.executable, '指定した python のときは、設定に書く値を見せる')
            rc, res = setup_json('--python', sys.executable, home=home)
            check(by_id(res).get('render', {}).get('level') == 'ok' and not [p for p in Path(tempfile.gettempdir()).glob('mittler_setup_*')],
                  '--work なしでも描けて、一時フォルダを残さない')
        else:
            print('SKIP この python には numpy・opencv・Pillow が無いので、描くところは飛ばす（描画の python で流す）', flush=True)

        # 3. 無い python
        rc, res = setup_json('--python', work / 'no_such' / 'python.exe', '--no-render', home=home)
        ids = by_id(res)
        check(rc == 1 and ids.get('render_python', {}).get('level') == 'missing' and not res.get('settings'), '無い python を指定すると「足りない」（ほかの python に替えない）')

        # 4. dry-run
        venv = work / 'venv_dry'
        h0 = tree(home)
        rc, res = setup_json('--install-venv', venv, '--install-extension', '--install-skill', '--dry-run', '--no-render', home=home)
        acts = res.get('actions', [])
        cmds = ' | '.join(a['command'] for a in acts)
        check(len(acts) >= 3 and all(a['ran'] is False for a in acts), f'--dry-run は流さない（{len(acts)} 手）')
        check('-m venv' in cmds and 'pip install -r' in cmds and 'requirements-engine.txt' in cmds and 'install_vscode.py' in cmds and 'mittler-new-project' in cmds,
              '--dry-run が、venv・pip・install_vscode.py・スキルの写しを見せる')
        check(not venv.exists() and tree(home) == h0, '--dry-run は venv も、ホームの中も作らない')

        # 5. 偽のホーム
        rc, res = setup_json('--install-skill', '--no-render', home=home)
        check((home / '.claude' / 'skills' / 'mittler-new-project' / 'SKILL.md').is_file() and by_id(res).get('skill', {}).get('level') == 'ok',
              '--install-skill が skills/ を偽のホームに写し、確かめが「入っている」になる')
        where = home / '.claude' / 'skills' / 'mittler-new-project' / 'mittler_dir.txt'
        check(where.is_file() and Path(where.read_text(encoding='utf-8').strip()) == CC, 'スキルの隣に Mittler の場所（mittler_dir.txt）を書く')
        pkg = json.loads((CC / 'package.json').read_text(encoding='utf-8'))
        ext = home / '.vscode' / 'extensions' / f"{pkg['publisher']}.{pkg['name']}-{pkg['version']}"
        ext.mkdir(parents=True, exist_ok=True)
        (ext / 'loader.js').write_text(f"module.exports = require({json.dumps(str(CC / 'extension.js'))});\n", encoding='utf-8')
        rc, res = setup_json('--no-render', home=home)
        check(by_id(res).get('extension', {}).get('level') == 'ok' and 'old_extension' not in by_id(res), '拡張がこのリポジトリを読んでいれば「入っている」')
        (ext / 'loader.js').write_text(f"module.exports = require({json.dumps(str(work / 'elsewhere' / 'extension.js'))});\n", encoding='utf-8')
        (home / '.vscode' / 'extensions' / 'sa-san10.claude-cut-0.1.0').mkdir(exist_ok=True)
        (home / '.claude' / 'skills' / 'claude-cut-new-project').mkdir(exist_ok=True)
        rc, res = setup_json('--no-render', home=home)
        ids = by_id(res)
        check(ids.get('extension', {}).get('level') == 'warn', '拡張が別の場所のリポジトリを読んでいれば「注意」')
        check(ids.get('old_extension', {}).get('level') == 'warn' and any('--uninstall-old' in f for f in ids['old_extension']['fix']), '前の名前の拡張が残っていれば知らせて、外し方を見せる')
        check('old_skill' in ids, '前の名前のスキルが残っていれば知らせる')

        # 6. 名前・既定値・リポジトリを汚さない
        props = pkg['contributes']['configuration']['properties']
        check('mittler.render.python' in props and 'mittler.render.ffmpegDir' in props, '見せる設定の名前（mittler.render.python・ffmpegDir）が package.json にある')
        sys.path.insert(0, str(CC / 'setup'))
        import mittler_setup
        dpy, dff = mittler_setup.defaults_js()
        # server/defaults.js の値（Node で読む。作者の PC の値は server/defaults.author.json から。無ければ空＝PATH）と同じこと
        nd = shutil.which('node')
        r = subprocess.run(([nd] if nd else ['cmd', '/c', str(CC / 'tools' / 'mittler.cmd'), 'node']) +
                           ['-e', 'const d = require(process.argv[1]); process.stdout.write(JSON.stringify([d.renderPython, d.ffmpegDirs]))', str(CC / 'server' / 'defaults.js')],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
        js = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
        check(js == [dpy, dff], f'server/defaults.js の既定値（描く python・ffmpeg のフォルダ）を同じに読めている（{dpy or "空"}・{dff or "空"}）')
        after = subprocess.run(['git', '-C', str(CC), 'status', '--porcelain', '--', 'setup', 'tools', 'skills'], capture_output=True, text=True).stdout
        check(before == after, 'リポジトリの中（setup・tools・skills）に何も作らない')
    finally:
        if ctx:
            ctx.cleanup()
    print(f'smoke_setup: {"FAIL " + str(len(fails)) if fails else "OK"}')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
