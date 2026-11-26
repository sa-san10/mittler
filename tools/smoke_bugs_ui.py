"""バグ直し（2026-11-12 のバグ探しの B3・B4・B5・B11 など）のやり直しを防ぐ確かめのうち、編集画面（ブラウザ）が要るもの。
  <Playwright の python> -X utf8 tools/smoke_bugs_ui.py --render-python <描画の python> [--work <フォルダ>] [--only B3,B11,…]
  （Playwright の python：Playwright と、localhost 以外への通信を止めるガードの入った venv。--work：試しの作品を残す場所。無ければ一時フォルダに作って消す）
試しの作品（320×180・30fps。赤 0〜1 秒・青 1〜2 秒の画像クリップと効果音）を自分で作り、サーバーを自分で立てて（127.0.0.1・空いているポート）、
終わったら /api/quit で止める。ブラウザは localhost だけ。ブラウザの要らない確かめは tools/smoke_bugs.py。
確かめること（番号は、2026-11-12 のバグ探しの報告 report_bughunt.md の番号）：
  B3  編集画面で動かす・伸び縮み・分けるで、コマに乗っている時刻をコマの時刻そのもの（n / fps）で書く（6 桁に丸めない）。エンジンと同じ比べ方
      （start <= t < start + dur）で、タイムラインで合わせたコマから切り替わる。前からある 6 桁の値は、開いただけ・触らない端は書きかえない
  B11 クリップの「開始」「長さ」の欄：負の数・0・コマに乗らない値を打っても、0 以上・1 コマ以上・コマの時刻になる
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

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
# 画面の文は辞書から引く（言い回しを直しても、この確かめを直さなくて済むように）
_JA = json.loads((ROOT / 'editor' / 'i18n' / 'ja.json').read_text(encoding='utf-8'))
SAVE_FAIL = re.sub(r'\{icon:[^}]*\}\s*', '', _JA['st.saveFailed']).split('（')[0]
SAVE_OK = _JA.get('st.saved', '保存しました').split('（')[0]
fails = []
FPS = 30


def opt(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


RPY = opt('--render-python')
if not RPY:
    sys.exit('使い方: smoke_bugs_ui.py --render-python <描画の python> [--work <フォルダ>] [--only B3,…]')


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


def node_cmd():
    n = shutil.which('node')
    return [n] if n else ['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node']


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close()
    return p


def make_project(d):
    r = subprocess.run(node_cmd() + [str(ROOT / 'tools' / 'new_project.js'), str(d), '--no-git', '--json', '--lang', 'ja'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    if r.returncode:
        raise SystemExit('new_project 失敗: ' + r.stdout + r.stderr)
    ff = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i']
    for name, col in (('red', '0xDC1E1E'), ('blue', '0x1E1EDC')):
        subprocess.run(ff + [f'color=c={col}:s=320x180', '-frames:v', '1', str(d / 'assets' / 'images' / f'{name}.png')], check=True)
    subprocess.run(ff + ['sine=frequency=880:duration=1:sample_rate=48000', '-ac', '2', str(d / 'assets' / 'sfx' / 'beep.wav')], check=True)
    return d / f'{d.name}.cut.json'


def base_tl(tlf, old_digits=False):
    """赤 0〜1 秒・青 1〜2 秒・効果音 0.5〜1.5 秒。old_digits：前の編集画面が書いた形（6 桁に丸めた 20 コマ目＝0.666667）"""
    tl = json.loads(tlf.read_text(encoding='utf-8'))
    tl.update(width=320, height=180, fps=FPS, duration=3)
    for tr in tl['tracks']:
        tr['clips'] = []
    v = next(t for t in tl['tracks'] if t['kind'] == 'video')
    a = next(t for t in tl['tracks'] if t['kind'] == 'audio')
    if old_digits:
        v['clips'] = [{'id': 'a', 'type': 'image', 'src': 'assets/images/red.png', 'start': 0, 'dur': 0.666667, 'label': 'red'},
                      {'id': 'b', 'type': 'image', 'src': 'assets/images/blue.png', 'start': 0.666667, 'dur': 1.0, 'label': 'blue'}]
    else:
        v['clips'] = [{'id': 'a', 'type': 'image', 'src': 'assets/images/red.png', 'start': 0, 'dur': 1, 'label': 'red'},
                      {'id': 'b', 'type': 'image', 'src': 'assets/images/blue.png', 'start': 1, 'dur': 1, 'label': 'blue'}]
    a['clips'] = [{'id': 'se', 'type': 'audio', 'src': 'assets/sfx/beep.wav', 'start': 0.5, 'dur': 1, 'in': 0, 'gain': -12, 'fade_in': 0, 'fade_out': 0, 'label': 'beep'}]
    return tl


def write_tl(tlf, tl):
    tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')


def read_tl(tlf):
    return json.loads(tlf.read_text(encoding='utf-8'))


def clip(tl, cid):
    return next(c for tr in tl['tracks'] for c in tr['clips'] if c['id'] == cid)


def frames_of(c):
    """エンジンと同じ比べ方（start <= n / fps < start + dur）で、クリップがかかるコマ番号の頭と終わり（終わりは含まない）"""
    on = [n for n in range(0, 200) if c['start'] <= n / FPS < c['start'] + c['dur']]
    return (on[0], on[-1] + 1) if on else None


class Server:
    def __init__(self, tlf, logf):
        env = dict(os.environ); env['MITTLER_NO_REVEAL'] = '1'
        self.log = open(logf, 'w', encoding='utf-8', errors='replace')
        # 画面の言葉は日本語で確かめる（サーバーは --lang ja、ページは &lang=ja。英語の確かめは tools/smoke_i18n.py）
        self.p = subprocess.Popen(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'serve', str(tlf), '--port', str(free_port()), '--render-python', RPY, '--lang', 'ja'],
                                  stdout=subprocess.PIPE, stderr=self.log, env=env, text=True, encoding='utf-8', errors='replace')
        self.url = self.p.stdout.readline().strip()
        if not self.url.startswith('http://127.0.0.1:'):
            raise SystemExit('サーバーが起動しない: ' + self.url)
        self.token = re.search(r'token=(\w+)', self.url).group(1)
        self.base = self.url.split('/editor/')[0]

    def get(self, path, timeout=120):
        req = urllib.request.Request(self.base + path, headers={'X-Mittler-Token': self.token})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def frame(self, n):
        """コマ n の絵の印（プレビューの JPEG の SHA）"""
        return hashlib.sha1(self.get(f'/api/frame?t={n / FPS!r}')).hexdigest()[:12]

    def ready(self):
        for _ in range(240):
            st = json.loads(self.get('/api/status'))
            if st.get('ready') or st.get('error'):
                return st
            time.sleep(0.5)
        return st

    def quit(self):
        try:
            urllib.request.urlopen(urllib.request.Request(self.base + '/api/quit', data=b'{}', method='POST', headers={'X-Mittler-Token': self.token}), timeout=10).read()
        except Exception as e:
            print('quit 失敗', e)
        try:
            self.p.wait(timeout=45)
        except subprocess.TimeoutExpired:
            print('サーバーが止まらない pid', self.p.pid)
        self.log.close()


class Page:
    def __init__(self, pw, url):
        self.br = pw.chromium.launch()
        self.pg = self.br.new_page(viewport={'width': 1500, 'height': 900})
        self.errors = []
        self.pg.on('pageerror', lambda e: self.errors.append(str(e)))
        self.pg.goto(url + '&lang=ja')
        self.wait(lambda: self.ev('!!(window.MITTLER_EDITOR && MITTLER_EDITOR.tl && MITTLER_EDITOR.fxReady)'), 60)

    def ev(self, js):
        return self.pg.evaluate(js)

    def wait(self, fn, sec=20):
        t0 = time.time()
        while time.time() - t0 < sec:
            if fn():
                return True
            self.pg.wait_for_timeout(100)  # time.sleep だと、待っているあいだ Playwright の route（保存を失敗させる偽物）が動かない
        return False

    def saved(self, sec=20):
        """画面の直しがファイルに保存されるまで待つ"""
        time.sleep(0.45)
        return self.wait(lambda: self.ev('!MITTLER_EDITOR.saveTimer && !MITTLER_EDITOR.saving && MITTLER_EDITOR.lastSaved === JSON.stringify(MITTLER_EDITOR.tl)'), sec)

    def reloaded(self, tl, sec=20):
        """外で書いたタイムライン tl を画面が読み直すまで待つ"""
        return self.wait(lambda: self.ev('MITTLER_EDITOR.tl') == tl, sec)

    def status(self):
        return self.ev("document.getElementById('status').textContent")

    def close(self):
        self.br.close()


# ---------------------------------------------------------------- B3
def b3(S, P, tlf):
    tl0 = base_tl(tlf); write_tl(tlf, tl0)
    check(P.reloaded(tl0), 'B3 試しのタイムライン（赤 0〜1 秒・青 1〜2 秒）を画面が読んだ')
    red, blue, black = S.frame(5), S.frame(45), S.frame(75)
    check(len({red, blue, black}) == 3, 'B3 赤・青・黒のコマが別の絵')
    # 丸めの計算そのもの（24・30・60・29.97 fps）：頭 a コマ・終わり b コマのクリップは、コマ a から b-1 までにかかる（エンジンと同じ足し算・比べ方で）
    bad = P.ev('''(() => { const keep = MITTLER_EDITOR.tl.fps; let bad = 0, n = 0, six = 0;
      for (const f of [24, 30, 60, 29.97]) { MITTLER_EDITOR.tl.fps = f;
        for (let a = 0; a < 400; a += 1) for (const k of [1, 2, 3, 7, 10, 30, 61, 100, 333]) {
          const s = rT(+(a / f).toFixed(6)), e = snapFrame((a + k) / f), d = durTo(s, e); n++;
          if (s !== a / f) bad++;                                   // 6 桁に丸めた値も、コマの時刻そのものに戻る
          if (!(s <= a / f) || !(s + d <= (a + k) / f) || !((a + k - 1) / f < s + d)) bad++;
          if (!(+(a / f).toFixed(6) <= a / f)) six++; } }
      MITTLER_EDITOR.tl.fps = keep; return [bad, n, six]; })()''')
    check(bad[0] == 0, f'B3 コマの時刻の書き方（rT・durTo）：{bad[1]} 通りで、頭のコマからかかり、終わりのコマではかからない（6 桁の丸めのままだと頭が遅れるのは {bad[2]} 通り）')
    # 動かす：青を 10 コマ前へ（Alt+Shift+←）
    P.ev("MITTLER_EDITOR.select('b')"); P.pg.keyboard.press('Alt+Shift+ArrowLeft'); P.saved()
    b = clip(read_tl(tlf), 'b')
    check(b['start'] == 20 / FPS, f"B3 10 コマ前へ動かした青の頭が、20 コマ目の時刻そのもの（{b['start']!r}。前は 0.666667）")
    check(frames_of(b) == (20, 50), f'B3 青はコマ 20〜49 にかかる（{frames_of(b)}）')
    got = [S.frame(n) for n in (19, 20, 49, 50)]
    check(got == [red, blue, blue, black], f'B3 描いた絵：コマ 19 は赤・20 と 49 は青・50 は黒（{[("赤" if g == red else "青" if g == blue else "黒" if g == black else "?") for g in got]}）')
    # 伸び縮み：青の頭を 7 コマ後ろへ、終わりを 4 コマ前へ
    P.ev("MITTLER_EDITOR.change(() => { const c = findClip('b').clip; trimClip(c, 'l', 7 / fps()); trimClip(c, 'r', -4 / fps()); })"); P.saved()
    b = clip(read_tl(tlf), 'b')
    check(b['start'] == 27 / FPS and frames_of(b) == (27, 46), f"B3 伸び縮みのあと、青はコマ 27〜45（頭 {b['start']!r}・かかるコマ {frames_of(b)}）")
    # 分ける：コマ 37 で（Ctrl+K）
    P.ev('MITTLER_EDITOR.seek(37 / fps())'); P.pg.keyboard.press('Control+k'); P.saved()
    tl = read_tl(tlf)
    parts = sorted((c for c in next(t for t in tl['tracks'] if t['kind'] == 'video')['clips'] if c['src'].endswith('blue.png')), key=lambda c: c['start'])
    check(len(parts) == 2 and [frames_of(c) for c in parts] == [(27, 37), (37, 46)] and parts[1]['start'] == 37 / FPS,
          f'B3 コマ 37 で分けた青は、コマ 27〜36 と 37〜45（{[frames_of(c) for c in parts]}）')
    # 取り消し 3 回で最初と同じ
    for _ in range(3):
        P.pg.keyboard.press('Control+z')
    P.saved()
    check(read_tl(tlf) == tl0, 'B3 取り消し 3 回で、タイムラインが最初と同じ')
    # 前からある 6 桁の値：開いただけでは書きかえない。触らない端（頭）も書きかえない
    old = base_tl(tlf, old_digits=True); write_tl(tlf, old); text0 = tlf.read_text(encoding='utf-8')
    check(P.reloaded(old), 'B3 6 桁の値のタイムライン（青の頭 0.666667）を画面が読んだ')
    P.ev("MITTLER_EDITOR.select('b')"); P.ev("MITTLER_EDITOR.select('a')"); P.ev('MITTLER_EDITOR.seek(1)'); time.sleep(1.2)
    check(tlf.read_text(encoding='utf-8') == text0, 'B3 開いて選んだだけでは、ファイルが 1 バイトも変わらない')
    P.ev("MITTLER_EDITOR.change(() => trimClip(findClip('b').clip, 'r', -5 / fps()))"); P.saved()
    b = clip(read_tl(tlf), 'b')
    check(b['start'] == 0.666667 and frames_of(b) == (21, 45), f"B3 終わりだけ縮めたとき、頭の 6 桁の値はそのまま（{b['start']!r}）。終わりはコマ 45 でかからなくなる（{frames_of(b)}）")
    P.ev("MITTLER_EDITOR.select('b')"); P.pg.keyboard.press('Alt+ArrowRight'); P.saved()
    b = clip(read_tl(tlf), 'b')
    check(b['start'] == 21 / FPS and frames_of(b) == (21, 46), f"B3 動かしたクリップは、コマの時刻そのものになる（頭 {b['start']!r}・コマ {frames_of(b)}）")


# ---------------------------------------------------------------- B11
def b11(S, P, tlf):
    tl0 = base_tl(tlf); write_tl(tlf, tl0)
    check(P.reloaded(tl0), 'B11 試しのタイムラインを画面が読んだ')

    def typed(cid, key, val):
        P.ev(f"MITTLER_EDITOR.select('{cid}')")
        el = P.pg.locator(f'#sel [data-k="{key}"]').first
        el.fill(str(val)); el.dispatch_event('change'); P.saved()
        return clip(read_tl(tlf), cid)
    for cid, name in (('se', '音'), ('b', '画像')):
        c = typed(cid, 'dur', '0')
        one = lambda c: (lambda fr: fr is not None and fr[1] - fr[0] == 1)(frames_of(c))
        check(one(c), f"B11 {name}のクリップの長さに 0 → 1 コマ（{c['dur']!r}・かかるコマ {frames_of(c)}）")
        c = typed(cid, 'dur', '-1')
        check(one(c), f"B11 {name}のクリップの長さに -1 → 1 コマ（{c['dur']!r}・かかるコマ {frames_of(c)}）")
        c = typed(cid, 'start', '-1')
        check(c['start'] == 0, f"B11 {name}のクリップの開始に -1 → 0（{c['start']!r}）")
        c = typed(cid, 'start', '0.067')
        check(c['start'] == 2 / FPS, f"B11 {name}のクリップの開始に 0.067 → 2 コマ目の時刻（{c['start']!r}）")
        c = typed(cid, 'dur', '0.667')
        check(frames_of(c) == (2, 22), f"B11 {name}のクリップの長さに 0.667 → 20 コマ（かかるコマ {frames_of(c)}）")
    c = typed('se', 'in', '-0.5')
    check(c['in'] == 0, f"B11 音のクリップの素材の頭に -0.5 → 0（{c['in']!r}）")
    c = typed('se', 'gain', '-18')
    check(c['gain'] == -18, f"B11 音量は負の数のまま（{c['gain']!r}）")
    write_tl(tlf, tl0); P.reloaded(tl0)


# ---------------------------------------------------------------- B4
def b4(S, P, tlf):
    tl0 = base_tl(tlf); write_tl(tlf, tl0)
    check(P.reloaded(tl0), 'B4 試しのタイムラインを画面が読んだ')
    st = lambda: P.ev("[document.getElementById('status').textContent, !!MITTLER_EDITOR.saveTimer, !!MITTLER_EDITOR.saving, MITTLER_EDITOR.lastSaved === JSON.stringify(MITTLER_EDITOR.tl)]")
    mode = {'v': '500'}

    def route(r):
        if r.request.method != 'PUT' or mode['v'] == 'ok':
            return r.continue_()
        if mode['v'] == '500':
            return r.fulfill(status=500, body='{"error":"EPERM: operation not permitted, rename"}', content_type='application/json')
        return r.abort()
    P.pg.route('**/api/timeline', route)
    # 1. サーバーが 500 を返す
    P.ev("MITTLER_EDITOR.change(() => { findClip('a').clip.label = 'red-500'; })"); P.pg.wait_for_timeout(1200)  # time.sleep だと route が動かない
    s = st()
    check(SAVE_FAIL in s[0] and SAVE_OK not in s[0], f'B4 保存が 500 のとき「保存できなかった」と出る（「保存しました」で上書きしない）：{s[0][:70]}')
    check(s[3] is False, 'B4 保存が 500 のとき、保存できたことにしない（lastSaved を入れない）')
    check(clip(read_tl(tlf), 'a')['label'] == 'red', 'B4 ファイルは前のまま（保存されていない）')
    mode['v'] = 'ok'
    ok = P.wait(lambda: clip(read_tl(tlf), 'a')['label'] == 'red-500', 12)
    check(ok and P.wait(lambda: st()[0] == '保存しました' and st()[3], 5), f'B4 やり直しで保存される（{st()[0][:40]}）')
    # 2. 通信が切れる
    mode['v'] = 'abort'
    P.ev("MITTLER_EDITOR.change(() => { findClip('a').clip.label = 'red-abort'; })"); P.pg.wait_for_timeout(1200)
    s = st()
    check(SAVE_FAIL in s[0], f'B4 通信が切れたとき「保存できなかった」と出る：{s[0][:70]}')
    check(s[2] is False, 'B4 通信が切れても、保存中の印（saving）が残らない')
    mode['v'] = 'ok'
    ok = P.wait(lambda: clip(read_tl(tlf), 'a')['label'] == 'red-abort', 12)
    check(ok and P.wait(lambda: st()[3] and not st()[1] and not st()[2], 5), 'B4 つながったら、やり直しで保存される')
    P.pg.unroute('**/api/timeline')
    # 3. そのあと外（Claude Code など）で直したタイムラインを読み直す（前は、通信が切れたあと読み直さなくなった）
    ext = read_tl(tlf); ext['name'] = '外で直した名前'; clip(ext, 'b')['label'] = 'blue-ext'; time.sleep(0.3); write_tl(tlf, ext)
    check(P.reloaded(ext, 8), 'B4 保存の失敗のあとでも、外で直したタイムラインを読み直す')
    write_tl(tlf, tl0); P.reloaded(tl0)


# ---------------------------------------------------------------- B5
def b5(S, P, tlf):
    tl0 = base_tl(tlf); write_tl(tlf, tl0)
    check(P.reloaded(tl0), 'B5 試しのタイムラインを画面が読んだ')
    P.ev("MITTLER_EDITOR.select('b')"); P.pg.keyboard.press('Alt+ArrowRight'); P.saved()  # 画面の直し：青を 1 コマ後ろへ
    mine = read_tl(tlf)
    check(clip(mine, 'b')['start'] == 31 / FPS, 'B5 画面で青を 1 コマ動かした')
    ext = read_tl(tlf); ext['name'] = '外で直した名前'; clip(ext, 'a')['label'] = 'red-ext'; P.pg.wait_for_timeout(300); write_tl(tlf, ext)  # 外（Claude Code など）の直し
    check(P.reloaded(ext, 8), 'B5 外で直したタイムラインを画面が読み直した')
    P.ev("document.activeElement && document.activeElement.blur()")
    P.pg.keyboard.press('Control+z'); P.saved()
    t1 = read_tl(tlf)
    check(t1 == mine, f"B5 1 回目の Ctrl+Z は外の直しだけを戻す（名前 {t1['name']!r}・青の頭 {clip(t1, 'b')['start']!r}＝画面の直しは残る）")
    check('外' in P.status() and '取り消' in P.status(), f'B5 外の直しを取り消したと知らせる：{P.status()[:60]}')
    P.pg.keyboard.press('Control+z'); P.saved()
    check(read_tl(tlf) == tl0, 'B5 2 回目の Ctrl+Z で画面の直しを戻す（最初と同じ）')
    P.pg.keyboard.press('Control+Shift+z'); P.saved(); P.pg.keyboard.press('Control+Shift+z'); P.saved()
    check(read_tl(tlf) == ext, 'B5 やり直し 2 回で、外の直しまで戻る')
    write_tl(tlf, tl0); P.reloaded(tl0)


# ---------------------------------------------------------------- B16-2
def b16(S, P, tlf):
    """再生用の動画（preview.proxy）の名前に # % 空白があっても、URL をエンコードして読む"""
    name = 'a#b %c.webm'
    f = tlf.parent / 'work' / 'proxy' / name
    f.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=64x36:d=0.5', '-c:v', 'libvpx-vp9', str(f)], check=True)
    tl = base_tl(tlf); tl['preview'] = {'proxy': 'work/proxy/' + name}; write_tl(tlf, tl)
    P.reloaded(tl); P.pg.reload()  # 再生用の動画は、開いたときに読む
    check(P.wait(lambda: P.ev('!!(window.MITTLER_EDITOR && MITTLER_EDITOR.tl && MITTLER_EDITOR.fxReady)'), 60) and P.ev('MITTLER_EDITOR.tl') == tl, 'B16-2 再生用の動画つきのタイムラインを開き直した')
    src = P.ev("document.getElementById('proxy').getAttribute('src')")
    check(src == '/project/work/proxy/a%23b%20%25c.webm', f'B16-2 再生用の動画の URL をエンコードする（{src}）')
    ok = P.wait(lambda: P.ev("document.getElementById('proxy').readyState") >= 1 and not P.ev("!!document.getElementById('proxy').error"), 10)
    check(ok, f"B16-2 名前に # % 空白のある再生用の動画が読める（readyState {P.ev('document.getElementById(\"proxy\").readyState')}）")
    tl0 = base_tl(tlf); write_tl(tlf, tl0); P.reloaded(tl0)


TESTS = {'B3': b3, 'B11': b11, 'B4': b4, 'B5': b5, 'B16': b16}


def main():
    work = Path(opt('--work')).resolve() if opt('--work') else None
    only = set(opt('--only').upper().split(',')) if opt('--only') else None
    tmp = None
    if work is None:
        tmp = tempfile.mkdtemp(prefix='mittler_bugsui_')
        work = Path(tmp)
    work.mkdir(parents=True, exist_ok=True)
    proj = work / f'bugsui{int(time.time()) % 100000}'
    tlf = make_project(proj)
    write_tl(tlf, base_tl(tlf))
    S = Server(tlf, work / (proj.name + '_server.log'))
    P = None
    try:
        st = S.ready()
        if not st.get('ready'):
            raise SystemExit('描画サーバーが起動しない: ' + str(st.get('error')))
        with sync_playwright() as pw:
            P = Page(pw, S.url)
            for name, fn in TESTS.items():
                if only and name not in only:
                    continue
                try:
                    fn(S, P, tlf)
                except Exception as e:  # 1つ落ちても、ほかの項目は続ける
                    import traceback
                    check(False, f'{name} の確かめが例外で止まった: {e}\n{traceback.format_exc()[-800:]}')
            check(not P.errors, f'ページのエラーなし（{P.errors[:3]}）')
            P.close()
    finally:
        S.quit()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    print('FAIL ' + str(len(fails)) + ' 件' if fails else 'ALL OK')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
