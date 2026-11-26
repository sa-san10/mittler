"""編集画面の見た目と使い勝手（2026-11-12 の UI の作り直し）のやり直しを防ぐ確かめ。ヘッドレスのブラウザ、localhost だけ。
  <Playwright の python> -X utf8 tools/smoke_ui.py --render-python <描画の python> [--work <フォルダ>]
  （--work：試しの作品を残す場所。無ければ一時フォルダに作って消す）
試しの作品（320×180・30fps・3 秒）を自分で作り、サーバーを自分で立てて、終わったら /api/quit で止める。
確かめること：
  テーマ   ブラウザで直に開いたとき（--vscode-* が無い）、OS がダーク／ライトのどちらでも、地と字の色が入れかわり、主な部品の字が読める（コントラスト比 4.5 以上）
           VS Code の Webview（extension.js の html()）が、--vscode-* の変数とテーマの種類を中の iframe に渡し、編集画面の色がそれになる。テーマを切り替えると付いてくる
  知らせ   失敗の知らせは上の 1 行の色が変わり、右下にも残る（次の知らせで上書きされても消えない）。保存の失敗は、通ったら消える
           押せる知らせ（ここを押すと…）はボタンの形（data-level=act・Tab で移れる）
  ボタン   押せないボタン（貼り付け など）に理由が付く。上のバーのアイコン（Lucide。2026-11-14〜、前の絵文字の代わり）が出る（大きさ・型の絵が読めた）。幅 1600 では名前も出る
  数の欄   「開始」「長さ」の横にコマ番号・コマ数
  拡大     短い作品（3 秒）でも、タイムラインが幅いっぱい
  Ctrl+S   何もしないのをやめた（「保存済みです」／待っている保存をすぐ流す）
  崩れ     幅 1600・1280・900 で、上のバーのボタンがバーからはみ出さない・重ならない
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
fails = []


def opt(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


RPY = opt('--render-python')
if not RPY:
    sys.exit('使い方: smoke_ui.py --render-python <描画の python> [--work <フォルダ>]')


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
    subprocess.run(ff + ['color=c=0xDC1E1E:s=320x180', '-frames:v', '1', str(d / 'assets' / 'images' / 'red.png')], check=True)
    subprocess.run(ff + ['sine=frequency=880:duration=1:sample_rate=48000', '-ac', '2', str(d / 'assets' / 'sfx' / 'beep.wav')], check=True)
    tlf = d / f'{d.name}.cut.json'
    tl = json.loads(tlf.read_text(encoding='utf-8'))
    tl.update(width=320, height=180, fps=30, duration=3)
    for tr in tl['tracks']:
        tr['clips'] = []
    next(t for t in tl['tracks'] if t['kind'] == 'video')['clips'] = [{'id': 'a', 'type': 'image', 'src': 'assets/images/red.png', 'start': 0.5, 'dur': 1, 'label': 'red'}]
    next(t for t in tl['tracks'] if t['kind'] == 'audio')['clips'] = [{'id': 'se', 'type': 'audio', 'src': 'assets/sfx/beep.wav', 'start': 0.5, 'dur': 1, 'in': 0, 'gain': -12, 'label': 'beep'}]
    tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    return tlf


class Server:
    def __init__(self, tlf, logf):
        env = dict(os.environ); env['MITTLER_NO_REVEAL'] = '1'
        self.log = open(logf, 'w', encoding='utf-8', errors='replace')
        # 画面の言葉は日本語で確かめる（サーバーは --lang ja、ページは &lang=ja。既定の英語の確かめは tools/smoke_i18n.py）
        self.p = subprocess.Popen(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'serve', str(tlf), '--port', str(free_port()), '--render-python', RPY, '--lang', 'ja'],
                                  stdout=subprocess.PIPE, stderr=self.log, env=env, text=True, encoding='utf-8', errors='replace')
        self.url = self.p.stdout.readline().strip()
        if not self.url.startswith('http://127.0.0.1:'):
            raise SystemExit('サーバーが起動しない: ' + self.url)
        self.token = re.search(r'token=(\w+)', self.url).group(1)
        self.base = self.url.split('/editor/')[0]

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


# 字と地のコントラスト比（WCAG）。地は、その部品から親へたどって最初の透けていない色
CONTRAST_JS = """sel => {
  const el = document.querySelector(sel); if (!el) return null;
  const cv = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  const rgba = c => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = '#000'; cv.fillStyle = c; cv.fillRect(0, 0, 1, 1); const d = cv.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (f, b) => [0, 1, 2].map(i => f[i] * f[3] + b[i] * (1 - f[3])).concat(1);
  let bg = [255, 255, 255, 0]; const chain = [];
  for (let e = el; e; e = e.parentElement) chain.push(rgba(getComputedStyle(e).backgroundColor));
  chain.push(rgba(getComputedStyle(document.documentElement).backgroundColor)); chain.push([255, 255, 255, 1]);
  let acc = [0, 0, 0, 0];
  for (const c of chain) { acc = [0, 1, 2].map(i => (acc[i] * acc[3] + c[i] * c[3] * (1 - acc[3])) / ((acc[3] + c[3] * (1 - acc[3])) || 1)).concat(acc[3] + c[3] * (1 - acc[3])); if (acc[3] > 0.995) break; }
  bg = acc; const fg = over(rgba(getComputedStyle(el).color), bg);
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const a = lum(fg), b = lum(bg); return +((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)).toFixed(2);
}"""
# 読めるかを確かめる部品（字のあるもの）
TEXT_SELECTORS = ['#file', '#durBtn', '#fit', '#exportBtn', '#paneTabs button.on', '#paneTabs button:not(.on)', '#assetTabs button.on', '#assetTabs button:not(.on)',
                  '#time', '#frame', '#headList .head .nm', '#ruler .tick', '#cutbar button:not(:disabled)', '#sel .form label', '#sel input[data-k=start]', '.fhint',
                  '#laneList .clip .lb', '.zoom', '#transport .pvScale']


def wait_ready(pg):
    pg.wait_for_function('() => window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl && window.MITTLER_EDITOR.assets', timeout=60000)
    pg.wait_for_function("() => document.querySelector('#cutbar button') && document.getElementById('exportBtn') && !document.getElementById('exportBtn').hidden", timeout=60000)
    pg.evaluate("() => { MITTLER_ASSETS.setOpen(true); MITTLER_EDITOR.select('se'); }")
    pg.wait_for_selector('#sel input[data-k=start]')


def main(work):
    tlf = make_project(work / 'ui1')
    srv = Server(tlf, work / 'server.log')
    errors = []
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()

            def page(w=1280, scheme='dark', q=''):
                ctx = br.new_context(viewport={'width': w, 'height': 860}, color_scheme=scheme)
                pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
                pg.goto(srv.url + '&lang=ja' + q); wait_ready(pg)
                return ctx, pg

            # ---- テーマ：ブラウザで直に（ダーク・ライト）----
            seen = {}
            for scheme in ('dark', 'light'):
                ctx, pg = page(1280, scheme)
                seen[scheme] = pg.evaluate("() => [getComputedStyle(document.body).backgroundColor, getComputedStyle(document.body).color, getComputedStyle(document.getElementById('inspector')).backgroundColor]")
                low = []
                for sel in TEXT_SELECTORS:
                    c = pg.evaluate(CONTRAST_JS, sel)
                    if c is None or c < 4.5:
                        low.append(f'{sel}={c}')
                check(not low, f'テーマ（{scheme}・ブラウザで直に）：主な部品の字が読める（コントラスト比 4.5 以上。{len(TEXT_SELECTORS)} か所）' + (' 足りない：' + '、'.join(low) if low else ''))
                if scheme == 'light':
                    pg.evaluate("() => MITTLER_NOTIFY('失敗の知らせ', 'bad')"); pg.evaluate("() => setStatus('{icon:triangle-alert} 保存できなかった（HTTP 500）。2 秒後にやり直します（1 回目）', 'bad', { toast: false })")
                    lo = [f'{s}={pg.evaluate(CONTRAST_JS, s)}' for s in ('.mittlerToast.bad .tbody', '#status') if (pg.evaluate(CONTRAST_JS, s) or 0) < 4.5]
                    check(not lo, 'テーマ（light）：失敗の知らせ（右下・上の 1 行）の字が読める' + (' 足りない：' + '、'.join(lo) if lo else ''))
                ctx.close()
            check(seen['dark'][0] != seen['light'][0] and seen['dark'][1] != seen['light'][1], f"テーマ：OS がダーク／ライトで地と字の色が入れかわる（地 {seen['dark'][0]} ／ {seen['light'][0]}）")

            # ---- テーマ：URL の &theme=light は OS の設定に勝つ（確かめ用の口）----
            ctx, pg = page(1280, 'dark', '&theme=light')
            check(pg.evaluate("() => getComputedStyle(document.body).backgroundColor") == seen['light'][0], 'テーマ：&theme=light で、OS がダークでもライトの色')
            ctx.close()

            # ---- テーマ：VS Code の Webview から iframe へ（extension.js の html() を、vscode の代わりの偽物で読んで使う）----
            js = ("const Module = require('module'); const load = Module._load; Module._load = function (r) { return r === 'vscode' ? {} : load.apply(this, arguments); };"
                  "const x = require(process.env.SMOKE_EXT); process.stdout.write(x.html(process.env.SMOKE_SRC, process.env.SMOKE_ORIGIN, 'smokenonce'));")
            # URL は環境変数で渡す（mittler.cmd 越しの引数は、cmd の決まりで = のところで分かれる）
            r = subprocess.run(node_cmd() + ['-e', js], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
                               env=dict(os.environ, SMOKE_EXT=str(ROOT / 'extension.js'), SMOKE_SRC=srv.url + '&lang=ja', SMOKE_ORIGIN=srv.base))
            outer = r.stdout
            check("script-src 'nonce-smokenonce'" in outer and 'mittler-theme' in outer and '#16171b' not in outer, 'Webview：テーマを渡すスクリプトがあり、CSP は nonce だけ・地の色は決め打ちでない')
            ctx = br.new_context(viewport={'width': 1280, 'height': 860}, color_scheme='dark')
            pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
            pg.set_content(outer, wait_until='load')
            fr = next(f for f in pg.frames if f.url.startswith(srv.base))
            fr.wait_for_function('() => window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl', timeout=60000)

            def vscode_theme(cls, bg, fg, btn):
                pg.evaluate("""([cls, bg, fg, btn]) => { const st = document.documentElement.style;
                  st.setProperty('--vscode-editor-background', bg); st.setProperty('--vscode-sideBar-background', bg); st.setProperty('--vscode-foreground', fg);
                  st.setProperty('--vscode-button-background', btn); st.setProperty('--vscode-font-family', 'Georgia'); document.body.className = cls; }""", [cls, bg, fg, btn])
                fr.wait_for_function(f"() => document.documentElement.dataset.vscode === {json.dumps(cls)}", timeout=10000)
                return fr.evaluate("() => [getComputedStyle(document.body).backgroundColor, getComputedStyle(document.body).color, getComputedStyle(document.getElementById('play')).backgroundColor, document.documentElement.dataset.theme, getComputedStyle(document.body).fontFamily.split(',')[0].trim()]")
            a = vscode_theme('vscode-light', 'rgb(250, 240, 230)', 'rgb(20, 30, 40)', 'rgb(200, 0, 100)')
            check(a == ['rgb(250, 240, 230)', 'rgb(20, 30, 40)', 'rgb(200, 0, 100)', 'light', 'Georgia'], f'Webview → iframe：VS Code のテーマの色・書体になる（ライト）{a}')
            b2 = vscode_theme('vscode-dark', 'rgb(10, 20, 30)', 'rgb(220, 230, 240)', 'rgb(0, 100, 200)')
            check(b2[:4] == ['rgb(10, 20, 30)', 'rgb(220, 230, 240)', 'rgb(0, 100, 200)', 'dark'], f'Webview → iframe：テーマを切り替えると付いてくる（ダーク）{b2}')
            ctx.close()

            # ---- 知らせ・ボタン・数の欄・拡大・Ctrl+S ----
            ctx, pg = page(1500, 'dark')
            # 知らせの種類（ok・busy・warn・bad・act）は呼ぶ側が渡す（2026-11-13〜。前は文から決めていた。言葉を切り替えても同じ種類になるように）
            # 保存の失敗は右下に自分で出す（scheduleSave）ので、上の1行は toast: false（editor.js と同じ呼び方。前は文で外していた）
            pg.evaluate("() => setStatus('{icon:triangle-alert} 保存できなかった（HTTP 500）。2 秒後にやり直します（1 回目）', 'bad', { toast: false })")
            lv1 = pg.get_attribute('#status', 'data-level')
            pg.evaluate("() => setStatus('{icon:microscope} 解析に失敗（拍）：python が見つからない', 'bad')"); pg.evaluate("() => setStatus('保存しました', 'ok')")
            check(lv1 == 'bad' and pg.get_attribute('#status', 'data-level') == 'ok' and pg.locator('.mittlerToast.bad').count() == 1 and '解析に失敗' in pg.inner_text('.mittlerToast.bad'),
                  '知らせ：失敗は上の 1 行の種類が bad になり、次の知らせで上書きされても右下に残る')
            pg.wait_for_timeout(9500)
            check(pg.locator('.mittlerToast.bad').count() == 1, '知らせ：失敗の知らせは時間で消えない（押して閉じる）')
            pg.click('.mittlerToast.bad'); check(pg.locator('.mittlerToast').count() == 0, '知らせ：押すと閉じる')
            pg.evaluate("() => setStatus('{icon:camera} 保存しました：output/stills/x.png（0.1MB）　ここを押すと開く', 'act')")
            check(pg.locator('#status .ic[data-ic=camera]').count() == 1 and '{icon:' not in pg.inner_text('#status') and '{icon:' not in (pg.get_attribute('#status', 'title') or ''),
                  '知らせ：文の中のアイコンの印 {icon:…} は、上の 1 行ではアイコンに、ツールチップでは外れる')
            check(pg.get_attribute('#status', 'data-level') == 'act' and pg.get_attribute('#status', 'tabindex') == '0' and pg.evaluate("() => getComputedStyle(document.getElementById('status')).cursor") == 'pointer',
                  '知らせ：押せる知らせ（ここを押すと…）はボタンの形（Tab で移れる・手の形のカーソル）')
            # 保存の失敗：PUT を 1 回だけ 500 にする → 右下に「保存できていません」→ やり直しが通ると消える
            st = {'n': 0}

            def fail_once(route):
                if route.request.method == 'PUT' and st['n'] == 0:
                    st['n'] += 1; route.fulfill(status=500, body='smoke')
                else:
                    route.continue_()
            pg.route('**/api/timeline', fail_once)
            pg.evaluate("() => MITTLER_EDITOR.change(() => { MITTLER_EDITOR.tl.tracks.find(t => t.kind === 'video').clips[0].label = 'red2'; })")
            pg.wait_for_selector('.mittlerToast.bad .tact', timeout=10000)
            t1 = pg.inner_text('.mittlerToast.bad')
            pg.evaluate("() => setStatus('ほかの知らせ')")
            still = pg.locator('.mittlerToast.bad').count() == 1
            pg.click('.mittlerToast.bad .tact')  # 今すぐやり直す
            pg.wait_for_function("() => !document.querySelector('.mittlerToast.bad') && !MITTLER_EDITOR.saveTimer && !MITTLER_EDITOR.saving", timeout=20000)
            pg.unroute('**/api/timeline')
            saved = json.loads(tlf.read_text(encoding='utf-8'))
            check('保存できていません' in t1 and still and next(t for t in saved['tracks'] if t['kind'] == 'video')['clips'][0]['label'] == 'red2',
                  '知らせ：保存の失敗は右下に残り（ほかの知らせで消えない）、「今すぐやり直す」で保存が通ると消える')
            pg.evaluate("() => { document.querySelectorAll('.mittlerToast').forEach(e => e.remove()); }")

            # 押せないボタンの理由（頭の言葉は辞書から引く：言い回しを直しても、この確かめを直さなくて済むように）
            NOPE = re.split(r'\{', json.loads((ROOT / 'editor' / 'i18n' / 'ja.json').read_text(encoding='utf-8'))['ui.disabledWhy'])[0]
            pg.evaluate("() => { MITTLER_EDITOR.clipboard = null; MITTLER_EDITOR.select(null); }")
            paste = pg.locator('#cutbar [data-act=paste]')
            ok1 = paste.is_disabled() and (paste.get_attribute('title') or '').startswith(NOPE) and 'コピー' in (paste.get_attribute('data-why') or '')
            bb = paste.bounding_box(); pg.mouse.move(bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2)
            pg.wait_for_timeout(150); hint = pg.inner_text('#whyTip') if pg.locator('#whyTip:not([hidden])').count() else ''
            hint0 = pg.inner_text('#cutHint')
            pg.evaluate("() => MITTLER_EDITOR.select('se')"); pg.keyboard.press('Control+c'); pg.wait_for_timeout(150)
            check(ok1 and hint.startswith(NOPE) and NOPE not in hint0 and not paste.is_disabled() and not (paste.get_attribute('title') or '').startswith(NOPE),
                  f'ボタン：押せないボタンに理由（ツールチップと、マウスのそばの札「{hint[:24]}…」。下の説明の欄には出さない）。押せるようになると理由が外れる')
            # 数の欄の横のコマ番号
            pg.evaluate("() => MITTLER_EDITOR.select('se')"); pg.wait_for_selector('#sel .fhint')
            h = pg.eval_on_selector_all('#sel .fhint', 'els => els.map(e => e.textContent)')
            pg.fill('#sel input[data-k=start]', '1'); pg.keyboard.press('Tab'); pg.wait_for_timeout(400)
            h2 = pg.eval_on_selector_all('#sel .fhint', 'els => els.map(e => e.textContent)')
            check(h[:2] == ['f15', '30 コマ'] and h2[:2] == ['f30', '30 コマ'], f'数の欄：「開始」「長さ」の横にコマ番号・コマ数（{h[:2]} → 開始を 1 秒に → {h2[:2]}）')
            pg.evaluate("() => { document.activeElement && document.activeElement.blur(); }"); pg.keyboard.press('Control+z')  # 欄の外で（欄の中の Ctrl+Z は欄の文字の取り消し）
            # 短い作品でも幅いっぱい
            wfit = pg.evaluate("() => { const w = document.getElementById('lanesWrap'), l = document.getElementById('lanes'); return [w.clientWidth, l.getBoundingClientRect().width, MITTLER_EDITOR.pps]; }")
            check(wfit[1] >= wfit[0] - 2 and wfit[2] > 100, f'拡大：3 秒の作品でもタイムラインが幅いっぱい（幅 {wfit[0]}px・中身 {wfit[1]:.0f}px・{wfit[2]:.0f}px/秒）')
            # Ctrl+S
            pg.wait_for_function("() => !MITTLER_EDITOR.saveTimer && !MITTLER_EDITOR.saving", timeout=20000)
            pg.evaluate("() => { document.activeElement && document.activeElement.blur(); setStatus(''); }"); pg.keyboard.press('Control+s'); pg.wait_for_timeout(200)
            s1 = pg.inner_text('#status')
            pg.evaluate("() => MITTLER_EDITOR.change(() => { MITTLER_EDITOR.tl.tracks.find(t => t.kind === 'video').clips[0].label = 'red3'; })")
            pg.keyboard.press('Control+s'); pg.wait_for_function("() => !MITTLER_EDITOR.saveTimer && !MITTLER_EDITOR.saving", timeout=20000); pg.wait_for_timeout(200)
            saved = json.loads(tlf.read_text(encoding='utf-8'))
            check('保存済み' in s1 and next(t for t in saved['tracks'] if t['kind'] == 'video')['clips'][0]['label'] == 'red3' and '保存しました' in pg.inner_text('#status'),
                  f'Ctrl+S：直しが無ければ「{s1[:8]}…」、あれば待っている保存をすぐ流す')
            ctx.close()

            # ---- アイコン（2026-11-14〜。前の絵文字と、絵文字の書体が無い環境の ?noemoji=1 の代わり）：上のバー・再生の操作のボタンにアイコンが出る ----
            ctx, pg = page(1600, 'dark')
            ids = ['assetToggle', 'durBtn', 'sizeBtn', 'stillBtn', 'reloadBtn', 'undo', 'redo', 'annotBtn', 'masterBtn', 'snapBtn', 'shyBtn', 'toStart', 'stepBack', 'play', 'stepFwd', 'toEnd']
            vis = pg.evaluate("""ids => ids.map(id => { const b = document.getElementById(id), i = b && b.querySelector('.ic'); if (!i) return id + ':なし';
              const r = i.getBoundingClientRect(), cs = getComputedStyle(i); return (r.width >= 13 && r.width <= 16 && r.height === r.width && /icons\\//.test(cs.webkitMaskImage || cs.maskImage)) ? '' : id + ':' + r.width + ' ' + (cs.webkitMaskImage || cs.maskImage); }).filter(Boolean)""", ids)
            # 型の絵（SVG）が読めた（ブラウザが返事を受けた）か：使っている名前ぜんぶ
            names = pg.evaluate("() => [...new Set([...document.querySelectorAll('.ic')].map(i => i.dataset.ic))]")
            bad = pg.evaluate("async names => { const out = []; for (const n of names) { const r = await fetch('icons/' + n + '.svg'); const t = await r.text(); if (!r.ok || !/^image\\/svg\\+xml/.test(r.headers.get('content-type') || '') || !t.includes('<svg')) out.push(n); } return out; }", names)
            lb = pg.evaluate("() => ['stillBtn', 'reloadBtn', 'snapBtn', 'shyBtn', 'annotBtn', 'masterBtn'].filter(id => { const l = document.querySelector('#' + id + ' .lb'); return !l || l.offsetWidth === 0; })")
            check(not vis and not bad and not lb and len(names) >= 20, f'アイコン：上のバー・再生の操作の {len(ids)} 個にアイコン（13〜16px・型の絵 icons/*.svg）、使っている {len(names)} 種の SVG が読める（image/svg+xml）、幅 1600 では名前も出る {vis} {bad} {lb}')
            ctx.close()

            # ---- 崩れ：上のバーのボタンがはみ出さない・重ならない・縦に折れない ----
            for w in (1600, 1280, 900):
                ctx, pg = page(w, 'dark')
                r = pg.evaluate("""() => { const bar = document.getElementById('bar').getBoundingClientRect();
                  const els = [...document.querySelectorAll('#bar > button, #bar > span > button, #bar > .zoom, #bar > #file')].filter(e => e.offsetWidth > 0).map(e => [e.id || e.className, e.getBoundingClientRect()]);
                  const out = els.filter(([, b]) => b.right > bar.right + 1 || b.left < bar.left - 1 || b.height > 34).map(x => x[0]);
                  const lap = []; for (let i = 0; i < els.length; i++) for (let j = i + 1; j < els.length; j++) { const a = els[i][1], b = els[j][1]; if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) lap.push(els[i][0] + '×' + els[j][0]); }
                  const tp = document.getElementById('transport').getBoundingClientRect(), st = document.getElementById('stage').getBoundingClientRect();
                  const tin = [...document.querySelectorAll('#transport button, #transport select, #cutNow')].filter(e => e.offsetWidth > 0 && (e.getBoundingClientRect().right > st.right + 1 || e.getBoundingClientRect().left < st.left - 1)).map(e => e.id);
                  return { out, lap, tin, barH: bar.height, sx: document.documentElement.scrollWidth - innerWidth }; }""")
                check(not r['out'] and not r['lap'] and not r['tin'] and r['barH'] <= 44 and r['sx'] <= 0, f"崩れ（幅 {w}）：上のバー・再生の操作がはみ出さない・重ならない（バーの高さ {r['barH']:.0f}px）{r['out']} {r['lap']} {r['tin']}")
                ctx.close()
            br.close()
    finally:
        srv.quit()
    check(not errors, 'ページのエラーなし' + ('' if not errors else ': ' + ' | '.join(errors[:5])))


w = opt('--work')
if w:
    Path(w).mkdir(parents=True, exist_ok=True); main(Path(w))
else:
    with tempfile.TemporaryDirectory(prefix='mittler_smoke_ui_') as td:
        main(Path(td))
print('ALL OK' if not fails else f'FAIL {len(fails)}')
sys.exit(1 if fails else 0)
