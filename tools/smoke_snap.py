"""タイムラインのスナップ（🧲）の動作確認（ヘッドレス、localhost だけ）。試し用の作品で流す。最後にタイムラインを最初に戻す。
  <Playwright の python> -X utf8 tools\\smoke_snap.py <URL> --timeline <作品>\\<名前>.cut.json --a <クリップ> --b <クリップ> [--shot 画像]
作品には同じトラックに A（0 秒から）と B（A より後ろ、A とのあいだが空いている）、ビートとカットのメタデータが要る。
確かめること：B を動かすと A の終わりに吸いつく（コマにそろえない、ぴったり）→ Alt を押すと吸いつかない → 右端を拍に吸いつかせる →
🧲 オフで吸いつかない → S キーでオンに戻る → ▾ で拍を外すと拍に吸いつかない → 再生位置のドラッグがクリップの頭・カットの境目に吸いつく → 黄色い線が出て消える。
"""
import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(); ap.add_argument('url'); ap.add_argument('--timeline', required=True); ap.add_argument('--a', required=True); ap.add_argument('--b', required=True); ap.add_argument('--shot')
a = ap.parse_args()
if not a.url.startswith(('http://127.0.0.1:', 'http://localhost:')): sys.exit('localhost only')
tlf = Path(a.timeline); orig = tlf.read_bytes(); fails, errs = [], []


def check(c, m):
    print(('OK   ' if c else 'FAIL ') + m, flush=True); (None if c else fails.append(m))


def clip(cid):
    return next(c for t in json.loads(tlf.read_text(encoding='utf-8'))['tracks'] for c in t.get('clips', []) if c['id'] == cid)


def wait(cid, cond, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            c = clip(cid)
            if cond(c): return c
        except Exception: pass
        time.sleep(0.2)
    return clip(cid)


try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True); pg = b.new_page(viewport={'width': 1600, 'height': 940})
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.add_init_script("try { localStorage.removeItem('cc.snap'); } catch (e) {}")
        pg.goto(a.url); pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl', timeout=120000)
        pg.evaluate('() => { setZoom(150); document.getElementById("lanesWrap").scrollLeft = 0; }'); pg.wait_for_timeout(300)
        S = lambda js: pg.evaluate(js)
        pps = S('() => window.MITTLER_EDITOR.pps'); lx = S('() => document.getElementById("lanes").getBoundingClientRect().left')
        A, B = clip(a.a), clip(a.b); aend = A['start'] + A['dur']
        beats = next(m for m in json.loads(orig)['meta'] if m['kind'] == 'beats')['items']
        X = lambda t: lx + t * pps
        # B を A の終わりの 5px 手前まで動かす → A の終わりにぴったり
        by = pg.locator(f'.clip[data-id="{a.b}"]').bounding_box(); y = by['y'] + by['height'] / 2; x0 = by['x'] + by['width'] / 2
        pg.mouse.move(x0, y); pg.mouse.down(); pg.mouse.move(x0 + (aend - B['start']) * pps + 5, y, steps=6)
        check(S('() => getComputedStyle(document.getElementById("snapLine")).display') == 'block', 'ドラッグ中に黄色い線が出る')
        if a.shot: pg.screenshot(path=a.shot)
        pg.mouse.up()
        c = wait(a.b, lambda c: abs(c['start'] - B['start']) > 1e-6)
        check(abs(c['start'] - aend) < 1e-6, f"B の頭が A の終わり {aend} にぴったり（{c['start']}）")
        check(S('() => getComputedStyle(document.getElementById("snapLine")).display') == 'none', '離すと線が消える')
        pg.keyboard.press('Control+z'); c = wait(a.b, lambda c: abs(c['start'] - B['start']) < 1e-6)
        # Alt を押しながら → 吸いつかない（コマにそろう）
        pg.mouse.move(x0, y); pg.keyboard.down('Alt'); pg.mouse.down(); pg.mouse.move(x0 + (aend - B['start']) * pps + 5, y, steps=6); pg.mouse.up(); pg.keyboard.up('Alt')
        c = wait(a.b, lambda c: abs(c['start'] - B['start']) > 1e-6)
        fps = json.loads(orig).get('fps', 30)
        check(abs(c['start'] - aend) > 1e-3 and abs(c['start'] * fps - round(c['start'] * fps)) < 1e-4, f"Alt で吸いつかない（{c['start']}、コマにそろう）")
        pg.keyboard.press('Control+z'); wait(a.b, lambda c: abs(c['start'] - B['start']) < 1e-6)
        # B の右端を拍の近くへ → 拍にぴったり
        bt = next(t for t, *_ in beats if t > B['start'] + B['dur'] + 0.1)
        by = pg.locator(f'.clip[data-id="{a.b}"]').bounding_box(); gx = by['x'] + by['width'] - 2
        pg.mouse.move(gx, y); pg.mouse.down(); pg.mouse.move(X(bt) - 4, y, steps=6); pg.mouse.up()
        c = wait(a.b, lambda c: abs(c['dur'] - B['dur']) > 1e-6)
        check(abs(c['start'] + c['dur'] - bt) < 1e-6, f"右端が拍 {bt} にぴったり（{c['start'] + c['dur']:.4f}）")
        pg.keyboard.press('Control+z'); wait(a.b, lambda c: abs(c['dur'] - B['dur']) < 1e-6)
        # 🧲 オフ → 吸いつかない、S キーでオン
        pg.click('#snapBtn'); check(not S('() => window.MITTLER_EDITOR.snap.on'), '🧲 でオフ')
        by = pg.locator(f'.clip[data-id="{a.b}"]').bounding_box(); x0 = by['x'] + by['width'] / 2
        pg.mouse.move(x0, y); pg.mouse.down(); pg.mouse.move(x0 + (aend - B['start']) * pps + 5, y, steps=6); pg.mouse.up()
        c = wait(a.b, lambda c: abs(c['start'] - B['start']) > 1e-6); check(abs(c['start'] - aend) > 1e-3, f"オフなら吸いつかない（{c['start']}）")
        pg.keyboard.press('Control+z'); wait(a.b, lambda c: abs(c['start'] - B['start']) < 1e-6)
        pg.mouse.click(lx + 5, S('() => document.getElementById("ruler").getBoundingClientRect().top') + 5)  # フォーカスをタイムラインへ
        pg.keyboard.press('s'); check(S('() => window.MITTLER_EDITOR.snap.on'), 'S キーでオンに戻る')
        # ▾ で拍を外す → 拍に吸いつかない
        pg.click('#snapMenuBtn'); pg.uncheck('#snapMenu [data-snap="beats"]'); pg.mouse.click(10, 10)
        by = pg.locator(f'.clip[data-id="{a.b}"]').bounding_box(); gx = by['x'] + by['width'] - 2
        pg.mouse.move(gx, y); pg.mouse.down(); pg.mouse.move(X(bt) - 4, y, steps=6); pg.mouse.up()
        c = wait(a.b, lambda c: abs(c['dur'] - B['dur']) > 1e-6)
        check(abs(c['start'] + c['dur'] - bt) > 1e-3, f"拍を外すと拍に吸いつかない（{c['start'] + c['dur']:.4f}）")
        pg.keyboard.press('Control+z'); wait(a.b, lambda c: abs(c['dur'] - B['dur']) < 1e-6)
        pg.click('#snapMenuBtn'); pg.check('#snapMenu [data-snap="beats"]'); pg.mouse.click(10, 10)
        # 再生位置のドラッグ：B の頭の 4px 先で → B の頭
        ry = S('() => document.getElementById("ruler").getBoundingClientRect().top') + 6
        pg.mouse.move(X(B['start']) + 4, ry); pg.mouse.down(); pg.mouse.move(X(B['start']) + 3, ry); pg.mouse.up()
        t = S('() => window.MITTLER_EDITOR.t'); check(abs(t - B['start']) < 1e-6, f"再生位置が B の頭 {B['start']} に吸いつく（{t}）")
        cuts = next(m for m in json.loads(orig)['meta'] if m['kind'] == 'cuts')['items']; ct = cuts[1]['start']
        pg.mouse.move(X(ct) - 5, ry); pg.mouse.down(); pg.mouse.move(X(ct) - 4, ry); pg.mouse.up()
        t = S('() => window.MITTLER_EDITOR.t'); check(abs(t - ct) < 1e-6, f"再生位置がカットの境目 {ct} に吸いつく（{t}）")
        b.close()
finally:
    tlf.write_bytes(orig)
check(not errs, 'エラーなし' + ('' if not errs else ': ' + ' | '.join(errs[:3])))
sys.exit(1 if fails else 0)
