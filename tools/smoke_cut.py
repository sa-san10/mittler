"""✂ カット編集の道具（editor/cutedit.js）の動作確認（ヘッドレス、localhost だけ）。試し用の作品で流す。最後にタイムラインを最初に戻す。
  <Playwright の python> -X utf8 tools\\smoke_cut.py <URL> <作品>\\<名前>.cut.json
作品に要るもの：assets/videos/withsound.mp4（音つき・6 秒ほど。ffmpeg の testsrc2＋sine で作れる）、映像のトラック1本、
ト書きのメタデータ（id "m_notes"、kind "notes"）。サーバーは MITTLER_NO_REVEAL=1 で起動する（書き出し先を開かない）。最後に 0〜1 秒を書き出す。
確かめること：✂ カット編集の道具：音つき動画を置く（音もリンクして）→ 再生位置で分割（リンクも）→ カット道具 → 取り消し・やり直し → ドラッグで一緒に動く
→ 別の映像トラックへ → リップル削除 → コピー・貼り付け・複製 → 1コマ動かす → スリップ → フェードのつまみ → 波形 → 囲んで選ぶ → 連動オフ
→ ト書き（メタデータ）のドラッグ・伸び縮み・ダブルクリックで足す・Delete → 隙間を詰める → ↑↓ 編集点 → 書き出すと動画の音が鳴る（最後にタイムラインを戻す）"""
import re, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright
url, tlf = sys.argv[1], Path(sys.argv[2]); orig = tlf.read_bytes(); fails, errs = [], []
proj = tlf.parent


def check(c, m):
    print(('OK   ' if c else 'FAIL ') + m, flush=True); (None if c else fails.append(m))


TL = '() => window.MITTLER_EDITOR.tl'
VIDS = "() => window.MITTLER_EDITOR.tl.tracks.filter(t => t.kind === 'video').flatMap(t => t.clips.filter(c => c.type === 'video').map(c => ({id: c.id, tr: t.id, start: +c.start.toFixed(4), dur: +c.dur.toFixed(4), in: +(c.in||0).toFixed(4), link: c.link || ''})))"
AUS = "() => window.MITTLER_EDITOR.tl.tracks.filter(t => t.kind === 'audio').flatMap(t => t.clips.map(c => ({id: c.id, tr: t.id, src: c.src, start: +c.start.toFixed(4), dur: +c.dur.toFixed(4), in: +(c.in||0).toFixed(4), link: c.link || '', fade_in: c.fade_in || 0})))"


def box(pg, sel):
    loc = pg.locator(sel).first; loc.scroll_into_view_if_needed(); time.sleep(0.1); return loc.bounding_box()


def drag(pg, x0, y0, x1, y1, mods=()):
    for m in mods: pg.keyboard.down(m)
    pg.mouse.move(x0, y0); pg.mouse.down(); pg.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, steps=4); pg.mouse.move(x1, y1, steps=4); pg.mouse.up()
    for m in mods: pg.keyboard.up(m)
    time.sleep(0.3)


def clip_sel(cid):
    return f'#laneList .clip[data-id="{cid}"]'


try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True); pg = b.new_page(viewport={'width': 1700, 'height': 1000})
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.goto(url); pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl && window.MITTLER_CUT', timeout=120000)
        check(pg.is_visible('#cutbar [data-tool="razor"]'), '道具のバーが出る')
        pg.evaluate("() => { window.MITTLER_EDITOR.change(() => { window.MITTLER_EDITOR.tl.tracks.find(t => t.kind === 'video').clips = []; }); }")
        pg.evaluate('() => window.MITTLER_ASSETS.setOpen(true)'); pg.click('#assetTabs [data-tab="videos"]')
        pg.click('#assetBody .arow[data-path$="withsound.mp4"]'); pg.click('#apVid')
        pg.wait_for_function("() => /動画と音|動画を置きました/.test(document.getElementById('status').textContent)", timeout=60000)
        v, a = pg.evaluate(VIDS), pg.evaluate(AUS)
        check(len(v) == 1 and len(a) == 1 and v[0]['link'] and v[0]['link'] == a[0]['link'] and a[0]['src'].startswith('assets/video_audio/') and (proj / a[0]['src']).is_file(),
              f"動画を置くと音も取り出してリンクして置く（{pg.inner_text('#status')}／{a}）")
        check(pg.evaluate("() => window.MITTLER_EDITOR.tl.tracks.find(t => t.from_video).name") == '動画の音', '「動画の音」のトラック')
        check(pg.evaluate('() => window.MITTLER_EDITOR.multi.size') == 2, '動画を選ぶと音も一緒に選ばれる')
        vid, aid = v[0]['id'], a[0]['id']
        pg.wait_for_selector(clip_sel(aid) + ' .wave', timeout=30000)
        check('api/wave' in pg.get_attribute(clip_sel(aid) + ' .wave', 'style'), '音のクリップに波形')
        # 再生位置で分割（Ctrl+K）
        pg.evaluate('() => window.MITTLER_EDITOR.seek(2)'); pg.click(clip_sel(vid)); pg.evaluate('() => window.MITTLER_EDITOR.seek(2)')
        pg.keyboard.press('Control+k')
        v, a = pg.evaluate(VIDS), pg.evaluate(AUS)
        rv = [x for x in v if x['start'] == 2]; ra = [x for x in a if x['start'] == 2]
        check(len(v) == 2 and len(a) == 2 and rv and ra and rv[0]['in'] == 2 and ra[0]['in'] == 2 and rv[0]['link'] == ra[0]['link'] and rv[0]['link'] != v[0]['link'] or False,
              f'Ctrl+K で動画も音も 2 秒で分かれ、右は素材の 2 秒から・右どうしで新しいリンク（{v}／{a}）')
        # カット道具
        pg.keyboard.press('c'); check(pg.evaluate("() => document.body.classList.contains('tool-razor')"), 'C でカット道具')
        bx = box(pg, clip_sel(rv[0]['id'])); pps = pg.evaluate('() => window.MITTLER_EDITOR.pps')
        pg.keyboard.down('Alt'); pg.mouse.click(bx['x'] + 1.0 * pps, bx['y'] + bx['height'] / 2); pg.keyboard.up('Alt'); time.sleep(0.3)
        v, a = pg.evaluate(VIDS), pg.evaluate(AUS)
        check(len(v) == 3 and len(a) == 3, f'カット道具でクリップを押すと、そこで分かれる（リンクの音も。動画 {len(v)}・音 {len(a)}）')
        pg.keyboard.press('v')
        # 取り消し・やり直し
        pg.keyboard.press('Control+z'); n1 = len(pg.evaluate(VIDS)); pg.keyboard.press('Control+y'); n2 = len(pg.evaluate(VIDS)); pg.keyboard.press('Control+Shift+z')
        check(n1 == 2 and n2 == 3, f'Ctrl+Z で戻り、Ctrl+Y でやり直す（{n1}→{n2}）')
        pg.keyboard.press('Control+z'); check(len(pg.evaluate(VIDS)) == 2, 'もう一度戻して 2 つずつ')
        # ドラッグで一緒に動く
        v = pg.evaluate(VIDS); right = [x for x in v if x['start'] == 2][0]
        bx = box(pg, clip_sel(right['id'])); pg.mouse.click(bx['x'] + bx['width'] / 2, bx['y'] + 10)
        pg.evaluate("() => { window.MITTLER_EDITOR.snap.on = false; }")
        drag(pg, bx['x'] + bx['width'] / 2, bx['y'] + 10, bx['x'] + bx['width'] / 2 + 1.0 * pps, bx['y'] + 10)
        v, a = pg.evaluate(VIDS), pg.evaluate(AUS); mv = [x for x in v if x['id'] == right['id']][0]; ma = [x for x in a if x['link'] == right['link']][0]
        check(abs(mv['start'] - 3) < 0.05 and abs(ma['start'] - mv['start']) < 1e-6, f"ドラッグで動画と音が一緒に動く（動画 {mv['start']}・音 {ma['start']}）")
        # 別の映像トラックへ（上に映像トラックを足して、上へドラッグ）
        pg.evaluate("() => { const S = window.MITTLER_EDITOR; S.change(() => { const i = S.tl.tracks.findIndex(t => t.kind === 'video'); S.tl.tracks.splice(i, 0, { id: 't_video_up', name: '映像 2', kind: 'video', clips: [] }); }); }")
        bx = box(pg, clip_sel(right['id'])); up = box(pg, '#laneList .lane[data-track="t_video_up"]')
        drag(pg, bx['x'] + bx['width'] / 2, bx['y'] + 10, bx['x'] + bx['width'] / 2, up['y'] + up['height'] / 2)
        v, a = pg.evaluate(VIDS), pg.evaluate(AUS); mv = [x for x in v if x['id'] == right['id']][0]; ma = [x for x in a if x['link'] == right['link']][0]
        check(mv['tr'] == 't_video_up' and abs(mv['start'] - 3) < 0.05 and ma['tr'] != 't_video_up', f"上の映像トラックへ（時刻はそのまま、音は音のトラックのまま：{mv['tr']}・{ma['tr']}）")
        pg.keyboard.press('Control+z')
        # リップル削除：左の動画（0〜2）を消すと、同じトラックの後ろ（3〜）が 2 秒前へ
        v = pg.evaluate(VIDS); left = [x for x in v if x['start'] == 0][0]
        pg.click(clip_sel(left['id'])); pg.keyboard.press('Shift+Delete')
        v, a = pg.evaluate(VIDS), pg.evaluate(AUS)
        check(len(v) == 1 and abs(v[0]['start'] - 1) < 0.05 and len(a) == 1 and abs(a[0]['start'] - 1) < 0.05, f'リップル削除：消して後ろを詰める（リンクの音も：{v}／{a}）')
        pg.keyboard.press('Control+z')
        # コピー・貼り付け・複製
        v = pg.evaluate(VIDS); left = [x for x in v if x['start'] == 0][0]
        pg.click(clip_sel(left['id'])); pg.keyboard.press('Control+c'); pg.evaluate('() => window.MITTLER_EDITOR.seek(6)'); pg.keyboard.press('Control+v')
        v2, a2 = pg.evaluate(VIDS), pg.evaluate(AUS); pv = [x for x in v2 if x['start'] == 6]; pa = [x for x in a2 if x['start'] == 6]
        check(len(pv) == 1 and len(pa) == 1 and pv[0]['link'] == pa[0]['link'] and pv[0]['link'] != left['link'], f'Ctrl+C → Ctrl+V で再生位置に貼る（動画と音、新しいリンク）')
        pg.keyboard.press('Control+d'); v3 = pg.evaluate(VIDS); check(any(abs(x['start'] - 8) < 1e-3 for x in v3), f'Ctrl+D ですぐ後ろに複製（{[x["start"] for x in v3]}）')
        pg.keyboard.press('Control+z'); pg.keyboard.press('Control+z')
        # 1コマ動かす
        pg.click(clip_sel(left['id'])); pg.keyboard.press('Alt+ArrowRight')
        mv = [x for x in pg.evaluate(VIDS) if x['id'] == left['id']][0]; check(abs(mv['start'] - 1 / 30) < 1e-4, f"Alt+→ で 1 コマ（{mv['start']}）")
        pg.keyboard.press('Control+z')
        # スリップ：右（素材の 2 秒から）を右へ 0.5 秒 → 素材の 1.5 秒から（位置はそのまま）
        v = pg.evaluate(VIDS); right = [x for x in v if x['start'] > 1][0]
        pg.keyboard.press('y'); bx = box(pg, clip_sel(right['id']))
        drag(pg, bx['x'] + bx['width'] / 2, bx['y'] + 10, bx['x'] + bx['width'] / 2 + 0.5 * pps, bx['y'] + 10)
        mv = [x for x in pg.evaluate(VIDS) if x['id'] == right['id']][0]; ma = [x for x in pg.evaluate(AUS) if x['link'] == right['link']][0]
        check(abs(mv['in'] - (right['in'] - 0.5)) < 0.05 and mv['start'] == right['start'] and abs(ma['in'] - mv['in']) < 1e-6, f"スリップ：位置そのまま、素材の場所だけずれる（in {right['in']}→{mv['in']}、音も {ma['in']}）")
        pg.keyboard.press('v')
        # フェードのつまみ
        a = pg.evaluate(AUS); a0 = [x for x in a if x['start'] == 0][0]
        pg.click(clip_sel(a0['id'])); bx = box(pg, clip_sel(a0['id']) + ' .fh.l')
        drag(pg, bx['x'] + 4, bx['y'] + 4, bx['x'] + 4 + 0.5 * pps, bx['y'] + 4)
        fi = [x for x in pg.evaluate(AUS) if x['id'] == a0['id']][0]['fade_in']; check(0.4 < fi < 0.6, f'フェードインのつまみ（{fi}秒）')
        # 囲んで選ぶ
        pg.keyboard.press('Escape'); lanes = box(pg, '#laneList')
        pg.evaluate("() => { document.getElementById('lanesWrap').scrollTop = 0; }"); lanes = pg.locator('#laneList').bounding_box(); wr = pg.locator('#lanesWrap').bounding_box()
        drag(pg, lanes['x'] + 3, lanes['y'] + 2, lanes['x'] + 3.5 * pps, min(lanes['y'] + lanes['height'], wr['y'] + wr['height']) - 4, mods=('Shift',))
        n = pg.evaluate('() => window.MITTLER_EDITOR.multi.size'); check(n == 4, f'Shift＋ドラッグで囲んで選ぶ（{n} 個）')
        # 連動オフ
        pg.click('#cutbar [data-act="linkon"]'); pg.keyboard.press('Escape'); pg.click(clip_sel(left['id']))
        check(pg.evaluate('() => window.MITTLER_EDITOR.multi.size') == 1, '🔗 連動オフなら動画だけ選べる')
        pg.click('#cutbar [data-act="linkon"]')
        # ト書き（メタデータ）
        pg.evaluate("() => { const S = window.MITTLER_EDITOR; S.change(() => { S.tl.meta.find(m => m.id === 'm_notes').items = [{ start: 1, end: 2, text: 'ト書きA' }]; }); }")
        ib = box(pg, '#laneList .item.notes')
        drag(pg, ib['x'] + ib['width'] / 2, ib['y'] + ib['height'] / 2, ib['x'] + ib['width'] / 2 + 1.0 * pps, ib['y'] + ib['height'] / 2)
        it = pg.evaluate("() => window.MITTLER_EDITOR.tl.meta.find(m => m.id === 'm_notes').items[0]")
        check(abs(it['start'] - 2) < 0.05 and abs(it['end'] - 3) < 0.05, f"ト書きをドラッグで動かす（{it['start']}〜{it['end']}）")
        check(pg.evaluate("() => window.MITTLER_EDITOR.pane") == 'meta' and pg.locator('#metaBody .mrow.picked').count() == 1, '押すとメタデータの欄でその行が出る')
        gb = box(pg, '#laneList .item.notes .grip.r')
        drag(pg, gb['x'] + 2, gb['y'] + 5, gb['x'] + 2 + 0.5 * pps, gb['y'] + 5)
        it = pg.evaluate("() => window.MITTLER_EDITOR.tl.meta.find(m => m.id === 'm_notes').items[0]"); check(abs(it['end'] - 3.5) < 0.05, f"右の端で長さ（終わり {it['end']}）")
        lane = box(pg, '#laneList .lane.meta[data-meta="m_notes"]')
        pg.mouse.dblclick(lane['x'] + 5.5 * pps, lane['y'] + lane['height'] / 2); time.sleep(0.3)
        items = pg.evaluate("() => window.MITTLER_EDITOR.tl.meta.find(m => m.id === 'm_notes').items")
        check(len(items) == 2 and abs(items[1]['start'] - 5.5) < 0.05, f'空いたところをダブルクリックで足す（{[(x["start"], x["end"]) for x in items]}）')
        pg.locator('#laneList .item.notes >> nth=1').scroll_into_view_if_needed(); pg.click('#laneList .item.notes >> nth=1'); pg.keyboard.press('Delete')
        check(len(pg.evaluate("() => window.MITTLER_EDITOR.tl.meta.find(m => m.id === 'm_notes').items")) == 1, '選んで Delete で消す')
        # 隙間を詰める（動画のトラック：0〜2 と 2〜 のあいだを空けてから）
        v = pg.evaluate(VIDS); right = [x for x in v if x['start'] > 1][0]
        pg.evaluate(f"() => {{ const S = window.MITTLER_EDITOR; S.change(() => {{ for (const t of S.tl.tracks) for (const c of t.clips) if (c.link === '{right['link']}') c.start = 3; }}); }}")
        pg.click(clip_sel(right['id'])); pg.click('#cutbar [data-act="gaps"]')
        v, a = pg.evaluate(VIDS), pg.evaluate(AUS); mv = [x for x in v if x['id'] == right['id']][0]; ma = [x for x in a if x['link'] == right['link']][0]
        check(abs(mv['start'] - 2) < 1e-4 and abs(ma['start'] - 2) < 1e-4, f"隙間を詰める（動画 {mv['start']}・音 {ma['start']}）")
        # 編集点へ
        pg.keyboard.press('Escape'); pg.evaluate('() => window.MITTLER_EDITOR.seek(0.5)'); pg.click('#lanesWrap', position={'x': 5, 'y': 5}); pg.evaluate('() => window.MITTLER_EDITOR.seek(0.5)')
        pg.keyboard.press('ArrowDown'); t1 = pg.evaluate('() => window.MITTLER_EDITOR.t'); pg.keyboard.press('ArrowUp'); pg.keyboard.press('ArrowUp'); t2 = pg.evaluate('() => window.MITTLER_EDITOR.t')
        check(abs(t1 - 2) < 0.02 and abs(t2 - 0) < 0.02, f'↓ で次の編集点・↑ で前（{t1:.3f}・{t2:.3f}）')
        # 書き出し（0〜1秒）：動画の音が入る
        pg.wait_for_function('() => !window.MITTLER_EDITOR.saveTimer && !window.MITTLER_EDITOR.saving', timeout=30000)
        pg.click('#exportBtn'); pg.wait_for_selector('#exportPanel input[name=xr]')
        pg.evaluate("document.querySelectorAll('#exportPanel details.xadv').forEach(d => d.open = true)")  # 同時処理数は詳細設定の中
        pg.check('#exportPanel input[name=xr][value="part"]'); pg.fill('#xFrom', '0'); pg.fill('#xTo', '1'); pg.fill('#xName', 'smoke_cut'); pg.fill('#xJobs', '2'); pg.uncheck('#xProxy')
        pg.click('#exportPanel [data-x="start"]')
        pg.wait_for_function("() => ['done','error','cancelled'].includes(window.MITTLER_EXPORT.job.state)", timeout=600000)
        j = pg.evaluate('() => window.MITTLER_EXPORT.job'); check(j['state'] == 'done', f"書き出し（{j['state']}）{(j.get('error') or '')[:300]}")
        b.close()
finally:
    tlf.write_bytes(orig)
out = proj / 'output' / 'smoke_cut.mp4'
if out.exists():
    r = subprocess.run(['ffmpeg', '-v', 'info', '-i', str(out), '-af', 'volumedetect', '-vn', '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    m = re.search(r'mean_volume: (-?[\d.]+) dB', r); mv = float(m.group(1)) if m else -999
    check(mv > -40, f'書き出した動画に動画の音が入っている（平均 {mv} dB）')
check(not errs, 'エラーなし' + ('' if not errs else ': ' + ' | '.join(errs[:3])))
sys.exit(1 if fails else 0)
