"""古い名前（claude-cut）の互換の確かめ（2026-11-12 に Mittler に改名。ブラウザは要らない。描画の python（numpy・opencv・Pillow）で流す）。
  <描画の python> -X utf8 tools/smoke_compat.py [--work <フォルダ>]（--work：試しの作品を残す場所。無ければ一時フォルダに作って消す）
サーバーを2回立てる（127.0.0.1 だけ。空いているポート。終わったら /api/quit で止める）。Windows の tools\\cc.cmd・tools\\mittler.cmd（VS Code の Node）を使う。
確かめること：
1. 名前の1か所（server/names.js と pyengine/mittler/names.py）：環境変数 MITTLER_*／CC_*（両方あれば新しいほう）・状態フォルダの決まり（JS と Python が同じ答え）・
   トークンのヘッダ・VS Code の設定 mittler.*／claudeCut.*（extension.js の settingsNow を、vscode の代わりの偽物で。両方あれば新しいほう）
2. Python のパッケージ ccpy：mittler と同じモジュールそのもの、python -m ccpy stills と python -m mittler stills が同じ PNG
3. 古い名前だけの作品（.claude-cut/・.gitignore は .claude-cut だけ・フックは tools/cc_state.py・エフェクトは ccpy を import して CC_ROOT を読む）：
   tools\\cc.cmd serve＋環境変数 CC_NO_REVEAL・CC_PRESETS で立てる → 状態は .claude-cut/ のまま（.mittler/ を作らない）・古いヘッダ X-CC-Token で書ける・
   新しいヘッダでも書ける・両方あれば新しいほう・状態フォルダは配らない・📷 の PNG がエンジンの静止画と同じ・フック cc_state.py と tools/cc_api.py が動く
4. 新しい名前だけの作品（new_project で作ったまま＋ mittler を import するエフェクト）：tools\\mittler.cmd serve で .mittler/ を使う・フック mittler_state.py・
   tools/mittler_api.py・環境変数は MITTLER_PRESETS が CC_PRESETS に勝つ・📷 の PNG が 3 と同じ
5. 道具の環境変数（tools/h3_jobs.py の MYDRIVE・H3_ROOT、tools/gen/codex_image.py の CODEX_MODEL、pyengine/mittler/enhance.py の ESRGAN）・fix_hooks.py（古いフックを見つける）
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
sys.path.insert(0, str(ROOT / 'pyengine'))
fails = []


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


def node(script, *args):
    """JS のファイルを流す：PATH の node、無ければ tools\\mittler.cmd node（VS Code に入っている Node）"""
    n = shutil.which('node')
    cmd = [n] if n else ['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node']
    r = subprocess.run(cmd + [str(script), *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    if r.returncode:
        raise SystemExit('node 失敗: ' + r.stdout + r.stderr)
    return r.stdout


def run_py(args, env=None, cwd=None, timeout=300):
    e = {k: v for k, v in os.environ.items() if not k.startswith(('CC_', 'MITTLER_'))}
    e.update(env or {})
    return subprocess.run([PY, '-X', 'utf8', '-B', *map(str, args)], capture_output=True, text=True, encoding='utf-8', errors='replace', env=e, cwd=cwd, timeout=timeout)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close()
    return p


class Server:
    """tools\\<launcher> serve <タイムライン>（描く python はこの python）。止めるのは /api/quit"""

    def __init__(self, launcher, tl, env, quit_header):
        e = {k: v for k, v in os.environ.items() if not k.startswith(('CC_', 'MITTLER_'))}
        e.update(env)
        self.err = tempfile.TemporaryFile()
        self.p = subprocess.Popen(['cmd', '/c', str(ROOT / 'tools' / launcher), 'serve', str(tl), '--port', str(free_port()), '--render-python', PY],
                                  stdout=subprocess.PIPE, stderr=self.err, env=e, text=True, encoding='utf-8', errors='replace')
        self.url = self.p.stdout.readline().strip()
        if not self.url.startswith('http://127.0.0.1:'):
            raise SystemExit(f'サーバーが起動しない（{launcher}）: {self.url}')
        self.token = re.search(r'token=(\w+)', self.url).group(1)
        self.base = self.url.split('/editor/')[0]
        self.quit_header = quit_header

    def call(self, path, body=None, headers=None, method=None):
        """→ (HTTP の番号, 中身の bytes)"""
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode('utf-8'),
                                     method=method or ('POST' if body is not None else 'GET'), headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def ready(self, header):
        for _ in range(240):
            st = json.loads(self.call('/api/status', headers={header: self.token})[1])
            if st.get('ready') or st.get('error'):
                return st
            time.sleep(0.5)
        return st

    def quit(self):
        code = self.call('/api/quit', body={}, headers={self.quit_header: self.token})[0]
        try:
            self.p.wait(timeout=45)
        except subprocess.TimeoutExpired:
            print('サーバーが止まらない pid', self.p.pid)
        self.err.close()
        return code


def make_work(d, pkg, root_env, old):
    """試しの作品：画像1枚・字幕・重ね絵・フェード・色・部品を import するエフェクト。old なら古い名前の作品の形にする"""
    from PIL import Image, ImageDraw
    # 引数は少なく（tools\mittler.cmd が node に渡すのは 8 個まで）。大きさは下でタイムラインに入れる
    r = subprocess.run(['cmd', '/c', str(ROOT / 'tools' / ('cc.cmd' if old else 'mittler.cmd')), 'node', str(ROOT / 'tools' / 'new_project.js'), str(d),
                        '--duration', '4', '--no-git'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    if r.returncode:
        raise SystemExit('new_project 失敗: ' + r.stdout + r.stderr)
    im = Image.new('RGB', (640, 360)); dr = ImageDraw.Draw(im)
    for i in range(8):
        dr.rectangle((i * 80, 0, i * 80 + 79, 359), fill=(i * 36 % 256, 255 - i * 30, (i * 97) % 256))
    dr.ellipse((200, 80, 440, 280), fill=(250, 250, 250))
    im.save(d / 'assets' / 'images' / 'bars.png')
    lg = Image.new('RGBA', (80, 48), (0, 0, 0, 0)); ImageDraw.Draw(lg).ellipse((2, 2, 78, 46), fill=(255, 80, 160, 220), outline=(255, 255, 255, 255), width=3)
    lg.save(d / 'assets' / 'overlays' / 'logo.png')
    (d / 'effects' / 'usepkg.py').write_text(f'''"""試し：エンジンの部品（{pkg}）を import して、素材の根を環境変数 {root_env} から読むエフェクト"""
import os
from pathlib import Path

import numpy as np

from {pkg}.helpers import smooth
from {pkg}.lib import look

STAGE = 'post'
META = {{'label': '試し', 'window': {{'clip': True}}, 'params': {{}}}}


def apply(ctx, f, clip):
    assert Path(os.environ['{root_env}']) == ctx.root
    k = smooth((ctx.t - clip['start']) / clip['dur'])
    return np.clip(look.vignette(np.asarray(f, np.float32), amt=0.6 * k), 0, 255).astype(np.uint8)
''', encoding='utf-8', newline='\n')
    tlf = d / f'{d.name}.cut.json'
    tl = json.loads(tlf.read_text(encoding='utf-8'))
    tl.update(width=320, height=180, fps=30)
    assert tl['format'] == 'mittler/py1' and tl['engine'] == 'mittler', '新しく作る作品は新しい名前の format・engine'
    if old:  # 改名の前に作った作品は、前の名前の format・engine のまま（同じ形として開く）
        tl.update(format='claude-cut/py1', engine='ccpy')
    tr = {t['id']: t for t in tl['tracks']}
    tr['t_sub_0']['clips'] = [{'id': 'sub_1', 'type': 'subtitle', 'start': 0.5, 'dur': 3, 'text': '互換の確かめ', 'style': {'size': 28}}]
    tr['t_video_0']['clips'] = [{'id': 'i_1', 'type': 'image', 'start': 0, 'dur': 4, 'src': 'assets/images/bars.png', 'camera': [[0, 1.0, 0.5, 0.5], [4, 1.3, 0.6, 0.4]], 'grade': {'s': 1.2}}]
    tl['tracks'].insert(1, {'id': 't_fx_0', 'name': 'エフェクト', 'kind': 'effect', 'clips': [
        {'id': 'fx_fade', 'type': 'effect', 'effect': 'fade', 'start': 0, 'dur': 4, 'params': {'fade_in': 1.0, 'fade_out': 1.0}},
        {'id': 'fx_sprite', 'type': 'effect', 'effect': 'sprite', 'start': 1, 'dur': 2, 'params': {'img': 'assets/overlays/logo.png', 'x': 240, 'y': 50, 't0': 1, 't1': 3, 'anim': 'pop', 'scale': 1}},
        {'id': 'fx_use', 'type': 'effect', 'effect': 'usepkg', 'start': 0, 'dur': 4, 'params': {}}]})
    tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    if old:  # 改名の前に作った作品の形：状態フォルダ .claude-cut/・.gitignore は .claude-cut だけ・フックは cc_state.py
        (d / '.gitignore').write_text('assets/\nwork/\noutput/\n.claude-cut/\n__pycache__/\n*.tmp\n*.part\n*.test.cut.json\n', encoding='utf-8', newline='\n')
        hook = (ROOT / 'tools' / 'cc_state.py').as_posix()
        (d / '.claude' / 'settings.json').write_text(json.dumps({'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': f'python "{hook}"'}]}]}}, indent=2) + '\n', encoding='utf-8')
        shutil.rmtree(d / '.mittler', ignore_errors=True)  # new_project が書いた .mittler/（2026-11-13〜）は、改名の前の作品には無い
        (d / '.claude-cut').mkdir()
    return tlf


def part_names(work):
    from mittler import names as N
    # ---- JS の側（server/names.js と extension.js の settingsNow）----
    cases = {}
    for name, dirs, gi in [('none', [], None), ('new_dir', ['.mittler'], None), ('old_dir', ['.claude-cut'], None), ('both', ['.mittler', '.claude-cut'], None),
                           ('old_gitignore', [], 'assets/\n.claude-cut/\n'), ('both_gitignore', [], '.mittler/\n.claude-cut/\n'), ('new_gitignore', [], '/.mittler\n')]:
        p = work / 'names' / name; p.mkdir(parents=True)
        for x in dirs:
            (p / x).mkdir()
        if gi is not None:
            (p / '.gitignore').write_text(gi, encoding='utf-8')
        cases[name] = str(p)
    js = work / 'names_check.js'
    js.write_text('''const path = require('path'), Module = require('module');
const ROOT = process.argv[2], cases = JSON.parse(process.argv[3]);
const N = require(path.join(ROOT, 'server', 'names.js'));
const out = { state: {}, env: {}, token: {}, pick: {}, settings: {} };
for (const [k, p] of Object.entries(cases)) out.state[k] = N.stateDirName(p);
out.env = { none: N.env('X', {}), old: N.env('X', { CC_X: 'o' }), neu: N.env('X', { MITTLER_X: 'n' }), both: N.env('X', { CC_X: 'o', MITTLER_X: 'n' }), empty_new: N.env('X', { CC_X: 'o', MITTLER_X: '' }) };
out.token = { none: N.tokenOf({}) === undefined, old: N.tokenOf({ 'x-cc-token': 'o' }), neu: N.tokenOf({ 'x-mittler-token': 'n' }), both: N.tokenOf({ 'x-cc-token': 'o', 'x-mittler-token': 'n' }) };
const ins = (g, w, d) => ({ defaultValue: d === undefined ? '' : d, globalValue: g, workspaceValue: w });
out.pick = { none: N.pickSetting(ins(), ins()), old: N.pickSetting(ins(), ins('o')), neu: N.pickSetting(ins('n'), ins()), both: N.pickSetting(ins('n'), ins('o')),
  ws_old_vs_user_new: N.pickSetting(ins('n'), ins(undefined, 'o')), zero: N.pickSetting(ins(undefined, undefined, null), ins(0)), no_old: N.pickSetting(ins('n'), undefined) };
// extension.js の settingsNow を、vscode の代わりの偽物で（人が書いた設定：古い名前だけ・新しい名前だけ・両方）
const written = { claudeCut: { 'render.python': 'OLD_PY', 'render.ffmpegDir': 'OLD_FF', 'master.scale': 3, 'voicevox.url': 'http://old' }, mittler: { 'render.python': 'NEW_PY', 'master.fps': 30 } };
const fake = { workspace: { isTrusted: true, getConfiguration: sec => ({ get: () => { throw new Error('get は使わない'); },
  inspect: k => ({ defaultValue: /^master\\.(scale|fps|outHeight|cacheGb)$/.test(k) ? null : '', globalValue: (written[sec] || {})[k] }) }) } };
// 登録の偽物：同じ ID の2回目は本物と同じく断る
const ids = new Set(); let refused = 0;
const once = id => { if (ids.has(id)) { refused++; throw new Error('already registered: ' + id); } ids.add(id); return { dispose() { } }; };
fake.window = { registerCustomEditorProvider: once }; fake.commands = { registerCommand: once };
const load = Module._load; Module._load = function (req) { return req === 'vscode' ? fake : load.apply(this, arguments); };
const ext = require(path.join(ROOT, 'extension.js'));
out.settings = ext.settingsNow();
// activate：新しい ID（mittler.*）と古い ID（claudeCut.*）の両方で登録する。前の拡張と新しい拡張が両方入っているとき（2回呼ばれる）も落ちない
const err = console.error; console.error = () => { };
let threw = '';
try { ext.activate({ subscriptions: [], extension: { packageJSON: { contributes: { customEditors: [{ viewType: 'claudeCut.timeline' }] } } } }); ext.activate({ subscriptions: [] }); } catch (e) { threw = String(e.message || e); }
console.error = err;
out.activate = { ids: [...ids].sort(), refused, threw };
console.log(JSON.stringify(out));
''', encoding='utf-8', newline='\n')
    o = json.loads(node(js, str(ROOT), json.dumps(cases)).strip().splitlines()[-1])
    want = {'none': '.mittler', 'new_dir': '.mittler', 'old_dir': '.claude-cut', 'both': '.mittler', 'old_gitignore': '.claude-cut', 'both_gitignore': '.mittler', 'new_gitignore': '.mittler'}
    check(o['state'] == want, f"状態フォルダの決まり（JS）：{o['state']}")
    py_state = {k: N.state_dir_name(p) for k, p in cases.items()}
    check(py_state == want, f'状態フォルダの決まり（Python が JS と同じ答え）：{py_state}')
    check(o['env'] == {'none': '', 'old': 'o', 'neu': 'n', 'both': 'n', 'empty_new': 'o'}, f"環境変数（JS）：古い CC_* が読める・両方あれば MITTLER_*（{o['env']}）")
    keep = {k: os.environ.pop(k, None) for k in ('CC_X', 'MITTLER_X')}
    try:
        got = {'none': N.env('X')}
        os.environ['CC_X'] = 'o'; got['old'] = N.env('X')
        os.environ['MITTLER_X'] = 'n'; got['both'] = N.env('X')
        del os.environ['CC_X']; got['neu'] = N.env('X')
    finally:
        for k, v in keep.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    check(got == {'none': None, 'old': 'o', 'both': 'n', 'neu': 'n'}, f'環境変数（Python）：古い CC_* が読める・両方あれば MITTLER_*（{got}）')
    check(o['token'] == {'none': True, 'old': 'o', 'neu': 'n', 'both': 'n'}, f"トークンのヘッダ：X-CC-Token も読める・両方あれば X-Mittler-Token（{o['token']}）")
    check(o['pick'] == {'none': '', 'old': 'o', 'neu': 'n', 'both': 'n', 'ws_old_vs_user_new': 'n', 'zero': 0, 'no_old': 'n'}, f"設定1つの読み方（pickSetting）：{o['pick']}")
    s = o['settings']
    check(s['local'] == {'python': 'NEW_PY', 'ffmpegDir': 'OLD_FF'} and s['voicevoxUrl'] == 'http://old' and s['master']['scale'] == 3 and s['master']['fps'] == 30
          and s['master']['outHeight'] == '' and s['presetsDir'] == '',
          f"VS Code の設定（extension.js の settingsNow）：claudeCut.* が効く・両方あれば mittler.*・どちらも無ければ空（{json.dumps(s, ensure_ascii=False)}）")
    names = ['newProject', 'openInBrowserUrl', 'reopenAsText', 'setup', 'timeline']  # setup：初期設定（2026-11-13）
    act = o['activate']
    check(act['ids'] == sorted(f'{p}.{n}' for p in ('mittler', 'claudeCut') for n in names) and act['refused'] == 2 * len(names) and not act['threw'],
          f"拡張の登録（extension.js の activate）：新しい ID mittler.* と古い ID claudeCut.* の両方・2回呼ばれても落ちない（{len(act['ids'])} 個・断られた {act['refused']}・{act['threw'] or '例外なし'}）")
    contrib = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['contributes']
    check(contrib['customEditors'][0]['viewType'] == 'mittler.timeline' and sorted(c['command'] for c in contrib['commands']) == sorted(f'mittler.{n}' for n in names if n != 'timeline'),
          'package.json：カスタムエディタとコマンドの ID は mittler.* だけ（古い ID は出していない）')
    pk = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['contributes']['configuration']['properties']
    # 古い名前 claudeCut.* は、改名の前からあった 16 個だけ（読むだけ）。改名のあとに足した設定（mittler.language・blender.path・image.engine など）には古い名前を作らない
    newk = {k[len('mittler.'):] for k in pk if k.startswith('mittler.')}; oldk = sorted(k[len('claudeCut.'):] for k in pk if k.startswith('claudeCut.'))
    check(len(oldk) == 16 and set(oldk) <= newk and all('deprecationMessage' in pk['claudeCut.' + k] and 'deprecationMessage' not in pk['mittler.' + k] for k in oldk),
          f'package.json：mittler.* {len(newk)} 個・古い名前 claudeCut.*（deprecationMessage 付き）{len(oldk)} 個は、どれも同じ名前の mittler.* がある（古い名前の無い新しい設定 {sorted(newk - set(oldk))}）')
    # 表示の文は package.nls.json（英語）・package.nls.ja.json（日本語）：package.json の %鍵% が両方にある
    import re as _re
    keys = set(_re.findall(r'"%([^%"\s]+)%"', (ROOT / 'package.json').read_text(encoding='utf-8')))
    nls = {n: json.loads((ROOT / n).read_text(encoding='utf-8')) for n in ('package.nls.json', 'package.nls.ja.json')}
    check(keys and all(keys <= set(d) for d in nls.values()) and set(nls['package.nls.json']) == set(nls['package.nls.ja.json']),
          f'package.json の表示の文：%鍵% {len(keys)} 個が package.nls.json・package.nls.ja.json の両方にある')


def part_package(work, tl_old):
    import ccpy
    import ccpy.engine
    import mittler.engine
    import mittler.helpers
    from ccpy import helpers as h_old
    from ccpy.lib import look as look_old
    import mittler.lib.look
    check(h_old is mittler.helpers and look_old is mittler.lib.look and ccpy.engine is mittler.engine and h_old.__name__ == 'mittler.helpers' and h_old.__spec__.name == 'mittler.helpers',
          'ccpy.<名前> は mittler.<名前> と同じモジュールそのもの（写しを作らない）')
    out = {}
    for mod in ('ccpy', 'mittler'):
        r = run_py(['-m', mod, 'stills', tl_old, '--at', '0.5,2.0,3.5', '--out', work / f'stills_{mod}'], cwd=ROOT / 'pyengine')
        if r.returncode:
            print(r.stdout[-800:], r.stderr[-1500:])
        out[mod] = {p.name: sha(p) for p in sorted((work / f'stills_{mod}').glob('*.png'))} if not r.returncode else None
    check(out['ccpy'] and out['ccpy'] == out['mittler'] and len(out['ccpy']) == 3, f"python -m ccpy stills と python -m mittler stills が同じ PNG（{[v[:10] for v in (out['ccpy'] or {}).values()]}）")
    r = run_py(['-m', 'ccpy.analyze', '--help'], cwd=ROOT / 'pyengine')
    check(r.returncode == 0 and 'transcribe' in r.stdout, 'python -m ccpy.analyze が動く（--help）')
    return out['mittler'] or {}


def part_work(tag, d, tlf, launcher, env, header, hook, api, state_name, other_state, stills, presets_want):
    srv = Server(launcher, tlf, env, header)
    res = {}
    try:
        st = srv.ready(header)
        check(st.get('ready') is True, f'{tag}：{launcher} serve で描画サーバーが起動する（{st.get("error") or "ready"}）')
        check((d / state_name / 'server.json').is_file() and not (d / other_state).exists(), f'{tag}：状態フォルダは {state_name}/（{other_state}/ を作らない）')
        T = srv.token
        codes = {'なし': srv.call('/api/log', method='POST')[0], '古いヘッダ': srv.call('/api/log', method='POST', headers={'X-CC-Token': T})[0],
                 '新しいヘッダ': srv.call('/api/log', method='POST', headers={'X-Mittler-Token': T})[0],
                 '両方（新しいほうが正しい）': srv.call('/api/log', method='POST', headers={'X-Mittler-Token': T, 'X-CC-Token': 'x'})[0],
                 '両方（新しいほうが違う）': srv.call('/api/log', method='POST', headers={'X-Mittler-Token': 'x', 'X-CC-Token': T})[0]}
        check(codes == {'なし': 403, '古いヘッダ': 200, '新しいヘッダ': 200, '両方（新しいほうが正しい）': 200, '両方（新しいほうが違う）': 403}, f'{tag}：トークン（{codes}）')
        hid = {n: srv.call(f'/project/{n}/server.json')[0] for n in ('.claude-cut', '.mittler')}
        check(hid == {'.claude-cut': 403, '.mittler': 403}, f'{tag}：/project/ は状態フォルダを配らない（{hid}）')
        pr = json.loads(srv.call('/api/presets/characters')[1])
        check(Path(pr.get('dir', '')) == Path(presets_want), f"{tag}：プリセットの場所（環境変数）＝{pr.get('dir')}")
        ok = True
        for t, name in ((0.5, 'still_000.500.png'), (2.0, 'still_002.000.png')):
            r = json.loads(srv.call('/api/still', body={'t': t}, headers={header: T})[1])
            res[name] = sha(d / r['path']) if r.get('ok') else str(r)
            ok = ok and res[name] == stills.get(name)
        check(ok, f'{tag}：📷 の PNG がエンジンの静止画と同じ（{[v[:10] for v in res.values()]}）')
        s, body = srv.call('/api/frame?t=2.0&token=' + T)
        check(s == 200 and body[:2] == b'\xff\xd8', f'{tag}：プレビューの1コマ（JPEG {len(body)} バイト）')
        srv.call('/api/state', body={'name': '試し', 'time': {'t': 2.0, 'frame': 60}, 'selection': {'id': 'sub_1', 'label': '互換の確かめ', 'type': 'subtitle', 'track': {'name': '字幕'}, 'start': 0.5, 'end': 3.5},
                                     'at_time': [], 'frame_t': 2.0}, headers={header: T})
        stj = json.loads((d / state_name / 'state.json').read_text(encoding='utf-8'))
        check(stj.get('frame_image') == f'{state_name}/current_frame.jpg' and (d / state_name / 'current_frame.jpg').is_file(), f"{tag}：state.json と止めた1コマ（{stj.get('frame_image')}）")
        r = run_py([ROOT / 'tools' / hook, d])
        check(r.returncode == 0 and 'sub_1' in r.stdout and f'{state_name}/state.json' in r.stdout.replace('\\', '/') and 'current_frame.jpg' in r.stdout, f'{tag}：フック tools/{hook} の要約（{r.stdout.splitlines()[0] if r.stdout else r.stderr[-200:]}）')
        r = run_py([ROOT / 'tools' / api, d, 'status'])
        check(r.returncode == 0 and '"ready": true' in r.stdout, f'{tag}：tools/{api} status（{(r.stdout or r.stderr).strip()[:80]}）')
    finally:
        code = srv.quit()
    check(code == 200 and not (d / state_name / 'server.json').exists(), f'{tag}：/api/quit（ヘッダ {header}）で止まり、server.json を消す')
    return res


def part_tools(work, d_old):
    code = ('import sys; sys.path.insert(0, r"%s"); import h3_jobs\n'
            'try:\n    print(h3_jobs.places())\nexcept h3_jobs.Refuse as e:\n    print("Refuse")') % (ROOT / 'tools')
    a, b = work / 'drive_a', work / 'drive_b'
    for x in (a, b):
        (x / 'H3_tasks').mkdir(parents=True)
    r1 = run_py(['-c', code], env={'CC_MYDRIVE': str(a), 'CC_H3_ROOT': str(a / 'H3_tasks')}).stdout.strip()
    r2 = run_py(['-c', code], env={'CC_MYDRIVE': str(a), 'CC_H3_ROOT': str(a / 'H3_tasks'), 'MITTLER_MYDRIVE': str(b), 'MITTLER_H3_ROOT': str(b / 'H3_tasks')}).stdout.strip()
    check(r1 == repr((str(a), str(a / 'H3_tasks'))) and r2 == repr((str(b), str(b / 'H3_tasks'))), 'tools/h3_jobs.py：CC_MYDRIVE・CC_H3_ROOT が読める・両方あれば MITTLER_*')
    code = 'import sys; sys.path.insert(0, r"%s"); import codex_image; print(codex_image.DEFAULT_MODEL)' % (ROOT / 'tools' / 'gen')
    m = [run_py(['-c', code], env=e).stdout.strip() for e in ({}, {'CC_CODEX_MODEL': 'old-m'}, {'CC_CODEX_MODEL': 'old-m', 'MITTLER_CODEX_MODEL': 'new-m'})]
    check(m == ['gpt-6.1-sol', 'old-m', 'new-m'], f'tools/gen/codex_image.py：CC_CODEX_MODEL が読める・両方あれば MITTLER_CODEX_MODEL（{m}）')
    vid = work / 'no_such.mp4'
    e = [run_py(['-m', mod, 'enhance', vid, '--upscale', 'anime'], env=env, cwd=ROOT / 'pyengine') for mod, env in (('ccpy', {'CC_ESRGAN': 'X:/old/e.exe'}), ('mittler', {'MITTLER_ESRGAN': 'X:/new/e.exe'}))]
    check(all(r.returncode == 4 and 'MASTER_STOP' in r.stdout for r in e), 'python -m ccpy enhance・python -m mittler enhance：入力が無ければ同じ止まり方（終わりの番号 4・MASTER_STOP）')
    r = run_py([ROOT / 'tools' / 'fix_hooks.py', d_old, '--dry-run'])
    check(r.returncode == 0 and 'cc_state.py' in r.stdout and "'.mittler'" in r.stdout and 'hook.py' in r.stdout,
          f'tools/fix_hooks.py --dry-run：古いフック cc_state.py を見つけて、今の書き方（.mittler/hook.py を探す。2026-11-13〜）に直す案を出す（{r.stdout.strip()[:120]}）')
    hook = json.loads((d_old / '.claude' / 'settings.json').read_text(encoding='utf-8'))['hooks']['UserPromptSubmit'][0]['hooks'][0]['command']
    check('cc_state.py' in hook, '--dry-run は作品を書きかえない')


def main():
    keep = sys.argv[sys.argv.index('--work') + 1] if '--work' in sys.argv else None
    ctx = None if keep else tempfile.TemporaryDirectory(prefix='mittler_compat_', ignore_cleanup_errors=True)
    work = Path(keep).resolve() if keep else Path(ctx.name)
    if keep:
        if work.exists() and any(work.iterdir()):
            sys.exit(f'--work は空のフォルダにする：{work}')
        work.mkdir(parents=True, exist_ok=True)
    try:
        part_names(work)
        d_old, d_new = work / 'old_work', work / 'new_work'
        tl_old = make_work(d_old, 'ccpy', 'CC_ROOT', True)
        tl_new = make_work(d_new, 'mittler', 'MITTLER_ROOT', False)
        gi = (d_new / '.gitignore').read_text(encoding='utf-8').split()
        hook_new = (d_new / '.claude' / 'settings.json').read_text(encoding='utf-8')
        check('.mittler/' in gi and '.claude-cut/' in gi and "'.mittler'" in hook_new and 'hook.py' in hook_new and 'cc_state.py' not in hook_new
              and '.mittler/api.py' in (d_new / 'AGENTS.md').read_text(encoding='utf-8') and '@AGENTS.md' in (d_new / 'CLAUDE.md').read_text(encoding='utf-8'),
              '新しい作品（new_project）：.gitignore に .mittler/ と .claude-cut/・フックは状態フォルダの中継 hook.py を探す形・AGENTS.md が本文で CLAUDE.md がそれを読み込む')
        stills = part_package(work, tl_old)
        pa, pb = work / 'presets_a', work / 'presets_b'
        pa.mkdir(); pb.mkdir()
        res_old = part_work('古い名前の作品', d_old, tl_old, 'cc.cmd', {'CC_NO_REVEAL': '1', 'CC_PRESETS': str(pa)}, 'X-CC-Token', 'cc_state.py', 'cc_api.py', '.claude-cut', '.mittler', stills, pa)
        res_new = part_work('新しい名前の作品', d_new, tl_new, 'mittler.cmd', {'MITTLER_NO_REVEAL': '1', 'CC_PRESETS': str(pa), 'MITTLER_PRESETS': str(pb)}, 'X-Mittler-Token',
                            'mittler_state.py', 'mittler_api.py', '.mittler', '.claude-cut', stills, pb)
        check(res_old == res_new and len(res_new) == 2, '古い名前の作品と新しい名前の作品（中身は同じ）で、同じ絵')
        part_tools(work, d_old)
    finally:
        if ctx:
            ctx.cleanup()
    print(f'smoke_compat: {"FAIL " + str(len(fails)) if fails else "OK"}')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
