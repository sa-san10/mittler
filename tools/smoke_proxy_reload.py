"""再生用の動画が一度読めなかったあとの立ち直りと、知らせとログの窓の確かめ（ヘッドレス、localhost だけ。描画の python で流す）。試しの作品を自分で作って消す。
  <描画の python（Playwright 入り）> -X utf8 tools\\smoke_proxy_reload.py
確かめること：
1. 再生用の動画が壊れている（作っている途中など）と、再生は描いたコマで続き、上のバーに注意（error 4 など）が出る
2. 上のバーの注意を押すと「知らせとログ」の窓が出て、全文と最近の記録（動画の error）が選べる形で見える・コピーでページのエラーにならない
3. 正しい動画に置きかわると（同じ名前）、読み直して再生用の動画で流れる（前は同じ名前のままでは二度と読み直さなかった）
4. make_proxy.py は書き終わるまで別の名前に書く（作っている途中の .webm が見えない）
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

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
fails, errors = [], []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


work = Path(tempfile.mkdtemp(prefix='mittler_pxr_'))
proj = work / 'pxr'
r = subprocess.run(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node', str(ROOT / 'tools' / 'new_project.js'), str(proj), '--duration', '6', '--no-git', '--lang', 'ja'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
if r.returncode:
    sys.exit('new_project 失敗: ' + r.stdout + r.stderr)
tlf = next(proj.glob('*.cut.json'))
tl = json.loads(tlf.read_text(encoding='utf-8'))
tl.update(width=320, height=180, fps=10)
tl['preview'] = {'proxy': 'work/proxy/clip.webm'}
tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
pdir = proj / 'work' / 'proxy'; pdir.mkdir(parents=True, exist_ok=True)
good = work / 'good.webm'
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=10:d=6', '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '40', '-deadline', 'realtime', str(good)], check=True)
(pdir / 'clip.webm').write_bytes(good.read_bytes()[:3000])  # 作っている途中のように、頭だけの壊れたファイル

srv = subprocess.Popen(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'serve', str(tlf), '--render-python', PY, '--lang', 'ja'],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=dict(os.environ, MITTLER_NO_REVEAL='1'), text=True, encoding='utf-8', errors='replace')
url = srv.stdout.readline().strip()
try:
    if not url.startswith('http://127.0.0.1:'):
        raise SystemExit('サーバーが起動しない: ' + url)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required'])
        ctx = b.new_context(viewport={'width': 1400, 'height': 900})
        ctx.grant_permissions(['clipboard-read', 'clipboard-write'], origin=url.split('/editor/')[0])
        pg = ctx.new_page()
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.goto(url); pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl', timeout=60000)
        pg.wait_for_function("() => { const v = document.getElementById('proxy'); return v.error || v.readyState >= 1; }", timeout=30000)
        pg.click('#play'); time.sleep(3)
        st = pg.inner_text('#status')
        check('再生用の動画を再生できません' in st, f'1 壊れた再生用の動画では、上のバーに注意（{st[:60]}）')
        pg.click('#play'); time.sleep(0.5)  # 止める（止めると注意は消える）
        pg.click('#play'); time.sleep(3)  # もう一度：まだ壊れているので注意が出る
        pg.evaluate("document.getElementById('status').click()"); pg.wait_for_selector('#logPanel:not([hidden])', timeout=5000)
        now, log = pg.inner_text('#logPanel .lgNow'), pg.inner_text('#logPanel .lgLog')
        check('再生用の動画を再生できません' in now and 'error' in log, f'2 知らせとログの窓：全文と記録（記録 {len(log.splitlines())} 行）')
        us = pg.evaluate("getComputedStyle(document.querySelector('#logPanel .lgLog')).userSelect")
        pg.click('#logPanel [data-lg=copy]'); time.sleep(0.4)
        clip = pg.evaluate('navigator.clipboard.readText()')
        check(us in ('text', 'auto') and '再生用の動画を再生できません' in clip, f'2 選べる（{us}）・コピーで全文と記録がクリップボードに')
        pg.click('#logPanel [data-lg=close]')
        pg.click('#play'); time.sleep(0.5)  # 止める
        tmp = pdir / 'clip.webm.new'
        tmp.write_bytes(good.read_bytes()); os.replace(tmp, pdir / 'clip.webm')  # 作り終わって置きかわった
        time.sleep(2)
        _b = urllib.request.urlopen(url.split('/editor/')[0] + '/project/work/proxy/clip.webm', timeout=10).read(); print('served', len(_b), 'good', good.stat().st_size)
        # 読み直しは、ファイルが変わった知らせか、次の再生で起きる。ここは再生で読み直す道を確かめるため、壊れた状態のまま知らせを待たずに再生する道も通る
        pg.evaluate('window.MITTLER_EDITOR.seek(1.0)')
        pg.click('#play'); time.sleep(3)
        v = pg.evaluate("() => { const v = document.getElementById('proxy'); return {err: v.error && v.error.code, t: v.currentTime, paused: v.paused, rs: v.readyState}; }")
        st = pg.inner_text('#status')
        check(not v['err'] and not v['paused'] and v['t'] > 1.5 and '再生用の動画を再生できません' not in st, f'3 置きかわった動画を読み直して流れる（{v}・上のバー「{st[:30]}」）')
        if v['err'] or v['paused']:
            print('log:', pg.evaluate('window.MITTLER_EDITOR.logBuf.slice(-12).join("\\n")'))
        pg.click('#play')
        check(not errors, f'ページのエラーなし（{errors[:2]}）')
        b.close()
    # 4. make_proxy.py：別の名前に書いてから置きかえる
    src = work / 'src.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=10:d=2', '-f', 'lavfi', '-i', 'sine=d=2', '-shortest', '-c:v', 'libx264', '-c:a', 'aac', str(src)], check=True)
    p = subprocess.Popen([PY, '-X', 'utf8', str(ROOT / 'tools' / 'make_proxy.py'), str(tlf), str(src), '--no-timeline'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    seen_partial_final = False
    while p.poll() is None:
        f = pdir / 'src.webm'
        if f.exists() and any(pdir.glob('src.part*.webm')):
            seen_partial_final = True
        time.sleep(0.05)
    out, err = p.communicate()
    check(p.returncode == 0 and (pdir / 'src.webm').is_file() and not seen_partial_final and not list(pdir.glob('*.part*')),
          f'4 make_proxy.py は書き終わってから置きかえる（{out.strip()[:80]}）')
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
    shutil.rmtree(work, ignore_errors=True)
print('smoke_proxy_reload: ' + ('OK' if not fails else f'FAIL {len(fails)}'))
sys.exit(1 if fails else 0)
