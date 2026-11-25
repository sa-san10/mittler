"""映像クリップの速さ・🎵 音ハメ（editor/warp.js・pyengine/mittler/onbeat.py）の動作確認（ヘッドレス、localhost だけ）。試し用の作品で流す。
  <Playwright の python> -X utf8 tools\\smoke_warp.py <URL> --timeline <作品>\\<名前>.cut.json --clip <映像クリップの id> [--shot 画像]
作品には映像クリップ1本（動いている人の動画）とビートのメタデータが要る。終わったらタイムラインを最初に戻す。
確かめること：速さの欄 → タイムラインのバッジ／音ハメ（自動）→ 点・アクセント・拍との組がタイムラインに入り、速さの線が出る
→ 描画エンジンの絵が「点が決める動画の秒」のコマと一致する（ffmpeg で取り出したコマといちばん近い）
→ 点のドラッグ・ダブルクリックで足す・右クリックで消す → 頭を切っても映る絵が動かない → 一定の速さに戻す。
"""
import argparse
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pyengine'))
from mittler.warp import Points  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument('url'); ap.add_argument('--timeline', required=True); ap.add_argument('--clip', required=True); ap.add_argument('--shot')
a = ap.parse_args()
if not a.url.startswith(('http://127.0.0.1:', 'http://localhost:')): sys.exit('localhost only')
tlf = Path(a.timeline); orig = tlf.read_bytes(); proj = tlf.parent
fails, errors = [], []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


def clip_now():
    tl = json.loads(tlf.read_text(encoding='utf-8'))
    return tl, next(c for t in tl['tracks'] for c in t.get('clips', []) if c['id'] == a.clip)


def wait_file(cond, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            tl, c = clip_now()
            if cond(c):
                return c
        except Exception:
            pass
        time.sleep(0.3)
    return clip_now()[1]


def settled(pg):
    pg.wait_for_function('() => !window.MITTLER_EDITOR.saveTimer && !window.MITTLER_EDITOR.saving', timeout=60000)


def frame(pg, t):
    tok = a.url.split('token=')[-1].split('&')[0]  # /api/frame は描画サーバーを起動しうる GET なのでトークンが要る
    r = pg.request.get('/'.join(a.url.split('/')[:3]) + f'/api/frame?t={t}&q=95', headers={'X-Mittler-Token': tok}, timeout=180000)
    return np.asarray(Image.open(io.BytesIO(r.body())).convert('RGB'), np.float32)


def src_frames(path, fps, idx, W, H):
    out = {}
    for i in idx:
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{i / fps:.4f}', '-i', str(path), '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}',
                              '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
        if len(raw) == W * H * 3:
            out[i] = np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(np.float32)
    return out


try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={'width': 1600, 'height': 940})
        pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.goto(a.url)
        pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl && window.MITTLER_WARP', timeout=60000)
        tl, c0 = clip_now(); fps = tl['fps']
        pg.click(f'.clip[data-id="{a.clip}"]'); pg.wait_for_selector('#sel [data-act="auto"]')
        # 速さ
        pg.fill('#sel [data-k="speed"]', '1.25'); pg.press('#sel [data-k="speed"]', 'Enter')
        c = wait_file(lambda c: c.get('speed') == 1.25)
        check(c.get('speed') == 1.25, '速さ 1.25 がタイムラインに入る')
        pg.wait_for_selector(f'.clip[data-id="{a.clip}"] .spdb'); check('1.25' in pg.inner_text(f'.clip[data-id="{a.clip}"] .spdb'), 'タイムラインのバッジ 1.25×')
        pg.fill('#sel [data-k="speed"]', '1'); pg.press('#sel [data-k="speed"]', 'Enter')
        c = wait_file(lambda c: 'speed' not in c); check('speed' not in c, '速さ 1 に戻すと speed が消える')
        settled(pg)
        T = c0['start'] + c0['dur'] * 0.55
        before = frame(pg, T)
        # 音ハメ（自動）
        t0 = time.time(); pg.click('#sel [data-act="auto"]')
        c = wait_file(lambda c: isinstance(c.get('warp'), dict), timeout=300)
        w = c.get('warp') or {}
        check(isinstance(w.get('points'), list) and len(w['points']) >= 2, f"音ハメの点（{len(w.get('points', []))} 点、{time.time() - t0:.1f} 秒、{w.get('method')}）")
        check(len(w.get('pairs', [])) >= 2, f"拍に合わせたアクセント {len(w.get('pairs', []))} か所・アクセント {len(w.get('accents', []))}")
        pg.wait_for_selector(f'.clip[data-id="{a.clip}"] svg.spd'); check(True, 'タイムラインに速さの線')
        pg.wait_for_selector('#sel canvas.wgraph'); check(True, '右の欄にグラフ')
        if a.shot:
            pg.screenshot(path=a.shot)
        settled(pg)
        # そのほかの設定：固定点（pins）を足してやり直す → 点がそこを通る。設定は auto に残る
        Wp = Points(w['points'], w.get('smooth', 0)); pin = [round(Wp(3.0) + 0.05, 4), 3.0]
        pg.click('#sel details.wauto summary') if not pg.is_visible('#sel [data-adv]') else None
        pg.fill('#sel [data-adv]', json.dumps({'pins': [pin]})); pg.click('#sel [data-act="auto"]')
        cp = wait_file(lambda c: isinstance(c.get('warp'), dict) and (c['warp'].get('auto') or {}).get('pins') == [pin], timeout=300)
        okp = any(abs(p_[0] - 3.0) < 1e-6 and abs(p_[1] - pin[0]) < 1e-3 for p_ in cp['warp']['points'])
        check(okp, f"固定点 {pin} を通る（点 {len(cp['warp']['points'])} つ、auto に pins が残る）")
        pg.wait_for_selector('#sel [data-adv]', state='attached'); pg.click('#sel details.wauto summary') if not pg.is_visible('#sel [data-adv]') else None
        pg.fill('#sel [data-adv]', '{}'); pg.click('#sel [data-act="auto"]')
        # （欄から抜けたときに設定だけ先に保存されるので、点が変わるまで待つ）
        c = wait_file(lambda c: isinstance(c.get('warp'), dict) and 'pins' not in (c['warp'].get('auto') or {}) and c['warp']['points'] == w['points'], timeout=300)
        check(c['warp']['points'] == w['points'] and 'pins' not in c['warp']['auto'], '固定点を外してやり直す（最初の音ハメと同じ点に戻る）')
        settled(pg)
        # 描画エンジンの絵：点が決める動画の秒のコマ
        W_ = Points(w['points'], w.get('smooth', 0)); s = W_(T - c['start']); fi = int(round(s * fps))
        after = frame(pg, T)
        H, Wd = after.shape[:2]
        cand = src_frames(proj / (c['src'][0] if isinstance(c['src'], list) else c['src']), fps, range(fi - 3, fi + 4), Wd, H)
        diffs = {i: float(np.abs(after - f).mean()) for i, f in cand.items()}
        best = min(diffs, key=diffs.get) if diffs else None
        check(best == fi, f'エンジンの絵＝動画の {fi} コマ目（{s:.3f} 秒。いちばん近いコマ {best}、差 ' + ', '.join(f'{i}:{d:.1f}' for i, d in sorted(diffs.items())) + '）')
        check(float(np.abs(after - before).mean()) > 0.5 or abs(s - (T - c0['start'])) < 0.5 / fps, '音ハメの前と絵が変わる（同じ秒なら同じ）')
        # 点のドラッグ（Alt で吸いつかない）
        n0 = len(w['points']); i = n0 // 2
        pg.locator('#sel canvas.wgraph').scroll_into_view_if_needed(); box = pg.locator('#sel canvas.wgraph').bounding_box()
        xy = pg.evaluate(f'() => {{ const m = document.querySelector("#sel canvas.wgraph").mittlerMap, p = m.pts()[{i}]; return [m.X(p[0]), m.Y(p[1])]; }}')
        pg.mouse.move(box['x'] + xy[0], box['y'] + xy[1]); pg.mouse.down(); pg.keyboard.down('Alt')
        pg.mouse.move(box['x'] + xy[0], box['y'] + xy[1] - 6, steps=4); pg.mouse.up(); pg.keyboard.up('Alt')
        c2 = wait_file(lambda c: c['warp']['points'][i] != w['points'][i])
        moved = c2['warp']['points'][i][1] - w['points'][i][1]
        others = all(c2['warp']['points'][k] == w['points'][k] for k in range(n0) if k != i)
        check(moved > 0 and others, f'点 {i} を上へドラッグ：動画の秒 +{moved:.3f}、ほかの点はそのまま')
        # ダブルクリックで足す・右クリックで消す
        gx = (pg.evaluate('() => document.querySelector("#sel canvas.wgraph").mittlerMap.X(0)') + pg.evaluate(f'() => document.querySelector("#sel canvas.wgraph").mittlerMap.X({c2["warp"]["points"][1][0]})')) / 2
        pg.mouse.dblclick(box['x'] + gx, box['y'] + 60)
        c3 = wait_file(lambda c: len(c['warp']['points']) == n0 + 1); check(len(c3['warp']['points']) == n0 + 1, 'ダブルクリックで点を足す')
        xy = pg.evaluate('() => { const m = document.querySelector("#sel canvas.wgraph").mittlerMap, p = m.pts()[1]; return [m.X(p[0]), m.Y(p[1])]; }')
        pg.mouse.click(box['x'] + xy[0], box['y'] + xy[1], button='right')
        c4 = wait_file(lambda c: len(c['warp']['points']) == n0); check(len(c4['warp']['points']) == n0, '右クリックで点を消す')
        # 頭を切っても映る絵は同じ（点がずれる）
        Wb = Points(c4['warp']['points'], c4['warp'].get('smooth', 0))
        pg.evaluate(f'() => {{ const f = findClip("{a.clip}"); change(() => trimClip(f.clip, "l", 0.5)); }}')
        c5 = wait_file(lambda c: abs(c['start'] - c4['start'] - 0.5) < 1e-6)
        Wa = Points(c5['warp']['points'], c5['warp'].get('smooth', 0))
        check(abs(Wa(1.0) - Wb(1.5)) < 1e-4 and abs(c5['in'] - Wb(0.5)) < 1e-3, f'頭を 0.5 秒切る：同じ曲の時刻は同じ動画の秒（{Wa(1.0):.4f} / {Wb(1.5):.4f}）')
        pg.keyboard.press('Control+z')
        c6 = wait_file(lambda c: abs(c['start'] - c4['start']) < 1e-6); check(c6['warp']['points'] == c4['warp']['points'], '取り消しで点も戻る')
        # 一定の速さに戻す
        pg.click(f'.clip[data-id="{a.clip}"]'); pg.wait_for_selector('#sel [data-act="clear"]'); pg.click('#sel [data-act="clear"]')
        c7 = wait_file(lambda c: 'warp' not in c)
        check('warp' not in c7 and abs(c7.get('in', 0) - max(0, Wb(0))) < 1e-3, f"一定の速さに戻す（素材の頭 {c7.get('in')}）")
        # 表のファイル（偽マリアの取り込みと同じ形）：読むだけのグラフ → 「直せるようにする」で点に（ファイルはそのまま）
        tab = proj / 'work' / 'smoke_warp_table.json'; tab.parent.mkdir(parents=True, exist_ok=True)
        rows = [[i / 24, 0.2 + i / 24 if i < 48 else 2.2 + 1.5 * (i / 24 - 2)] for i in range(0, 145)]  # 2 秒で 1× → 1.5×
        tab.write_text(json.dumps({'table': rows}), encoding='utf-8'); tab_bytes = tab.read_bytes()
        pg.evaluate(f'() => {{ const f = findClip("{a.clip}"); change(() => {{ f.clip.warp = "work/smoke_warp_table.json"; f.clip.in = 0; }}); select("{a.clip}"); }}')
        pg.wait_for_selector('#sel [data-act="topts"]'); pg.wait_for_selector('#sel canvas.wgraph')
        pg.wait_for_selector(f'.clip[data-id="{a.clip}"] svg.spd', timeout=20000); check(True, '表のファイル：グラフと速さの線（読むだけ）')
        pg.click('#sel [data-act="topts"]')
        c8 = wait_file(lambda c: isinstance(c.get('warp'), dict))
        pts8 = (c8.get('warp') or {}).get('points', [])
        check(len(pts8) == 3 and abs(pts8[1][0] - 2.0) < 1e-3 and tab.read_bytes() == tab_bytes,
              f'「直せるようにする」：表 145 行 → 点 {len(pts8)} つ（折れ目 {pts8[1] if len(pts8) > 1 else None}）、ファイルはそのまま')
        settled(pg)
        b.close()
finally:
    tlf.write_bytes(orig)  # タイムラインを最初に戻す
check(not errors, 'コンソールエラーなし' + ('' if not errors else ': ' + ' | '.join(errors[:5])))
sys.exit(1 if fails else 0)
