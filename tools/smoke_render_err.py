"""描画のエラーの箱の確かめ（ヘッドレス、localhost だけ。描画の python で流す）。試しの作品を自分で作って、終わったら消す。
  <描画の python（Playwright 入り）> -X utf8 tools\\smoke_render_err.py [--shot <PNG>]（箱が出た画面を残す）
確かめること：
1. 素材が無い画像のクリップの時刻で止める → 画面の上にエラーの箱が出て、見出しに無いファイルの名前・本文に全文（選べる）
2. state.json の render_error に全文 → フック（tools/mittler_state.py）の要約に「描画のエラー」の 1 行
3. 「コピー」を押してもページのエラーにならない（クリップボードが使えないときは本文を選ぶ）
4. 「閉じる」で隠れ、同じエラーではもう出ない
5. 素材を置いて読み直すと、箱が消えて絵が出る・state.json から render_error が消える
6. 書き出しが失敗したときの窓：エラーの全文に「コピー」のボタン・選んだ文字と開いた「詳細」が窓の更新で消えない
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
fails, errors = [], []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


work = Path(tempfile.mkdtemp(prefix='mittler_rerr_'))
proj = work / 'rerr'
r = subprocess.run(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node', str(ROOT / 'tools' / 'new_project.js'), str(proj), '--duration', '4', '--no-git', '--lang', 'ja'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
if r.returncode:
    sys.exit('new_project 失敗: ' + r.stdout + r.stderr)
tlf = next(proj.glob('*.cut.json'))
tl = json.loads(tlf.read_text(encoding='utf-8'))
tl.update(width=320, height=180, fps=10)
vid = next(t for t in tl['tracks'] if t.get('kind') == 'video')
vid['clips'] = [{'id': 'img_missing', 'type': 'image', 'start': 0, 'dur': 4, 'src': 'assets/images/gen/not_yet.png', 'label': 'まだ無い絵'}]
tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

env = dict(os.environ, MITTLER_NO_REVEAL='1')
log = open(work / 'server.log', 'w', encoding='utf-8', errors='replace')
srv = subprocess.Popen(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'serve', str(tlf), '--render-python', PY, '--lang', 'ja'],
                       stdout=subprocess.PIPE, stderr=log, env=env, text=True, encoding='utf-8', errors='replace')
url = srv.stdout.readline().strip()
stf = proj / '.mittler' / 'state.json'


def state(pred, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s = json.loads(stf.read_text(encoding='utf-8'))
            if pred(s):
                return s
        except (OSError, ValueError):
            pass
        time.sleep(0.3)
    return json.loads(stf.read_text(encoding='utf-8')) if stf.is_file() else {}


try:
    if not url.startswith('http://127.0.0.1:'):
        raise SystemExit('サーバーが起動しない: ' + url)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={'width': 1400, 'height': 900})
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.goto(url)
        pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl', timeout=60000)
        pg.evaluate('window.MITTLER_EDITOR.seek(1.0)')
        pg.wait_for_selector('#renderErr:not([hidden])', timeout=120000)
        if '--shot' in sys.argv:
            pg.screenshot(path=sys.argv[sys.argv.index('--shot') + 1])
        title = pg.inner_text('#reTitle'); body = pg.inner_text('#reText')
        check('not_yet.png' in title and 'assets' in title, f'1 見出しに無いファイルの名前（{title}）')
        check('FileNotFoundError' in body and 'Traceback' in body, f'1 本文にエラーの全文（{len(body)} 字）')
        us = pg.evaluate("getComputedStyle(document.getElementById('reText')).userSelect")
        check(us in ('text', 'auto'), f'1 本文は選べる（user-select: {us}）')
        check(pg.evaluate("document.getElementById('screen').classList.contains('hasErr')"), '1 画面の前の絵は薄くなる')
        s = state(lambda s: (s.get('render_error') or {}).get('text'))
        re_ = s.get('render_error') or {}
        check('not_yet.png' in re_.get('text', '') and abs((re_.get('t') or -1) - 1.0) < 1e-6, f"2 state.json の render_error（t={re_.get('t')}）")
        h = subprocess.run([PY, '-X', 'utf8', str(ROOT / 'tools' / 'mittler_state.py'), str(proj)], capture_output=True, text=True, encoding='utf-8')
        check('描画のエラー' in h.stdout and 'not_yet.png' in h.stdout, '2 フックの要約に描画のエラーの 1 行')
        pg.click('#reCopy'); time.sleep(0.5)
        # 6. 書き出しが失敗したときの窓：エラーの全文に「コピー」のボタン・選んだ文字が次の更新で消えない・開いた「詳細」が閉じない
        pg.click('#exportBtn'); pg.wait_for_selector('#exportPanel:not([hidden]) #xName')
        pg.click('#exportPanel [data-x=start]')
        pg.wait_for_selector('#exportPanel pre.xerr', state='attached', timeout=300000)
        check(pg.locator('#exportPanel .xcopy').count() >= 1, '6 書き出しのエラーの全文に「コピー」のボタン')
        pg.evaluate("() => { const d = document.querySelector('#exportPanel details.xdet'); d.open = true; const pre = d.querySelector('pre.xerr'), sel = getSelection(), r = document.createRange(); r.selectNodeContents(pre); sel.removeAllRanges(); sel.addRange(r); }")
        time.sleep(4)  # 書き出しの窓は進み具合を聞いて描き直す
        kept = pg.evaluate("() => { const d = document.querySelector('#exportPanel details.xdet'), pre = d && d.querySelector('pre.xerr'), sel = getSelection(); return !!(d && d.open && pre && sel.rangeCount && pre.contains(sel.anchorNode) && String(sel).includes('FileNotFoundError')); }")
        check(kept, '6 選んだエラーの文字と開いた「詳細」が、窓の更新で消えない')
        pg.click('#exportPanel .xcopy'); time.sleep(0.5)
        check(not errors, f'6 書き出しのエラーの「コピー」でページのエラーなし（{errors[:2]}）')
        pg.click('#exportPanel [data-x=again]'); pg.wait_for_selector('#exportPanel #xName')
        check(pg.locator('#exportPanel #xName').count() == 1, '6 「戻る」で設定の窓に戻る')
        pg.evaluate("() => { document.getElementById('exportPanel').hidden = true; }")
        check(not errors, f'3 「コピー」でページのエラーなし（{errors[:2]}）')
        pg.click('#reClose')
        check(pg.evaluate("document.getElementById('renderErr').hidden"), '4 「閉じる」で隠れる')
        pg.evaluate('window.MITTLER_EDITOR.seek(2.0)'); time.sleep(3)
        check(pg.evaluate("document.getElementById('renderErr').hidden"), '4 同じエラーでは、もう出ない')
        # 素材を置く → 読み直す
        (proj / 'assets' / 'images' / 'gen').mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (320, 180), (40, 120, 200)).save(proj / 'assets' / 'images' / 'gen' / 'not_yet.png')
        pg.evaluate("document.getElementById('reload') ? document.getElementById('reload').click() : location.reload()")
        pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl', timeout=60000)
        pg.evaluate('window.MITTLER_EDITOR.seek(1.5)')
        pg.wait_for_function("() => { const S = window.MITTLER_EDITOR, i = document.getElementById('frameImg'); return !i.hidden && S.exactT === 1.5; }", timeout=120000)
        check(pg.evaluate("document.getElementById('renderErr').hidden && !document.getElementById('screen').classList.contains('hasErr')"), '5 素材を置いて読み直すと、箱が消えて絵が出る')
        s = state(lambda s: not s.get('render_error'))
        check(not s.get('render_error'), '5 state.json から render_error が消える')
        check(not errors, f'ページのエラーなし（{errors[:2]}）')
        b.close()
finally:
    try:
        import urllib.request
        tok = url.split('token=')[1].split('&')[0]
        urllib.request.urlopen(urllib.request.Request(url.split('/editor/')[0] + '/api/quit', data=b'{}', method='POST', headers={'X-Mittler-Token': tok}), timeout=10)
    except Exception as e:  # noqa: BLE001
        print('quit 失敗', e)
    try:
        srv.wait(timeout=45)
    except subprocess.TimeoutExpired:
        print('サーバーが止まらない pid', srv.pid)
    log.close()
    shutil.rmtree(work, ignore_errors=True)
print('smoke_render_err: ' + ('OK' if not fails else f'FAIL {len(fails)}'))
sys.exit(1 if fails else 0)
