"""キャラ設定のプリセット（presets/characters）を作品に写す確認（ヘッドレス、localhost だけ）。試し用の作品で流す。
  <Playwright の python> -X utf8 tools\\smoke_presets.py <URL> --timeline <作品>\\<名前>.cut.json [--id kurochan]
確かめること：「キャラ」タブの「＋プリセットから」に一覧 → 押すと characters.json に入り、立ち絵（差分も）・設定の文書・声が写る。
"""
import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(); ap.add_argument('url'); ap.add_argument('--timeline', required=True); ap.add_argument('--id', default='kurochan'); ap.add_argument('--shot')
a = ap.parse_args()
if not a.url.startswith(('http://127.0.0.1:', 'http://localhost:')): sys.exit('localhost only')
tlf = Path(a.timeline); proj = tlf.parent; tl = json.loads(tlf.read_text(encoding='utf-8')); root = (proj / tl.get('root', '.')).resolve()
cf = proj / tl.get('characters', 'characters.json'); before = cf.read_bytes()
fails, errors = [], []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={'width': 1600, 'height': 940})
    pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(a.url)
    pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl && window.MITTLER_EDITOR.assets', timeout=60000)
    pg.click('#assetTabs button[data-tab="chars"]'); pg.wait_for_selector('#charPreset'); pg.click('#charPreset')
    pg.wait_for_selector('#assetPreview .pcell', timeout=20000)
    n = pg.locator('#assetPreview .pcell').count()
    check(n >= 20, f'プリセットの一覧（{n} 人）')
    pg.click(f'#assetPreview .pcell[data-preset="{a.id}"]')
    t0 = time.time(); c = None
    while time.time() - t0 < 20:
        d = json.loads(cf.read_text(encoding='utf-8')); c = next((x for x in d.get('characters', []) if x['id'] == a.id), None)
        if c:
            break
        time.sleep(0.3)
    check(c is not None, f'characters.json に入った（{c and c["name"]}）')
    if c:
        imgs = [c['image']] + list((c.get('images') or {}).values())
        check(all((root / x).is_file() for x in imgs if x), f'立ち絵が写った（{imgs}）')
        check(all((proj / x).is_file() for x in c.get('profile_doc', [])), f"設定の文書が写った（{c.get('profile_doc')}）")
        check(bool(c.get('profile')) and ((c.get('tts') or {}).get('gemini') or {}).get('voice') in ('Kore', 'Charon', 'Puck', None), f"性格・声（{((c.get('tts') or {}).get('gemini') or {}).get('voice')}）")
    pg.wait_for_selector(f'#assetPreview .pcell.have[data-preset="{a.id}"]', timeout=20000)
    check(True, '一覧で「入っている」になる')
    pg.click('#assetTabs button[data-tab="chars"]')
    pg.wait_for_selector(f'#assetBody .char[data-char="{a.id}"]', timeout=20000)
    check(True, '「キャラ」タブに出る')
    if a.shot:
        pg.click('#charPreset'); pg.wait_for_selector('#assetPreview .pcell'); pg.screenshot(path=a.shot)
    b.close()

cf.write_bytes(before)  # 作品の characters.json を最初に戻す（写した画像・文書は残る）
check(not errors, 'コンソールエラーなし' + ('' if not errors else ': ' + ' | '.join(errors[:5])))
sys.exit(1 if fails else 0)
