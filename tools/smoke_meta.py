"""メタデータのタブ（歌詞・ト書き・セリフなどをテキストボックスで直す）の動作確認（ヘッドレス、localhost だけ）。
  <Playwright の python> -X utf8 tools\\smoke_meta.py <URL> --timeline <*.cut.json> [--shot 画像]
確かめること：タブが並ぶ → 歌詞の文字を直すとファイルに入る → 「＋この時刻に足す」で項目が増える → 時刻を直すと並び直す → × で消える
→ 取り消しで全部戻る（ファイルが最初と同じ中身）。
"""
import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(); ap.add_argument('url'); ap.add_argument('--timeline', required=True); ap.add_argument('--shot')
a = ap.parse_args()
if not a.url.startswith(('http://127.0.0.1:', 'http://localhost:')): sys.exit('localhost only')
tlf = Path(a.timeline); orig = tlf.read_bytes(); first = json.loads(orig.decode('utf-8'))
fails, errors = [], []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


def saved(pg):
    pg.wait_for_function("() => !window.MITTLER_EDITOR.saveTimer && !window.MITTLER_EDITOR.saving", timeout=30000); time.sleep(0.4)
    return json.loads(tlf.read_text(encoding='utf-8'))


def meta(tl, kind):
    return next(m for m in tl['meta'] if m['kind'] == kind)


with sync_playwright() as p:
    b = p.chromium.launch(headless=True, ignore_default_args=['--hide-scrollbars'])
    pg = b.new_page(viewport={'width': 1500, 'height': 900})
    pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else (print('[log]', m.text) if 'meta-time' in m.text else None))
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(a.url)
    pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl', timeout=30000)
    pg.evaluate('window.MITTLER_DEBUG_META = true')
    pg.click('#paneTabs button[data-p="meta"]')
    tabs = pg.eval_on_selector_all('#metaTabs .tab', 'els => els.map(e => e.textContent)')
    check(len(tabs) >= 2, f'タブ {tabs}')
    pg.click('#metaTabs .tab:has-text("歌詞")')
    n0 = len(meta(first, 'lyrics')['items'])
    rows = pg.eval_on_selector_all('#metaBody .mrow', 'els => els.length'); check(rows == n0, f'歌詞の項目が並ぶ（{rows}）')
    # 文字を直す
    ta = pg.locator('#metaBody .mrow[data-i="0"] textarea'); ta.fill('テストで直した歌詞'); ta.dispatch_event('change')
    tl = saved(pg); check(meta(tl, 'lyrics')['items'][0]['text'] == 'テストで直した歌詞', '歌詞の文字を直すとファイルに入る')
    # この時刻に足す
    t_add = round((meta(first, 'lyrics')['items'][-1]['end'] + 0.5) * 24) / 24
    pg.evaluate(f'window.MITTLER_EDITOR.seek({t_add})'); pg.click('#mAdd')
    tl = saved(pg); items = meta(tl, 'lyrics')['items']
    check(len(items) == n0 + 1 and any(abs(x['start'] - t_add) < 1e-6 for x in items), f'＋この時刻に足すで増える（{len(items)}）')
    i_new = next(i for i, x in enumerate(items) if abs(x['start'] - t_add) < 1e-6)
    pg.locator(f'#metaBody .mrow[data-i="{i_new}"] textarea').fill('足した行'); pg.locator(f'#metaBody .mrow[data-i="{i_new}"] textarea').dispatch_event('change')
    tl = saved(pg); check(any(x.get('text') == '足した行' for x in meta(tl, 'lyrics')['items']), '足した行に文字を入れられる')
    # 時刻を直す（いちばん前へ動かすと並び直す）
    ms = pg.locator(f'#metaBody .mrow[data-i="{i_new}"] .ms'); me = pg.locator(f'#metaBody .mrow[data-i="{i_new}"] .me')
    me.fill('0.5'); ms.fill('0.1'); ms.dispatch_event('change')
    tl = saved(pg); its = meta(tl, 'lyrics')['items']
    check(its[0].get('text') == '足した行' and abs(its[0]['start'] - 0.1) < 1e-6, f'時刻を直すと並び直す {[(x["start"], x["end"], x.get("text")) for x in its]}')
    if a.shot:
        pg.screenshot(path=a.shot)
    # 消す
    pg.locator('#metaBody .mrow[data-i="0"] .mdel').click()
    tl = saved(pg); check(len(meta(tl, 'lyrics')['items']) == n0, '× で消える')
    # 現在の時刻の項目に印が付く
    it1 = meta(first, 'lyrics')['items'][1]
    pg.evaluate(f"window.MITTLER_EDITOR.seek({(it1['start'] + it1['end']) / 2})")
    now = pg.eval_on_selector_all('#metaBody .mrow.now', 'els => els.map(e => +e.dataset.i)'); check(now == [1], f'今の時刻の項目に印（{now}）')
    # 取り消しで全部戻す
    while pg.evaluate('window.MITTLER_EDITOR.undo.length') > 0:
        pg.click('#undo')
    tl = saved(pg)
    b.close()

check(tl == first, 'タイムラインの中身が最初と同じ（取り消しで全部戻った）')
if json.loads(tlf.read_text(encoding='utf-8')) != first:
    tlf.write_bytes(orig); print('（ファイルを最初の中身に戻した）')
check(not errors, 'コンソールエラーなし' + ('' if not errors else ': ' + ' | '.join(errors[:5])))
sys.exit(1 if fails else 0)
