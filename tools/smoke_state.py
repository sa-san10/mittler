"""編集画面の状態を Claude Code に知らせるしくみの確認（ヘッドレス、localhost だけ）。試し用の作品で流す（assets/images に画像を1枚）。
  <Playwright の python> -X utf8 tools\\smoke_state.py <URL> --timeline <作品>\\<名前>.cut.json
確かめること：画像と字幕を置いて字幕を選ぶ → 作品の状態フォルダ（.mittler。古い作品は .claude-cut）の state.json に選んでいるクリップ・時刻・この時刻にかかっているもの
→ 止めた1コマが current_frame.jpg → フック（tools/mittler_state.py）の要約にそれが出る → 取り消しで最初と同じ。
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(); ap.add_argument('url'); ap.add_argument('--timeline', required=True)
a = ap.parse_args()
if not a.url.startswith(('http://127.0.0.1:', 'http://localhost:')): sys.exit('localhost only')
tlf = Path(a.timeline); proj = tlf.parent; first = json.loads(tlf.read_text(encoding='utf-8'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pyengine'))
from mittler.names import state_dir  # noqa: E402（状態フォルダの名前の決まり。サーバーと同じ）
sdir = state_dir(proj)  # サーバーが起動していれば、もうできている（.mittler。古い作品は .claude-cut）
stf = sdir / 'state.json'
fails, errors = [], []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


def saved(pg):
    pg.wait_for_function("() => !window.MITTLER_EDITOR.saveTimer && !window.MITTLER_EDITOR.saving", timeout=60000); time.sleep(0.4)
    return json.loads(tlf.read_text(encoding='utf-8'))


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


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={'width': 1600, 'height': 940})
    pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(a.url)
    pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl && window.MITTLER_EDITOR.assets && window.MITTLER_STATE', timeout=60000)
    # 画像（0〜3秒）と字幕（1秒〜）を置いて、字幕を選んで 1.5 秒で止める
    pg.click('#assetTabs button[data-tab="images"]'); pg.locator('#assetBody .acell').first.click()
    pg.wait_for_selector('#apImg'); pg.evaluate('window.MITTLER_EDITOR.seek(0)'); pg.click('#apImg'); saved(pg)
    sub = pg.evaluate("window.MITTLER_EDITOR.tl.tracks.find(t => t.kind === 'subtitle').id")
    pg.evaluate(f"window.MITTLER_LANE_DBL(window.MITTLER_EDITOR.tl.tracks.find(t => t.id === '{sub}'), 1.0)")
    pg.fill('#sel [data-k="text"]', 'ここを直したい字幕'); pg.dispatch_event('#sel [data-k="text"]', 'change'); tl = saved(pg)
    sid = next(c['id'] for t in tl['tracks'] for c in t['clips'] if c.get('text') == 'ここを直したい字幕')
    pg.evaluate('window.MITTLER_EDITOR.seek(1.5)')
    pg.wait_for_function("() => { const S = window.MITTLER_EDITOR, i = document.getElementById('frameImg'); return !i.hidden && S.exactT === 1.5 && S.shownVer === S.ver; }", timeout=240000)
    s = state(lambda s: (s.get('selection') or {}).get('id') == sid and s.get('frame_image') and abs(s.get('frame_image_t', -1) - 1.5) < 1e-6)
    sel = s.get('selection') or {}
    check(sel.get('id') == sid and sel.get('type') == 'subtitle' and sel.get('clip', {}).get('text') == 'ここを直したい字幕', f"state.json に選んでいるクリップ（{sel.get('id')}・{sel.get('label')}）")
    check((s.get('time') or {}).get('t') == 1.5 and (s.get('time') or {}).get('frame') == 45 and s.get('open') is True, f"時刻 {s.get('time')}")
    kinds = sorted(c.get('kind') for c in s.get('at_time', []))
    check(kinds == ['subtitle', 'video'], f'この時刻にかかっているもの {[(c.get("track"), c.get("label")) for c in s.get("at_time", [])]}')
    img = sdir / 'current_frame.jpg'
    check(img.is_file() and img.stat().st_size > 1000, f"止めた1コマ {s.get('frame_image')}（{img.stat().st_size if img.is_file() else 0} バイト）")
    # フックの要約
    r = subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve().parent / 'mittler_state.py'), str(proj)], capture_output=True, text=True, encoding='utf-8')
    print(r.stdout)
    check(sid in r.stdout and 'ここを直したい字幕' in r.stdout and 'current_frame.jpg' in r.stdout and '0:01.500' in r.stdout, 'フック（mittler_state.py）の要約に選んでいるもの・時刻・画面の1コマ')
    # 選びなおす → 追いつく
    pg.evaluate('window.MITTLER_EDITOR.select(null)')
    s = state(lambda s: s.get('selection') is None)
    check(s.get('selection') is None, '選ぶのをやめると selection なし')
    while pg.evaluate('window.MITTLER_EDITOR.undo.length') > 0:
        pg.click('#undo')
    tl = saved(pg)
    b.close()

check(tl == first, 'タイムラインの中身が最初と同じ（取り消しで戻った）')
check(not errors, 'コンソールエラーなし' + ('' if not errors else ': ' + ' | '.join(errors[:5])))
sys.exit(1 if fails else 0)
