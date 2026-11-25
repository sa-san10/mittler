"""画面への書き込み（✏️）をどの AI にも渡せるかの確かめ（ヘッドレス、localhost だけ。描画の python で流す）。試しの作品を自分で作って、終わったら消す。
  <描画の python（Playwright 入り）> -X utf8 tools\\smoke_annotate.py
確かめること：
1. 止めた画面に描いて「AI に渡す」→ .mittler/annotations/<id>/ に after.jpg・annotation.json
2. 描いた画面の場所と頼みの文がクリップボードに入る（ほかの AI のチャットに貼る用）
3. state.json の annotations_pending に載る（フックの無い AI が見つける）・image は実在する
4. フック（tools/mittler_state.py。Claude Code）が添えると delivered になり、annotations_pending から外れる
5. ボタンの名前は「AI に渡す」（Claude Code に限らない）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
fails, errors = [], []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


work = Path(tempfile.mkdtemp(prefix='mittler_annot_'))
proj = work / 'annot'
r = subprocess.run(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node', str(ROOT / 'tools' / 'new_project.js'), str(proj), '--duration', '3', '--no-git', '--lang', 'ja'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
if r.returncode:
    sys.exit('new_project 失敗: ' + r.stdout + r.stderr)
tlf = next(proj.glob('*.cut.json'))
(proj / 'assets' / 'images').mkdir(parents=True, exist_ok=True)
Image.new('RGB', (320, 180), (40, 120, 200)).save(proj / 'assets' / 'images' / 'bg.png')
tl = json.loads(tlf.read_text(encoding='utf-8'))
tl.update(width=320, height=180, fps=10)
next(t for t in tl['tracks'] if t.get('kind') == 'video')['clips'] = [{'id': 'bg', 'type': 'image', 'start': 0, 'dur': 3, 'src': 'assets/images/bg.png'}]
tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
stf = proj / '.mittler' / 'state.json'

log = open(work / 'server.log', 'w', encoding='utf-8', errors='replace')
srv = subprocess.Popen(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'serve', str(tlf), '--render-python', PY, '--lang', 'ja'],
                       stdout=subprocess.PIPE, stderr=log, env=dict(os.environ, MITTLER_NO_REVEAL='1'), text=True, encoding='utf-8', errors='replace')
url = srv.stdout.readline().strip()


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
        ctx = b.new_context(viewport={'width': 1400, 'height': 900})
        ctx.grant_permissions(['clipboard-read', 'clipboard-write'], origin=url.split('/editor/')[0])
        pg = ctx.new_page()
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.goto(url)
        pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl', timeout=60000)
        pg.evaluate('window.MITTLER_EDITOR.seek(1.0)')
        pg.wait_for_function("() => { const S = window.MITTLER_EDITOR, i = document.getElementById('frameImg'); return !i.hidden && S.exactT === 1.0; }", timeout=120000)
        pg.click('#annotBtn'); pg.wait_for_timeout(400)
        send = pg.locator('[data-act="send"]')
        check(send.inner_text().strip() == 'AI に渡す', f'5 ボタンの名前（{send.inner_text().strip()}）')
        box = pg.locator('#screen').bounding_box()
        pg.mouse.move(box['x'] + box['width'] * 0.3, box['y'] + box['height'] * 0.3); pg.mouse.down()
        pg.mouse.move(box['x'] + box['width'] * 0.6, box['y'] + box['height'] * 0.6, steps=8); pg.mouse.up()
        send.click()
        pg.wait_for_function("() => /annotations|書き込みを保存/.test(document.getElementById('status').textContent)", timeout=30000)
        anns = sorted((proj / '.mittler' / 'annotations').glob('*/annotation.json'))
        check(len(anns) == 1 and (anns[0].parent / 'after.jpg').is_file(), f'1 書き込みを保存（{[a.parent.name for a in anns]}）')
        clip = pg.evaluate('navigator.clipboard.readText()')
        check('after.jpg' in clip and str(proj) in clip, f'2 クリップボードに描いた画面の場所と頼みの文（{clip[:80]}…）')
        s = state(lambda s: s.get('annotations_pending'))
        pend = s.get('annotations_pending') or []
        check(len(pend) == 1 and Path(pend[0]['image']).is_file() and Path(pend[0]['annotation']).is_file() and abs(pend[0]['t'] - 1.0) < 1e-6,
              f"3 state.json の annotations_pending（{[(x.get('id'), x.get('t')) for x in pend]}）")
        h = subprocess.run([PY, '-X', 'utf8', str(ROOT / 'tools' / 'mittler_state.py'), str(proj)], capture_output=True, text=True, encoding='utf-8')
        a = json.loads(anns[0].read_text(encoding='utf-8')) if anns else {}
        check('書き込んだ画面' in h.stdout and a.get('delivered') is True, '4 フックが添えて delivered にする')
        pg.evaluate('window.MITTLER_EDITOR.seek(2.0)')
        s = state(lambda s: not s.get('annotations_pending') and (s.get('time') or {}).get('t') == 2.0)
        check(not s.get('annotations_pending'), '4 渡したあとは annotations_pending から外れる')
        check(not errors, f'ページのエラーなし（{errors[:2]}）')
        b.close()
finally:
    try:
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
print('smoke_annotate: ' + ('OK' if not fails else f'FAIL {len(fails)}'))
sys.exit(1 if fails else 0)
