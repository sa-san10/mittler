"""🎬 テイクの動画を真ん中のプレビューで見る（editor/plan.js の ▶・サムネ。2026-11-16）の確かめ。ヘッドレスのブラウザ、localhost だけ。
  <Playwright の python> -X utf8 tools/smoke_takeview.py --render-python <描画の python> [--work <フォルダ>] [--shot <画像>]
試しの作品は smoke_api.py と同じもの（動画化予定 plan_1 に H.264 の動画のテイク t1・t2）。確かめること：
  サムネ（/api/takethumb）が出る・▶ で WebM（/api/takeproxy → work/proxy/<名前>.webm）を作ってプレビューで流れる（左上に「テイク t1」）・
  行に位置と閉じるが出る・もう一度押すと一時停止・位置を動かせる・サムネで別のテイクに切りかわる・× で閉じてタイムラインの絵に戻る・
  タイムラインの再生・時刻を動かすと閉じる・タイムラインは書きかわらない・画面のエラーなし
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_api as SA  # noqa: E402  （--render-python を読む・試しの作品・サーバー）

from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    work = Path(SA.opt('--work') or tempfile.mkdtemp(prefix='mittler_smoketv_'))
    work.mkdir(parents=True, exist_ok=True)
    proj = work / 'p_tv'
    if proj.exists():
        import shutil
        shutil.rmtree(proj)
    tlf = SA.make_project(proj)
    T0 = tlf.read_text(encoding='utf-8')
    srv = SA.Server(tlf, work / 'server.log', 'http://127.0.0.1:9')
    check = SA.check
    try:
        with sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={'width': 1500, 'height': 900})
            errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.goto(srv.url)
            pg.wait_for_function(SA.READY, timeout=120000)
            ev = pg.evaluate
            ev("() => { MITTLER_EDITOR.select('plan_1'); MITTLER_EDITOR.showPane('sel'); }")
            pg.wait_for_selector('.vtake[data-take=t1] .vthumb')
            pg.wait_for_function("() => { const i = document.querySelector('.vtake[data-take=t1] .vthumb'); return i.complete && i.naturalWidth > 0; }", timeout=60000)
            check(True, 'サムネ（/api/takethumb）が出る')
            e0 = ev('MITTLER_EDITOR.edits')
            tv = "document.getElementById('takeView')"
            pg.click('.vtake[data-take=t1] .vplay')
            pg.wait_for_function(f"() => !{tv}.hidden && !{tv}.paused && {tv}.currentTime > 0.2", timeout=120000)
            src = ev(f"() => {tv}.currentSrc")
            tag = ev("() => document.getElementById('srcTag').textContent")
            check('work/proxy/plan_1_t1.webm' in src and (proj / 'work' / 'proxy' / 'plan_1_t1.webm').exists(), f'▶：WebM を作ってプレビューで流れる（{src.split("/project/")[-1]}）')
            check('t1' in tag and 'テイク' in tag, f'左上の札（{tag}）')
            vis = ev("() => !document.querySelector('.vtake[data-take=t1] .vctl').hidden && document.querySelector('.vtake[data-take=t2] .vctl').hidden")
            check(vis, '位置と閉じるは、見ているテイクの行だけに出る')
            if SA.opt('--shot'):
                pg.screenshot(path=SA.opt('--shot'))
            pg.click('.vtake[data-take=t1] .vplay')
            time.sleep(0.3)
            check(ev(f"() => {tv}.paused && !{tv}.hidden"), 'もう一度押すと一時停止（プレビューに残る）')
            ev("() => { const r = document.querySelector('.vtake[data-take=t1] .vctl input'); r.value = '500'; r.dispatchEvent(new Event('input', {bubbles: true})); }")
            time.sleep(0.3)
            ct = ev(f"() => {tv}.currentTime")
            check(0.8 < ct < 1.2, f'位置を動かせる（{ct:.2f} 秒）')
            pg.click('.vtake[data-take=t2] .vthumb')
            pg.wait_for_function(f"() => {tv}.currentSrc.includes('plan_1_t2.webm') && !{tv}.paused", timeout=120000)
            check(True, 'サムネを押すと、そのテイクに切りかわって流れる')
            pg.click('.vtake[data-take=t2] .vclose')
            time.sleep(0.3)
            check(ev(f"() => {tv}.hidden && !{tv}.getAttribute('src')"), '× で閉じる')
            pg.wait_for_function("() => /今のタイムライン/.test(document.getElementById('srcTag').textContent)", timeout=60000)
            check(True, '閉じると、今のタイムラインの絵に戻る')
            pg.click('.vtake[data-take=t1] .vplay')
            pg.wait_for_function(f"() => !{tv}.hidden && !{tv}.paused", timeout=60000)
            ev('() => seek(1)')
            time.sleep(0.2)
            check(ev(f"() => {tv}.hidden"), '時刻を動かすと閉じる')
            pg.click('.vtake[data-take=t1] .vplay')
            pg.wait_for_function(f"() => !{tv}.hidden && !{tv}.paused", timeout=60000)
            ev('() => setPlaying(true)')
            time.sleep(0.2)
            check(ev(f"() => {tv}.hidden"), 'タイムラインを再生すると閉じる')
            ev('() => setPlaying(false)')
            time.sleep(0.5)
            check(ev('MITTLER_EDITOR.edits') == e0 and tlf.read_text(encoding='utf-8') == T0, 'タイムラインは書きかわらない（見るだけ）')
            check(not errs, f'画面のエラーなし {errs[:3]}')
            br.close()
    finally:
        srv.quit()
    if not SA.opt('--work'):
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    print(f'---\nFAIL の数 {len(SA.fails)}')
    sys.exit(1 if SA.fails else 0)


if __name__ == '__main__':
    main()
