"""描画サーバー：時刻 t の1コマを JPEG で返す（編集画面のプレビュー用）。編集画面のサーバー（server/pyrender.js）が同じ PC で起動する。
  python -m mittler serve<timeline.cut.json> [--port 47901] [--hwaccel cuda] [--ahead コマ数]
- 127.0.0.1 だけで待ち受ける。1コマずつ順に描く（エンジンは1つ）。
- タイムラインのファイルが変わったら読み直す（エフェクトのファイルはエンジンが変わったときに読み直す）。
  映像・動画化予定（🎬）のクリップが使う絵・動画のファイルと、エフェクト・字幕のクリップのパラメータが指すファイル（sprite の絵など。2026-11-12）が
  同じ名前で上書きされたときも読み直す（更新時刻を頼みのたびに見る。2026-10-31）。
  JPEG のキャッシュ（120 枚、古いものから捨てる）は、タイムラインか effects/ の下の .py が変わったら捨てる。
- 先読み（2026-10-30）：JPEG の頼み（/frame。prof=1・fmt=png は除く）に答えたあと、0.2 秒ほかの頼みが来なければ、その先のコマ（既定 1 秒ぶん、--ahead）を
  同じ画質・縮小で1コマずつ描いてキャッシュに入れていく（スレッド1本・エンジンは同じ1つを鍵で取り合う）。新しい頼み（/frame・/effects）が来たら、
  描いている先読みはエフェクトの区切りでやめて（Engine.check → Interrupted）、すぐ本線に鍵を渡す。エフェクトは前のコマを覚えないので、どの順に描いても同じ絵。
- GET /frame?t=秒[&q=画質][&fmt=png][&prof=1][&scale=0.5][&draft=1]：JPEG（fmt=png なら劣化なしの PNG。編集画面の「📷 PNG で保存」）。応答ヘッダの X-Mittler-T は描いたコマの時刻、X-Mittler-Ms は描くのにかかった時間。
  prof=1（計測）：キャッシュを使わずに描き、応答ヘッダ X-Mittler-Prof に重いもの上位5件（名前:ms。エフェクトは <エフェクト>@<クリップの id>、ほかに video・subtitle・jpeg）、
  全部の内訳（engine.py の _prof_summary の形＋jpeg）を標準エラーに1行の JSON で出す（編集画面のサーバーのログに [engine] として出る）。
  scale=0.5 など（プレビューの縮小。既定 1）：書き出しのドラフトの scale（__main__.segment）と同じく、等倍で描いてから縮める（エフェクトの params は画素の
  大きさのままなので、小さく描くと位置・太さが変わる）。大きさも同じ（偶数にそろえる）。縮めるのは OpenCV の INTER_AREA（書き出しは ffmpeg の area。
  プレビューで1コマごとに ffmpeg を起こさないため）。JPEG のキャッシュは (t, 画質, scale, draft) ごと。fmt=png（📷）は scale・draft を見ない（いつも等倍・ドラフトでない）。
  draft=1（ドラフト品質、2026-10-30 機能追加案01）：その1コマの間だけ eng.draft を立てて描く（ctx.draft。対応したエフェクトだけが軽く描き、読まないエフェクトは同じ絵）。
  キャッシュも先読みも draft ごとの別の枠（draft=1 の絵を、draft なしの頼みに返さない）。編集画面が再生・シークの間だけ付ける想定（編集画面はまだ付けない）。
- GET /info：タイムラインの名前・長さ・fps と、読み直した回数・先読みで描いたコマ数（prefetched）・このプロセスの pid。
- GET /effects：プロジェクトの effects/*.py の説明（META：名前・パラメータの種類・時刻のパラメータ、STAGE、頭の説明文）。
- GET /flush：JPEG のキャッシュ（と、読んだ Blender の絵）を捨てる（Blender の 3D のためた絵を消したあと）。
- GET /effects_lib：部品の置き場（effects_lib/library.json のフォルダ：common・false_maria）のエフェクトのうち、作品の effects/ にまだ無いもの
  （/effects と同じ形＋ pack＝フォルダの名前。編集画面の「作品に入れる」）。
- Blender の 3D（blender.py）：JPEG のプレビューの間は eng.preview を立てる（ためた本番の絵が無ければ下描きを 1 枚描く。先読みでは描かない）。
- GET /warp?q=JSON：映像クリップ1本の音ハメ（onbeat.py。q と返すものはそちらの説明）。
- GET /quit：止まる。使われないまま idle 秒（既定 1800）たっても止まる（プロセスを残さない）。
"""
import collections
import hashlib
import http.server
import io
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from PIL import Image

from . import fcache
from .engine import Engine, Interrupted

CACHE_N = 2000      # JPEG のキャッシュの枚数（2026-11-16 120 → 2000。縮めたプレビューの JPEG は 1 枚 50〜250 KB。ためた絵の鍵で覚えるので、直しても全部は捨てない）
AHEAD_IDLE = 0.2    # 先読みを始めるまでに、ほかの頼みが来ないのを待つ秒


class _Server(http.server.ThreadingHTTPServer):
    """同じポートに2つ目のサーバーが入らないようにする。Python の HTTP サーバーは SO_REUSEADDR を付けるが、Windows ではそれで
    使われているポートにも入れてしまい、2つのサーバーが同じポートで答えた（2026-10-24：残っていた別の作品のサーバーが答えて、プレビューが真っ黒）。
    入れなければ止まる（編集画面のサーバーが別のポートで起動し直す）"""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _prof_header(pf):
    """X-Mittler-Prof：重いもの上位5件「名前:ms」をカンマでつなぐ（名前の ASCII でない字は %XX にする）"""
    items = [(f'{e}@{cid}', ms) for _, e, cid, ms in pf['fx']] + [(k, pf['stages'][k]) for k in ('video', 'subtitle')] + [(k, pf.get(k, 0.0)) for k in ('shrink', 'jpeg')]
    items = sorted((x for x in items if x[1] > 0), key=lambda x: -x[1])[:5]
    return ','.join(f'{quote(str(n), safe="@._-")}:{ms}' for n, ms in items)


def scale_of(q):
    """?scale= の値（0.1〜1。数でない・1 以上・0 以下は 1＝等倍）"""
    try:
        s = float(q.get('scale', ['1'])[0])
    except ValueError:
        return 1.0
    return round(max(s, 0.1), 3) if 0 < s < 1 else 1.0


def shrink(img, s):
    """等倍の絵を s 倍に縮める（幅・高さは書き出しのドラフトの scale=trunc(iw*s/2)*2:trunc(ih*s/2)*2 と同じ）"""
    import cv2
    h, w = img.shape[:2]
    return cv2.resize(img, (int(w * s / 2) * 2, int(h * s / 2) * 2), interpolation=cv2.INTER_AREA)


def serve(timeline, port, idle=1800, hwaccel=None, ahead=None):
    eng = Engine(timeline, hwaccel=hwaccel)
    lock = threading.Lock()   # エンジン（描くのは1度に1コマ）
    glock = threading.Lock()  # state['gen'] を数える
    ahead = int(round(eng.fps)) if ahead is None else max(0, int(ahead))  # 先読みのコマ数（既定 1 秒ぶん）
    # 読み直すかどうかは、更新時刻だけでなく中身でも見る（更新時刻が秒に丸められる写し方をすると、
    # 1秒のうちに2回直したとき時刻が同じになり、古いタイムラインのまま描いてしまっていた。前の、別の PC に写して描く仕組みで起きた）
    def sig():
        # 編集画面のサーバーがタイムラインを置きかえている瞬間（Windows の rename の途中）は、開けないことがある（PermissionError）。一瞬なので待って読み直す
        for i in range(40):
            try:
                return hashlib.sha1(Path(timeline).read_bytes()).hexdigest()
            except PermissionError:
                if i == 39:
                    raise
                time.sleep(0.01)

    def fx_sig():
        """エフェクトのファイル（effects/ の下の .py。_lib も）の更新時刻。変わったら JPEG のキャッシュを捨てる（同じ時刻でも絵が変わるので）"""
        out = []
        for p in sorted((eng.dir / 'effects').rglob('*.py')):
            try:
                out.append((str(p), p.stat().st_mtime_ns))
            except OSError:
                pass
        return tuple(out)

    def media_files():
        """映像・動画化予定（🎬）のクリップが使う絵・動画のファイル（映像の src、予定のスタート・エンドの絵とテイク）"""
        out = set()
        for tr in eng.tl.get('tracks', []):
            if tr.get('kind') not in ('video', 'plan'):
                continue
            for c in tr.get('clips', []):
                srcs = list(c['src']) if isinstance(c.get('src'), list) else [c.get('src')]  # 写す（タイムラインの中の list に足さない）
                for k in ('start_frame', 'end_frame', 'video'):
                    v = c.get(k) or {}
                    srcs += [v.get('src')] + [x.get('src') for x in v.get('takes') or []]
                out.update(eng.root / s for s in srcs if isinstance(s, str) and s)
        # エフェクト・字幕のクリップのパラメータ（params・style）が指すファイル（sprite の img＝フキダシ・描き文字、書体など。2026-11-12）：
        # 素材の根の下に実在するファイルを指す文字列を拾う。前は見ていなかったので、AI が同じ名前で絵を作り直しても、プレビューは古い絵のままだった
        # （JPEG のキャッシュも ctx.cache の画像も。読み直すと eng.load が ctx.cache を作り直す）

        def walk(v, depth=0):
            if isinstance(v, str):
                if 0 < len(v) < 300 and '\n' not in v and '.' in v:
                    try:
                        p = eng.root / v
                        if p.is_file():
                            out.add(p)
                    except (OSError, ValueError):
                        pass
            elif depth < 6 and isinstance(v, dict):
                for x in v.values():
                    walk(x, depth + 1)
            elif depth < 6 and isinstance(v, list):
                for x in v[:200]:
                    walk(x, depth + 1)
        for tr in eng.tl.get('tracks', []):
            if tr.get('kind') in ('effect', 'subtitle'):
                for c in tr.get('clips', []):
                    walk(c.get('params'))
                    walk(c.get('style'))
        return sorted(out)

    def media_sig(files):
        """そのファイルの更新時刻。同じ名前で上書きされたら（AI が絵を作り直したときなど）読み直す（AI の側から置きかえた絵も画面に出るように）"""
        out = []
        for p in files:
            try:
                out.append(p.stat().st_mtime_ns)
            except OSError:
                out.append(None)
        return tuple(out)

    # gen：本線の頼み（/frame・/effects）が来るたびに増える。先読みは、始めたときの gen と変わったらやめる
    files0 = media_files()
    state = {'mtime': sig(), 'fx': fx_sig(), 'files': files0, 'media': media_sig(files0), 'loads': 1, 'cache': collections.OrderedDict(), 'hit': False, 'full': False, 'kmemo': {},
             'last': time.time(), 'gen': 0, 'ahead': None, 'prefetched': 0}
    wake = threading.Event()

    def fresh():
        mt = sig()
        ms = None if mt != state['mtime'] else media_sig(state['files'])
        if mt != state['mtime'] or ms != state['media']:  # タイムラインが変わった・使う絵や動画のファイルが変わった（同じ名前の上書きも）
            eng.close()
            eng.load()
            files = media_files()
            state.update(mtime=mt, loads=state['loads'] + 1, fx=fx_sig(), files=files, media=media_sig(files))
            drop_unkeyed()
            return
        fs = fx_sig()
        if fs != state['fx']:
            state['fx'] = fs
            drop_unkeyed()

    def drop_unkeyed():
        """タイムライン・エフェクト・素材が変わった：時刻で覚えた絵（ドラフト・ためない描き方）だけ捨てる。ためた絵の鍵で覚えた絵（'k'）は残す
        （鍵がそのコマに効くものから作られているので、直した区間の絵は鍵が変わって使われない。2026-11-16、前は全部捨てていた）"""
        c = state['cache']
        for k in [k for k in c if k[0] != 'k']:
            del c[k]
        state['kmemo'] = {}

    def mem_keys(t, qual, sc, dr):
        """覚えた絵を探す鍵：ためた絵の鍵（ドラフトの頼みでも本番の絵を出す）と、時刻の鍵"""
        fk = fcache.key(eng, t, draft_ok=True)
        return ([('k', fk, qual, sc)] if fk else []) + [(t, qual, sc, dr)]

    def mem_get(t, qual, sc, dr):
        for k in mem_keys(t, qual, sc, dr):
            body = cache_get(k)
            if body is not None:
                return body, k[0] == 'k'
        return None, False

    def mem_put(t, qual, sc, dr, body):
        """本番の品質の絵（ためた絵・描いた本番の絵）は、描いたあとの鍵で（Blender の絵ができると鍵が変わる）。ほかは時刻で"""
        fk = fcache.key(eng, t, draft_ok=True) if state['full'] else None
        cache_put(('k', fk, qual, sc) if fk else (t, qual, sc, dr), body)

    def bump():
        """本線の頼みが来た（先読みに、エフェクトの区切りでやめてもらう）"""
        with glock:
            state['gen'] += 1

    def cache_get(key):
        body = state['cache'].get(key)
        if body is not None:
            state['cache'].move_to_end(key)
        return body

    def cache_put(key, body):
        c = state['cache']
        c[key] = body
        c.move_to_end(key)
        while len(c) > CACHE_N:
            c.popitem(last=False)

    def jpeg(t, qual, sc, dr, pf=None):
        """1コマを（縮めて）JPEG にする。ディスクにためた絵（fcache）があればそれ、無ければ描いて、本番の品質ならためる。
        dr＝ドラフト品質（その1コマの間だけ eng.draft を立てる。ためた本番の絵があれば、そちらを出す）。鍵を取ってから呼ぶ。
        描かずに出したら state['hit'] を立てる（X-Mittler-Cache）"""
        buf = io.BytesIO()
        state['hit'] = False
        img = None
        if pf is None:  # 計測（prof）のときは、いつも描く
            img, _ = fcache.get(eng, t, draft_ok=True)  # ドラフトの頼みでも、ためた本番の絵があればそれ
            state['hit'] = img is not None
        state['full'] = state['hit']
        if img is None:
            prev = eng.draft
            eng.draft = dr
            eng.preview = True  # プレビュー（Blender の 3D は、ためた本番の絵が無ければ下描きで。blender.py。ほかのエフェクトの絵は変わらない）
            try:
                img = eng.render(t, pf)
                state['full'] = not dr and pf is None and not eng.used_draft
                if not dr and pf is None:
                    fcache.put(eng, t, img)
            finally:
                eng.draft = prev
                eng.preview = False
        if sc < 1:
            ts_ = time.perf_counter()
            img = shrink(img, sc)
            if pf is not None:
                pf['shrink'] = round((time.perf_counter() - ts_) * 1000, 1)
        tj = time.perf_counter()
        Image.fromarray(img).save(buf, 'JPEG', quality=qual)
        if pf is not None:
            pf['jpeg'] = round((time.perf_counter() - tj) * 1000, 1)
        return buf.getvalue()

    def prefetch():
        """先読みのスレッド：最後の頼みのあと、ほかの頼みが来なければ、その先のコマを順にキャッシュへ"""
        while True:
            wake.wait()
            wake.clear()
            job = state['ahead']
            if not job:
                continue
            t, qual, sc, dr, g = job
            time.sleep(AHEAD_IDLE)
            n0 = int(round(t * eng.fps))

            def stop():
                if state['gen'] != g:
                    raise Interrupted()
            for i in range(1, ahead + 1):
                if state['gen'] != g:
                    break
                with lock:
                    if state['gen'] != g:
                        break
                    try:
                        fresh()
                        tt = (n0 + i) / eng.fps  # 本線の round(t * fps) / fps と同じ値
                        if tt >= eng.duration:
                            break
                        if mem_get(tt, qual, sc, dr)[0] is not None:
                            continue
                        eng.check = stop
                        body = jpeg(tt, qual, sc, dr)
                    except Interrupted:
                        break
                    except Exception as e:  # 描けないコマ（エフェクトの間違いなど）：先読みはやめる。本線で頼まれたらエラーを返す
                        print(f'先読みをやめた（{(n0 + i) / eng.fps:.3f}秒）: {e}', file=sys.stderr, flush=True)
                        break
                    finally:
                        eng.check = None
                    mem_put(tt, qual, sc, dr, body)
                    state['prefetched'] += 1

    if ahead:
        threading.Thread(target=prefetch, daemon=True).start()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype, extra=None):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            state['last'] = time.time()
            try:
                if u.path == '/quit':
                    self.send(200, b'bye', 'text/plain')
                    threading.Thread(target=srv.shutdown, daemon=True).start()
                    return
                if u.path == '/effects':
                    bump()
                    with lock:
                        out = {}
                        for p in sorted((eng.dir / 'effects').glob('*.py')):
                            mod = eng.effect(p.stem)
                            # doc_en：英語の画面の説明（エフェクトの DOC_EN。無ければ空＝日本語の doc を出す。docs/エフェクトの書き方.md）
                            out[p.stem] = {'meta': getattr(mod, 'META', {}), 'stage': getattr(mod, 'STAGE', 'v7'), 'doc': (mod.__doc__ or '').strip(),
                                           'doc_en': str(getattr(mod, 'DOC_EN', '') or '').strip(), 'file': f'effects/{p.name}'}
                    return self.send(200, json.dumps(out, ensure_ascii=False, default=str).encode('utf-8'), 'application/json; charset=utf-8')
                if u.path == '/flush':  # JPEG のキャッシュを捨てる（Blender の 3D のためた絵を消したあと。/api/blender/clear）
                    with lock:
                        state['cache'].clear()
                        eng.cache.pop('blender.frames', None)
                    return self.send(200, b'ok', 'text/plain')
                if u.path == '/effects_lib':  # 部品の置き場（effects_lib/library.json のフォルダ）にあって、作品の effects/ にまだ無いもの（編集画面の「作品に入れる」。2026-11-13）
                    import importlib.util
                    base = Path(__file__).resolve().parents[2] / 'effects_lib'
                    try:  # 置き場のフォルダの並び（2026-11-13 公開の準備：偽マリアのエフェクト集 false_maria を足した）
                        packs = [str(x['dir']) for x in json.loads((base / 'library.json').read_text(encoding='utf-8'))['packs']]
                    except (OSError, ValueError, KeyError, TypeError):
                        packs = ['common']
                    out = {}
                    for pack in packs:
                        for p in sorted((base / pack).glob('*.py')):
                            if p.stem in out or (eng.dir / 'effects' / p.name).exists():
                                continue
                            try:
                                spec = importlib.util.spec_from_file_location(f'mittler_lib_{p.stem}', p)
                                mod = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(mod)
                                out[p.stem] = {'meta': getattr(mod, 'META', {}), 'stage': getattr(mod, 'STAGE', 'v7'), 'doc': (mod.__doc__ or '').strip(),
                                               'doc_en': str(getattr(mod, 'DOC_EN', '') or '').strip(), 'file': f'effects_lib/{pack}/{p.name}', 'pack': pack}
                            except Exception as e:  # noqa: BLE001
                                out[p.stem] = {'meta': {}, 'error': f'{type(e).__name__}: {e}', 'pack': pack}
                    return self.send(200, json.dumps(out, ensure_ascii=False, default=str).encode('utf-8'), 'application/json; charset=utf-8')
                if u.path == '/warp':  # 音ハメ（onbeat.py）。描くのとは別（エンジンの鍵を取らない。解析は数秒〜数十秒）
                    from .onbeat import auto
                    out = auto(eng.dir, eng.root, json.loads(q.get('q', ['{}'])[0]))
                    return self.send(200, json.dumps(out, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')
                if u.path == '/cachemap':  # ためた絵の地図（2026-11-16）：コマごとの鍵（ためてあれば。無ければ ''）。編集画面の目盛りの印と、▶ でためた絵を流すのに使う
                    fps = eng.fps
                    n0 = max(0, int(round(float(q.get('from', ['0'])[0]) * fps)))
                    n1 = int(round(min(float(q.get('to', [str(eng.duration)])[0]), eng.duration) * fps))
                    keys = []
                    n = n0
                    while n < n1:  # 200 コマずつ鍵を取る（そのあいだにプレビューの頼みが入れる）
                        with lock:
                            fresh()
                            memo = state['kmemo']
                            bl = [(float(c['start']), float(c['start']) + float(c['dur'])) for c in eng.effect_clips if c.get('effect') == 'blender3d']
                            for m in range(n, min(n1, n + 200)):
                                t = m / fps
                                k = memo.get(m)
                                if k is None:
                                    k = fcache.key(eng, t) or ''
                                    if not any(s <= t < e for s, e in bl):  # Blender の絵のコマは、描けると鍵が変わるので覚えない
                                        memo[m] = k
                                keys.append(k if k and fcache.preview_of(eng, k).is_file() else '')
                        n += 200
                    body = json.dumps({'fps': fps, 'n0': n0, 'keys': keys}, separators=(',', ':'))
                    return self.send(200, body.encode('utf-8'), 'application/json')
                if u.path == '/info':
                    with lock:
                        fresh()
                        body = json.dumps({'name': eng.tl.get('name'), 'duration': eng.duration, 'fps': eng.fps, 'loads': state['loads'],
                                           'prefetched': state['prefetched'], 'pid': os.getpid()}, ensure_ascii=False)
                    return self.send(200, body.encode('utf-8'), 'application/json; charset=utf-8')
                if u.path == '/frame':
                    t = float(q.get('t', ['0'])[0])
                    qual = int(q.get('q', ['88'])[0])
                    bump()  # 先読みは、描いているコマをエフェクトの区切りでやめて鍵を渡す
                    if q.get('fmt', [''])[0] == 'png':  # 劣化なしの1コマ（覚えておかない。draft は見ない＝eng.draft は False のまま）
                        with lock:
                            fresh()
                            t = round(t * eng.fps) / eng.fps
                            buf = io.BytesIO()
                            Image.fromarray(eng.render(t)).save(buf, 'PNG')
                        return self.send(200, buf.getvalue(), 'image/png', {'X-Mittler-T': repr(t)})
                    pf = {} if q.get('prof', [''])[0] == '1' else None  # 計測：キャッシュを使わずに描いて内訳を測る
                    sc = scale_of(q)  # プレビューの縮小（1＝等倍）
                    dr = q.get('draft', [''])[0] == '1'  # ドラフト品質（ctx.draft。対応したエフェクトだけが軽く描く）
                    with lock:
                        fresh()
                        t = round(t * eng.fps) / eng.fps  # コマにそろえる
                        t0 = time.time()
                        # 覚えた絵：ためた絵の鍵（本番の品質。ドラフトの頼みにも出す）か時刻の鍵（ドラフトの絵は別の枠。draft=1 の絵を、ドラフトでない頼みに返さない）
                        body, hit = mem_get(t, qual, sc, dr) if pf is None else (None, False)
                        if body is None:
                            body = jpeg(t, qual, sc, dr, pf)
                            hit = state['hit']
                            if pf is None:
                                mem_put(t, qual, sc, dr, body)
                        ms = int((time.time() - t0) * 1000)
                        g = state['gen']
                    extra = {'X-Mittler-T': repr(t), 'X-Mittler-Ms': str(ms), 'X-Mittler-Loads': str(state['loads'])}
                    if hit:
                        extra['X-Mittler-Cache'] = 'disk'  # ディスクにためた絵（fcache）。描いていない
                    if pf is not None:
                        extra['X-Mittler-Prof'] = _prof_header(pf)
                        print(json.dumps({'prof': pf, 't': t, 'ms': ms, 'q': qual, 'scale': sc, 'draft': dr}, ensure_ascii=False), file=sys.stderr, flush=True)
                    elif ahead:  # 先読みを頼む（計測のときはしない）。この間にもっと新しい頼みが来ていれば、そちらの答えのあとに
                        state['ahead'] = (t, qual, sc, dr, g)
                        wake.set()
                    return self.send(200, body, 'image/jpeg', extra)
                return self.send(404, b'not found', 'text/plain')
            except Exception as e:  # 描けなかったら理由を返す（エフェクトのコードの間違いなど）
                import traceback
                return self.send(500, traceback.format_exc().encode('utf-8'), 'text/plain; charset=utf-8')

    srv = _Server(('127.0.0.1', port), H)

    def watchdog():
        while True:
            time.sleep(30)
            if time.time() - state['last'] > idle:
                print('idle, quit', flush=True)
                srv.shutdown()
                return
    threading.Thread(target=watchdog, daemon=True).start()
    print(f'serving {timeline} on 127.0.0.1:{port}', flush=True)
    try:
        srv.serve_forever()
    finally:
        eng.close()
