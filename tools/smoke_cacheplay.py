"""ためた絵（2026-11-16：裏で先に描く・目盛りの印・ためた絵で ▶・差分書き出し）の確かめ。ヘッドレスのブラウザ、localhost だけ。
  <Playwright の python> -X utf8 tools/smoke_cacheplay.py --render-python <描画の python> [--work <フォルダ>]
試しの作品は smoke_api.py と同じもの（320×180・30fps・12 秒）。確かめること：
  裏で描くのは既定で切・ボタンで入にして止めて手を離すと、サーバーが裏で描き始めて（/api/bake）全部のコマをためる・目盛りの下に印が出る（全体を覆う）・
  ▶ でためた絵を流す（左上に「ためた絵で再生」・絵は /api/cframe）・止めると今までどおり・
  外でクリップを直すと印が欠ける（直した区間）・その区間から ▶ は今までどおり（ためた絵では流さない）・
  書き出し（API の export --wait）は直していない区間をためた絵から（差分書き出し）・--no-cache なら全部描く・画面のエラーなし
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_api as SA  # noqa: E402  （--render-python を読む・試しの作品・サーバー）

from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    work = Path(SA.opt('--work') or tempfile.mkdtemp(prefix='mittler_smokecp_'))
    work.mkdir(parents=True, exist_ok=True)
    proj = work / 'p_cp'
    if proj.exists():
        shutil.rmtree(proj)
    tlf = SA.make_project(proj)
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
            check(ev('() => MITTLER_CACHE.state().off') and '切' in ev("() => document.getElementById('bakeBtn').getAttribute('aria-label')"), '裏で描くのは既定で切')
            ev('() => MITTLER_CACHE.setOff(false)')  # 入にする（この画面で覚える）
            ev('() => seek(1)')
            # 止めて手を離す → 裏で描く → 全部ためる
            pg.wait_for_function("() => { const s = MITTLER_CACHE.state(); return s.bake && (s.bake.state === 'running' || s.bake.state === 'done'); }", timeout=60000)
            check(True, '止めて手を離すと、裏で描き始める（/api/bake）')
            pg.wait_for_function("() => { const s = MITTLER_CACHE.state(); return s.map && s.fresh && s.map.keys.length && s.map.keys.every(Boolean); }", timeout=600000)
            n = ev("() => MITTLER_CACHE.state().map.keys.length")
            check(n == 360, f'全部のコマ（{n}）をためた')
            bars = ev("() => [...document.querySelectorAll('#ruler .cbar')].map(e => [parseFloat(e.style.left), parseFloat(e.style.width)])")
            full = ev("() => 12 * MITTLER_EDITOR.pps")
            check(len(bars) == 1 and bars[0][0] < 1 and abs(bars[0][1] - full) < 2, f'目盛りの下の印が全体を覆う（{bars}・{full:.0f}px）')
            # ▶ でためた絵を流す
            ev('() => seek(2)')
            ev('() => setPlaying(true)')
            pg.wait_for_function("() => (document.getElementById('frameImg').getAttribute('src') || '').includes('/api/cframe')", timeout=20000)
            tag = ev("() => document.getElementById('srcTag').textContent")
            check(ev('() => MITTLER_EDITOR.cachePlay') and 'ためた絵' in tag, f'▶ でためた絵を流す（{tag}）')
            time.sleep(1.0)
            t1 = ev('() => MITTLER_EDITOR.t')
            check(t1 > 2.5, f'時計で進む（{t1:.2f} 秒）')
            ev('() => setPlaying(false)')
            check(not ev('() => MITTLER_EDITOR.cachePlay'), '止めると、ためた絵の再生も止まる')
            # 外でクリップを直す（映像 2 の v_3：0〜1 秒。カットに入っていない。カットに入った映像は、前後のカットまで鍵に入る）→ 印が欠ける・その区間から ▶ は今までどおり
            tl = json.loads(tlf.read_text(encoding='utf-8'))
            v3 = next(c for t in tl['tracks'] if t['kind'] == 'video' for c in t['clips'] if c['id'] == 'v_3')
            v3['label'] = 'v3 changed'
            tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
            pg.wait_for_function("() => { const s = MITTLER_CACHE.state(); return s.fresh && s.map.keys.some(k => !k); }", timeout=60000)
            keys = ev("() => MITTLER_CACHE.state().map.keys")
            miss = [i for i, k in enumerate(keys) if not k]
            check(miss and miss[-1] <= 89 and keys[90] and keys[300],  # 区間の中は、プレビューの先読み・裏の係がすぐ描き直し始めるので、全部は欠けていないことがある
                  f'外で直すと、直した区間（0〜1 秒の前後 2 秒）の印だけ欠ける（{miss[0] / 30 if miss else "-"}〜{miss[-1] / 30 if miss else "-"} 秒・{len(miss)} コマ）')
            ok_play = ev('() => MITTLER_CACHE.canPlay(0.5)')
            check(not ok_play, 'ためていない区間からは、ためた絵では流さない')
            br.close()
        # 差分書き出し（API）：直していない区間はためた絵から（裏で描いた続きも、上で止めていなければためてある）
        r = SA.api(proj, 'export', '--wait', '--no-proxy', '--name', 'cp1')
        st = SA.api(proj, 'export-status')
        cached = st.get('cached')
        check(r.get('ok') and cached and 270 <= cached < 360, f'書き出しは、ためた絵を使う（{cached} / 360）')
        r = SA.api(proj, 'export', '--wait', '--no-proxy', '--no-cache', '--name', 'cp2')
        st = SA.api(proj, 'export-status')
        check(r.get('ok') and not st.get('cached'), f"--no-cache なら全部描く（{st.get('cached')}）")
        # シークすると裏で描くのを一時停止・静かになって 2.5 秒で続ける（1 コマ 0.3 秒の遅いエフェクトを全体に置いて、裏の係を長く動かす）
        (proj / 'effects' / 'slow.py').write_text('"""試し：遅い"""\nimport time\nSTAGE = "v7"\n\n\ndef apply(ctx, f, clip):\n    time.sleep(0.3)\n    return f\n', encoding='utf-8')
        tl = json.loads(tlf.read_text(encoding='utf-8'))
        fx = next(t for t in tl['tracks'] if t['kind'] == 'effect') if any(t['kind'] == 'effect' for t in tl['tracks']) else None
        if fx is None:
            fx = {'id': 't_fx_slow', 'name': 'slow', 'kind': 'effect', 'clips': []}
            tl['tracks'].insert(0, fx)
        fx['clips'].append({'id': 'slow_1', 'type': 'effect', 'effect': 'slow', 'start': 0, 'dur': 12, 'params': {}})
        tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
        with sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={'width': 1500, 'height': 900})
            pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.goto(srv.url)
            pg.wait_for_function(SA.READY, timeout=120000)
            ev = pg.evaluate
            ev('() => MITTLER_CACHE.setOff(false)')  # 新しいページは既定の切なので入にする
            bs = "async () => await (await api('/api/bake', { cache: 'no-store' })).json()"
            pg.wait_for_function("() => { const s = MITTLER_CACHE.state(); return s.bake && s.bake.state === 'running' && s.bake.done > 0; }", timeout=120000, polling=500)
            ev('() => seek(9.5)')
            t0 = time.time()
            ok = False
            while time.time() - t0 < 3:
                b = ev(bs)
                if b.get('paused') and b.get('workersPaused'):
                    ok = True
                    break
                time.sleep(0.1)
            check(ok, f'シークすると、裏で描いているプロセスを一時停止する（{time.time() - t0:.1f} 秒で）')
            d0 = ev(bs)['done']
            time.sleep(1.5)
            d1 = ev(bs)['done']
            check(d1 == d0, f'止めているあいだは進まない（{d0} → {d1}）')
            t0 = time.time()
            ok = False
            while time.time() - t0 < 8:
                b = ev(bs)
                if not b.get('paused') and not b.get('workersPaused'):
                    ok = True
                    break
                time.sleep(0.2)
            check(ok and time.time() - t0 < 6, f'静かになると続ける（{time.time() - t0:.1f} 秒あと）')
            # 「裏で描く」ボタン：押すと切（今のものも止まる）・切のあいだは自分で始めない・覚える・もう一度押すと入でまた描き始める
            pg.wait_for_function("() => MITTLER_CACHE.state().bake && MITTLER_CACHE.state().bake.state === 'running'", timeout=30000, polling=300)
            pg.click('#bakeBtn')
            time.sleep(0.5)
            b = ev(bs)
            txt = ev("() => document.getElementById('bakeBtn').getAttribute('aria-label')")
            check(b.get('state') == 'stopped' and '切' in txt and ev("() => localStorage.getItem('cc.bakeOff')") == '1', f"ボタンで切：裏で描くのが止まる（{b.get('state')}・{txt}）")
            ev('() => seek(3)')
            time.sleep(6)  # 手を離して 2.5 秒より長く待っても
            b = ev(bs)
            check(b.get('state') != 'running', f"切のあいだは、手を離しても始めない（{b.get('state')}）")
            pg.reload()
            pg.wait_for_function(SA.READY, timeout=120000)
            check(ev('() => MITTLER_CACHE.state().off'), '切は、開き直しても覚えている')
            pg.click('#bakeBtn')
            pg.wait_for_function("async () => (await (await api('/api/bake', { cache: 'no-store' })).json()).state === 'running'", timeout=30000, polling=500)
            txt = ev("() => document.getElementById('bakeBtn').getAttribute('aria-label')")
            check('裏で描く' in txt and '切' not in txt, f'もう一度押すと入：手を離すとまた描き始める（{txt}）')
            ev("async () => api('/api/bake/stop', { method: 'POST' })")
            br.close()
        check(not errs, f'画面のエラーなし {errs[:3]}')
    finally:
        srv.quit()
    if not SA.opt('--work'):
        shutil.rmtree(work, ignore_errors=True)
    print(f'---\nFAIL の数 {len(SA.fails)}')
    sys.exit(1 if SA.fails else 0)


if __name__ == '__main__':
    main()
