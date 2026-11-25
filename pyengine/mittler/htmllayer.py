"""HTML のレイヤー（2026-11-18）。バニラの JavaScript や three.js で書いた絵を、Python のエンジンの Mittler でも重ねられるようにする、
HTML ベースの VFX のレイヤー（描くのは Playwright の Chromium）。タイムラインのエフェクトのクリップ `html`（effects_lib/common/html.py）が使う。

クリップ（effect: "html"）の params：page（作品の root からの相対：`html/<名前>/index.html`）・args（ページに渡す dict）・seed（乱数の種）・blend（over／add／screen）・opacity
描き方：
- このプロセスに 1 つ、ヘッドレスの Chromium（Playwright）を専用のスレッドで動かす（Playwright の sync API はスレッドをまたげないため）。
  クリップごとにページを 1 枚開いたままにして（大きさ＝描く大きさ）、1 コマごとに `__mittlerRender(秒, args, コマ番号)` を呼んでから、透明の背景で撮る（CDP の
  Page.captureScreenshot・PNG）。ページのフォルダの中身が変わったら、開き直す。
- ページより先に html_runtime.js を読ませて、時刻（Date.now・performance.now・requestAnimationFrame）と乱数（Math.random）を Mittler が決める。
  絵は「クリップの頭からの秒」だけで決まる（ページの書き方の決まりは docs/エフェクトの書き方.md の「HTML のレイヤー」）。
- ページの JavaScript のエラーは、その時刻の絵を描かずに理由つきで止める（黙って抜かさない）。
- 外への通信はしない：ページは作品の中のファイル。モジュールの import（three.js など）は file:// では読めない（CORS）ので、作品の html/ と assets/ だけを配る
  小さなサーバーを 127.0.0.1 に立てて、そこから開く（ほかのフォルダ・状態フォルダのトークンは配らない）。ライブラリも作品の html/vendor/ に置く（ひな形は templates/html/）。
- Chromium の置き場：環境変数 PLAYWRIGHT_BROWSERS_PATH → 作者の PC の既定（server/defaults.author.json の playwrightBrowsers。あれば）→ Playwright の既定。
- GPU で描くページ（WebGL・three.js）は、別の PC・GPU で画素が少し違ってよい（3D と同じ例外）。同じ PC なら同じ時刻は同じ絵。
"""
import atexit
import base64
import http.server
import json
import os
import queue
import threading
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import numpy as np

from .defaults import author

RUNTIME = Path(__file__).with_name('html_runtime.js')
DEFAULTS = {'page': 'html/kinetic/index.html', 'args': {}, 'seed': 1, 'blend': 'over', 'opacity': 1.0}
LOAD_TIMEOUT = 60     # ページを読み終わるまで（秒）
FRAME_TIMEOUT = 60    # 1 コマ（秒）
KEEP_PAGES = 8        # 開いたままにするページの数（こえたら古いものから閉じる）


def _t(key, **kw):
    from .i18n import t
    return t(key, **kw)


class HtmlError(RuntimeError):
    pass


def page_files(page):
    """ページの絵に効くファイル：ページのフォルダの下の全部と、となりの vendor/（three.js など）。fcache の鍵とページの開き直しに使う"""
    page = Path(page)
    out = []
    for d in (page.parent, page.parent.parent / 'vendor'):
        if d.is_dir():
            for i, p in enumerate(sorted(d.rglob('*'))):
                if i > 2000:
                    break
                if p.is_file():
                    out.append(p)
    return out


def _sig(page):
    out = []
    for p in page_files(page):
        try:
            st = p.stat()
            out.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    return hash(tuple(out))


SERVE_DIRS = ('html', 'assets')  # ページのサーバーが配るフォルダ（作品の root の下）


def _server(root):
    """作品の html/ と assets/ だけを配るサーバー（127.0.0.1・空いているポート）。.js は text/javascript で（モジュールの import のため）"""
    root = Path(root).resolve()

    class H(http.server.SimpleHTTPRequestHandler):
        extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map, **{
            '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.wasm': 'application/wasm', '.svg': 'image/svg+xml'})

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

        def send_head(self):
            rel = unquote(urlparse(self.path).path).lstrip('/')
            first = rel.split('/', 1)[0]
            try:
                full = (root / rel).resolve()
                ok = first in SERVE_DIRS and full.is_relative_to(root / first)
            except (OSError, ValueError):
                ok = False
            if not ok:
                self.send_error(403)
                return None
            return super().send_head()

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name='mittler-html-files', daemon=True).start()
    return srv


class _Host:
    """ヘッドレスの Chromium を 1 つ、専用のスレッドで持つ"""

    def __init__(self):
        self.q = queue.Queue()
        self.err = None
        self.pages = {}   # クリップの id → (鍵, {ctx, page, cdp, errs})
        self.order = []
        self.servers = {}  # 作品の root → ページのサーバー
        up = threading.Event()
        self.th = threading.Thread(target=self._run, args=(up,), name='mittler-html', daemon=True)
        self.th.start()
        up.wait(180)
        if self.err:
            raise self.err

    def _run(self, up):
        try:
            if not os.environ.get('PLAYWRIGHT_BROWSERS_PATH'):
                bp = author('playwrightBrowsers', '')
                if bp and os.path.isdir(bp):
                    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = bp
            from playwright.sync_api import sync_playwright
            self.pw = sync_playwright().start()
            # ログ：Chromium は GPU のドライバーのお知らせ（NVIDIA の「GPU stall due to ReadPixels」＝WebGL の絵を読み出すときの性能の注意。絵は正しい）を
            # ERROR の書式で、描く python の作業フォルダ（＝作品のフォルダ）の debug.log に書いていた（2026-11-19、作者の作品で見つかった。git にも混ざる）。
            # 致命的なものだけにして（--log-level=3）、書くなら一時フォルダへ
            import tempfile
            log = Path(tempfile.gettempdir()) / 'mittler_chromium.log'
            self.browser = self.pw.chromium.launch(args=['--ignore-gpu-blocklist', '--enable-unsafe-swiftshader', '--disable-background-timer-throttling',
                                                         '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
                                                         '--log-level=3', f'--log-file={log}'])
        except Exception as e:  # noqa: BLE001
            self.err = HtmlError(_t('html.noBrowser', err=f'{type(e).__name__}: {e}'.splitlines()[0][:400]))
            up.set()
            return
        up.set()
        while True:
            job = self.q.get()
            if job is None:
                break
            fn, box, ev = job
            try:
                box['r'] = fn()
            except Exception as e:  # noqa: BLE001
                box['e'] = e
            ev.set()
        try:
            self.browser.close()
            self.pw.stop()
        except Exception:  # noqa: BLE001
            pass
        for srv in self.servers.values():
            srv.shutdown()

    def url(self, root, page):
        """ページの URL（作品のページのサーバーから）"""
        root = Path(root).resolve()
        srv = self.servers.get(str(root))
        if srv is None:
            srv = self.servers[str(root)] = _server(root)
        rel = Path(page).resolve().relative_to(root).as_posix()
        return f'http://127.0.0.1:{srv.server_address[1]}/' + quote(rel)

    def call(self, fn, timeout):
        box, ev = {}, threading.Event()
        self.q.put((fn, box, ev))
        if not ev.wait(timeout):
            raise HtmlError(_t('html.timeout', s=timeout))
        if 'e' in box:
            raise box['e']
        return box['r']

    # ---- ここから下は Chromium のスレッドで動く ----
    def _close(self, cid):
        got = self.pages.pop(cid, None)
        if cid in self.order:
            self.order.remove(cid)
        if got:
            try:
                got[1]['ctx'].close()
            except Exception:  # noqa: BLE001
                pass

    def _open(self, cid, key, url, init):
        old = self.pages.get(cid)
        if old and old[0] == key:
            self.order.remove(cid)
            self.order.append(cid)
            return old[1]
        # 読み込みの一時的な失敗（net::ERR_NO_BUFFER_SPACE など。メモリが苦しいときの通信の失敗）は、少し待って開き直す（2026-11-22。
        # 並列の書き出しで、書体の大きいページが多い作品の途中で 1 回起きて、書き出し全体が止まった）。ページの中のまちがい（JavaScript のエラー）は開き直さない
        for i in range(3):
            try:
                return self._open1(cid, key, url, init)
            except HtmlError as e:
                if i == 2 or 'net::ERR_' not in str(e):
                    raise
                time.sleep(2.0 * (i + 1))

    def _open1(self, cid, key, url, init):
        self._close(cid)
        ctx = self.browser.new_context(viewport={'width': init['W'], 'height': init['H']}, device_scale_factor=1)
        ctx.add_init_script(script='window.__MITTLER_INIT = ' + json.dumps(init, ensure_ascii=False) + ';')
        ctx.add_init_script(path=str(RUNTIME))
        page = ctx.new_page()
        page.set_default_timeout(LOAD_TIMEOUT * 1000)
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
        ent = {'ctx': ctx, 'page': page, 'errs': errs}
        self.pages[cid] = (key, ent)
        self.order.append(cid)
        while len(self.order) > KEEP_PAGES:
            self._close(self.order[0])
        try:
            page.goto(url, wait_until='load')
            page.evaluate('async () => await window.__mittlerReady()')
        except Exception as e:  # noqa: BLE001
            self._close(cid)
            raise HtmlError(_t('html.loadFail', page=url, err=(errs[:1] or [str(e).splitlines()[0]])[0][:400]))
        if errs:
            msg = errs[0]
            self._close(cid)
            raise HtmlError(_t('html.jsError', page=url, err=msg[:400]))
        cdp = ctx.new_cdp_session(page)
        cdp.send('Emulation.setDefaultBackgroundColorOverride', {'color': {'r': 0, 'g': 0, 'b': 0, 'a': 0}})
        ent['cdp'] = cdp
        return ent

    def render(self, cid, key, url, init, lt, args, n):
        ent = self._open(cid, key, url, init)
        page = ent['page']
        try:
            page.evaluate('async ([t, a, n]) => await window.__mittlerRender(t, a, n)', [lt, args, n])
        except Exception as e:  # noqa: BLE001  onFrame の中で投げた（ReferenceError など）
            self._close(cid)
            msg = str(e).splitlines()[0]
            raise HtmlError(_t('html.jsError', page=url, err=msg.split(': ', 1)[-1][:400])) from None
        if ent['errs']:
            msg = ent['errs'][0]
            self._close(cid)
            raise HtmlError(_t('html.jsError', page=url, err=msg[:400]))
        r = ent['cdp'].send('Page.captureScreenshot', {'format': 'png', 'optimizeForSpeed': True, 'fromSurface': True, 'captureBeyondViewport': False})
        return base64.b64decode(r['data'])


_HOST = None
_LOCK = threading.Lock()


def _host():
    global _HOST
    with _LOCK:
        if _HOST is None or not _HOST.th.is_alive():
            _HOST = _Host()
        return _HOST


@atexit.register
def close_all():
    h = _HOST
    if h is not None and h.th.is_alive():
        h.q.put(None)
        h.th.join(timeout=10)


def _decode(png, W, H):
    try:
        import cv2
        a = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
        if a is None:
            raise ValueError
        if a.ndim == 2:
            a = np.dstack([a, a, a, np.full_like(a, 255)])
        elif a.shape[2] == 3:
            a = np.dstack([a[..., ::-1], np.full(a.shape[:2], 255, np.uint8)])
        else:
            a = a[..., [2, 1, 0, 3]]
    except (ImportError, ValueError):
        from io import BytesIO

        from PIL import Image
        a = np.asarray(Image.open(BytesIO(png)).convert('RGBA'))
    if a.shape[:2] != (H, W):
        from PIL import Image
        a = np.asarray(Image.fromarray(np.ascontiguousarray(a)).resize((W, H), Image.BILINEAR))
    return a


def params(clip):
    p = dict(DEFAULTS)
    p.update(clip.get('params') or {})
    return p


def frame(ctx, clip):
    """このコマの、このクリップのページの絵（RGBA の uint8 H×W×4。色は乗算していない）"""
    eng = ctx.eng
    p = params(clip)
    rel = str(p.get('page') or '')
    page = (eng.root / rel).resolve() if rel else None
    if page is None or not page.is_file():
        raise HtmlError(_t('html.noPage', path=rel))
    W, H = int(ctx.W), int(ctx.H)
    args = p.get('args') if isinstance(p.get('args'), dict) else {}
    seed = int(p.get('seed') or 1)
    init = {'W': W, 'H': H, 'fps': eng.fps, 'scale': getattr(ctx, 'scale', 1), 'draft': bool(getattr(ctx, 'draft', False)), 'seed': seed,
            'args': args, 'dur': float(clip.get('dur') or 0)}
    key = (str(page), _sig(page), W, H, seed, bool(init['draft']), json.dumps(args, sort_keys=True, ensure_ascii=False, default=str))
    lt = float(ctx.t) - float(clip.get('start') or 0)
    n = int(round(lt * eng.fps))
    if not page.is_relative_to(eng.root.resolve() / 'html'):
        raise HtmlError(_t('html.noPage', path=rel))
    h = _host()
    url = h.url(eng.root, page)
    png = h.call(lambda: h.render(str(clip.get('id') or rel), key, url, init, lt, args, n), FRAME_TIMEOUT)
    return _decode(png, W, H)


def layer(ctx, f, clip):
    """'v7' 段：このコマのページの絵を f に重ねる（effects_lib/common/html.py の apply）"""
    p = params(clip)
    img = frame(ctx, clip)
    a = img[..., 3:4].astype(np.float32) * (float(p.get('opacity', 1.0)) / 255.0)
    rgb = img[..., :3].astype(np.float32)
    mode = p.get('blend', 'over')
    if mode == 'add':
        f += rgb * a
    elif mode == 'screen':
        fc = np.clip(f, 0, 255)
        f[:] = fc + (rgb * a) * (1 - fc / 255.0)
    else:
        f *= (1 - a)
        f += rgb * a
    return f
