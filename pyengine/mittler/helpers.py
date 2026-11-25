"""エフェクトが共通で使う小さな部品（偽マリアMV の fx7.py の頭と下の部品をそのまま写したもの）。
マスクの読み込み（2026-10-30）：read_gray が、デコードしたグレーの PNG を LRU で覚える（load_matte もこれを通る）。
ドラフト品質（2026-10-30）：draft_n(ctx, n) は ctx.draft のとき数を 1/3 に（下限 lo）、そうでなければ n のまま。
マスター書き出し（2026-10-30、機能追加案03 v2）：load_matte・face_box は ctx.scale 倍のキャンバスに合わせて返す（scale 1・fps そのままなら今までと同じ）。
draw_sprite・outline・paste_piece の中の px（落ち影のずれ・ぼかし）は scale を見ない（使うエフェクトが渡す値で合わせる）。"""
import bisect
import collections
import math
import os

import cv2
import numpy as np

# デコードしたマスク（グレーの PNG）の LRU：パス → ((更新時刻 ns, 大きさ), uint8 の配列)。上限は set_mask_cache_mb（既定 512 MB）
_GRAY = collections.OrderedDict()
_gray = {'bytes': 0, 'limit': 512 << 20}


def set_mask_cache_mb(mb):
    """マスクの LRU のメモリの上限（MB。0 なら覚えない）。エンジンが timeline の settings.cache.mask_mb（既定 512）で呼ぶ"""
    _gray['limit'] = max(0, int(mb)) << 20
    _gray_trim()


def _gray_drop(key):
    got = _GRAY.pop(key, None)
    if got:
        _gray['bytes'] -= got[1].nbytes


def _gray_trim():
    while _GRAY and _gray['bytes'] > _gray['limit']:
        _gray_drop(next(iter(_GRAY)))


def read_gray(path):
    """グレーの PNG（人のマスクなど）を uint8 で読む。無ければ（読めなければ）None。
    デコードしたものを LRU で覚えておき、次は読み直さない（ファイルの更新時刻か大きさが変わっていたら捨てて読み直す）。
    返すのは覚えている配列そのもの（書き換えられないようにしてある。変えるときは astype などで写してから）"""
    key = str(path)
    try:
        st = os.stat(key)
    except OSError:
        _gray_drop(key)
        return None
    sig = (st.st_mtime_ns, st.st_size)
    got = _GRAY.get(key)
    if got and got[0] == sig:
        _GRAY.move_to_end(key)
        return got[1]
    _gray_drop(key)
    m = cv2.imread(key, cv2.IMREAD_GRAYSCALE)
    if m is None:
        return None
    m.flags.writeable = False
    if m.nbytes <= _gray['limit']:
        _GRAY[key] = (sig, m)
        _gray['bytes'] += m.nbytes
        _gray_trim()
    return m


def ease_out_back(p, s=2.2):
    p = min(max(p, 0.0), 1.0) - 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


def smooth(p):
    p = min(max(p, 0.0), 1.0)
    return p * p * (3 - 2 * p)


def draft_n(ctx, n, lo=1):
    """ドラフトのとき数を減らす（粒・コピー・残像の段数など）。ctx.draft（機能追加案01）が無い古いエンジンでも落ちないように getattr"""
    return max(lo, n // 3) if getattr(ctx, 'draft', False) else n


class Beats:
    """拍の表 [[時刻, 小節の頭か, 強さ(kick)], …]"""
    def __init__(self, beats):
        self.t = [b[0] for b in beats]
        self.b = beats

    def pulse(self, t, decay=0.14, only_down=False, min_kick=0.0):
        """直前の拍からの減衰（0〜1）。強い拍ほど大きい。"""
        i = bisect.bisect_right(self.t, t) - 1
        best = 0.0
        for j in range(i, max(i - 3, -1), -1):
            tb, down, kick = self.b[j]
            if only_down and not down or kick < min_kick:
                continue
            v = math.exp(-(t - tb) / decay) * (1.0 if down else 0.7) * (0.6 + 0.4 * kick)
            best = max(best, v)
        return best

    def hits(self, t0, t1, only_down=False, min_kick=0.0):
        return [(tb, d, k) for tb, d, k in self.b if t0 <= tb < t1 and (d or not only_down) and k >= min_kick]


def paste_piece(f, pc, sc, rot):
    """RGBA（＋発光3ch）のかけらを、字の中心 (cx, cy) まわりに sc 倍・rot 度で f に貼る。"""
    img, x, y, cx, cy = pc
    h, w = img.shape[:2]
    H, W = f.shape[:2]
    if sc < 0.02:
        return f
    lcx, lcy = cx - x, cy - y  # かけらの中の字の中心
    Mx = cv2.getRotationMatrix2D((float(lcx), float(lcy)), rot, sc)
    # 拡大ではみ出す分の余白
    pad = int(max(w, h) * max(sc - 1, 0) * 0.6 + 8)
    Mx[0, 2] += pad
    Mx[1, 2] += pad
    ow, oh = w + 2 * pad, h + 2 * pad
    pm = img[..., :3] * img[..., 3:4]
    rgbA = cv2.warpAffine(np.dstack([pm, img[..., 3]]), Mx, (ow, oh), flags=cv2.INTER_LINEAR, borderValue=0)
    X0, Y0 = int(x) - pad, int(y) - pad
    xa, ya, xb, yb = max(X0, 0), max(Y0, 0), min(X0 + ow, W), min(Y0 + oh, H)
    if xa >= xb or ya >= yb:
        return f
    if img.shape[2] >= 7:  # 発光（すべての文字で加算で足す）を、シールより先に
        gw = cv2.warpAffine(np.ascontiguousarray(img[..., 4:7]), Mx, (ow, oh), flags=cv2.INTER_LINEAR, borderValue=0)
        g = gw[ya - Y0:yb - Y0, xa - X0:xb - X0]
        f[ya:yb, xa:xb] = np.minimum(f[ya:yb, xa:xb] + g, 255)
    sub = rgbA[ya - Y0:yb - Y0, xa - X0:xb - X0]
    a = sub[..., 3:4]
    f[ya:yb, xa:xb] = f[ya:yb, xa:xb] * (1 - a) + sub[..., :3]
    return f


def outline(f, m_s, w1, w2, c1, c2, W, H, amt=1.0):
    """人の外側に白→色の2段（マスクの解像度で距離をとって、1920 へ）。"""
    b = (m_s > 0.5).astype(np.uint8)
    d = cv2.distanceTransform((1 - b) * 255, cv2.DIST_L2, 5)
    a1 = np.clip(w1 - d + 0.5, 0, 1) * (1 - b)
    a2 = np.clip(w1 + w2 - d + 0.5, 0, 1) * (1 - b)
    a1 = cv2.resize(a1, (W, H), interpolation=cv2.INTER_LINEAR) * amt
    a2 = cv2.resize(a2, (W, H), interpolation=cv2.INTER_LINEAR) * amt
    f = f * (1 - a2[..., None]) + np.array(c2, np.float32) * a2[..., None]
    return f * (1 - a1[..., None]) + np.array(c1, np.float32) * a1[..., None]


def face_box(ctx, cut, fi):
    """そのコマの主役の顔の箱（いちばん大きく、人物マスクの上にあるもの）。前後2コマの平均でならす。無ければ None。
    顔と手の点は root の work/fx/cache/landmarks/<カット>.json（偽マリアMV の landmarks.py）。
    マスター書き出し：箱は ctx.scale 倍のキャンバスの座標で返す。fi は ctx.fps の番号（タイムラインの fps の番号に直して読む）"""
    fi = _tl_frame(ctx, fi)
    s = ctx.eng.scale
    if s != 1:
        b = face_box_at(ctx, cut, fi)
        return None if b is None else b * np.float32(s)
    return face_box_at(ctx, cut, fi)


def face_box_at(ctx, cut, fi):
    """face_box の中身（fi はタイムラインの fps の番号、箱はタイムラインの大きさの座標）"""
    import json
    lm = ctx.cache.setdefault('landmarks', {})
    if cut not in lm:
        p = ctx.root / 'work' / 'fx' / 'cache' / 'landmarks' / f'{cut}.json'
        lm[cut] = json.loads(p.read_text(encoding='utf-8'))['frames'] if p.exists() else {}
    fr = lm[cut]
    bs = []
    for k in range(fi - 2, fi + 3):
        fs = [x for x in fr.get(str(k), {}).get('faces', []) if x.get('matte', 1) >= 0.3]
        if fs:
            bs.append(max(fs, key=lambda x: (x['box'][2] - x['box'][0]) * (x['box'][3] - x['box'][1]))['box'])
    if not bs:
        return None
    return np.mean(np.array(bs, np.float32), axis=0)


def _tl_frame(ctx, fi):
    """コマ番号 fi（ctx.fps の番号）→ タイムラインの fps の番号（マスター書き出しで fps を上書きしたとき。マスク・顔の点はタイムラインの fps で並んでいる）"""
    eng = ctx.eng
    if eng.fps != eng.tl_fps:
        return int(round(fi * eng.tl_fps / eng.fps))
    return fi


def load_matte(ctx, cut, fi, name):
    """人のマスク（root の work/fx/cache/<name>/<カット>/<コマ>.png、960x540、0〜1）。無ければ None。
    PNG のデコードは read_gray の LRU を通る（同じコマを描き直すとき・同じマスクを2つのエフェクトが読むときに読み直さない）。返すのは毎回新しい配列。
    マスター書き出し（機能追加案03 v2）：ctx.scale が 1 でなければ s 倍に拡大して返す（960×540 → 1920×1080。cv2 の線形）。
    fps を上書きしたとき（60fps）は、fi をタイムラインの fps の番号に直して読む"""
    fi = _tl_frame(ctx, fi)
    m = read_gray(ctx.root / 'work' / 'fx' / 'cache' / name / str(cut) / f'{fi:05d}.png')
    if m is None:
        return None
    m = m.astype(np.float32) / 255  # 960x540
    s = ctx.eng.scale
    if s != 1:
        m = cv2.resize(m, (int(round(m.shape[1] * s)), int(round(m.shape[0] * s))), interpolation=cv2.INTER_LINEAR)
    return m


def grid(ctx):
    """細かい拍（4分＋8分の裏、[時刻, 強さ]）＝メタデータの pulse_grid"""
    g = ctx.cache.get('pulse_grid')
    if g is None:
        it = ctx.eng._meta_kind('pulse_grid').get('items', [])
        g = ctx.cache['pulse_grid'] = ([x[0] for x in it], [x[1] for x in it])
    return g


def draw_sprite(ctx, f, it, fr, m=None, ks=1.0):
    """ちび・スタンプを1つ貼る（偽マリアMV の fx7.sprites の中身）。it：{x, y（足もと＝下の中心）, h（高さ px）, t0, t1, phase, flip, rot, wobble,
    attach: 'face'（顔の箱に付ける：x, y は顔の幅・高さに対する割合で中心からのずれ、h も顔の高さに対する割合）, behind（人の後ろ）}。
    fr：絵のコマの並び（RGBA float32）。ポンと出て、拍で弾み、ポンと消える。ks：落ち影の詰め（スタンプは sticker_global.shadow）。"""
    t = ctx.t
    bounce = 1 + 0.08 * ctx.beats.pulse(t, 0.12)
    t0, t1 = it['t0'], it['t1']
    if not (t0 <= t < t1) or not fr:
        return f
    k = int(((t - t0) + it.get('phase', 0.0)) * 24) % len(fr)
    img = fr[k]
    if it.get('flip'):
        img = img[:, ::-1]
    x, y, hh = it['x'], it['y'], it['h']
    if it.get('attach') == 'face':
        fb = face_box(ctx, ctx.cut, ctx.sfi)
        if fb is None:
            return f
        fw, fh = fb[2] - fb[0], fb[3] - fb[1]
        x = (fb[0] + fb[2]) / 2 + it['x'] * fw
        y = (fb[1] + fb[3]) / 2 + it['y'] * fh
        hh = it['h'] * fh
    it = dict(it, x=x, y=y, h=hh)
    sc = it['h'] / img.shape[0]
    pin = (t - t0) / 0.22
    sc *= ease_out_back(pin) if pin < 1 else 1.0
    pout = (t1 - t) / 0.14
    if pout < 1:
        sc *= smooth(pout)
    sc *= bounce
    if sc < 0.02:
        return f
    h, w = int(img.shape[0] * sc), int(img.shape[1] * sc)
    if h < 2 or w < 2:
        return f
    im = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_LINEAR)
    rot = it.get('rot', 0.0) + it.get('wobble', 0.0) * math.sin(t * 5.0 + it.get('phase', 0.0) * 3)
    if pin < 1:
        rot += (1 - smooth(pin)) * -25
    if abs(rot) > 0.3:
        d_ = int(math.hypot(w, h)) + 2
        Mr = cv2.getRotationMatrix2D((w / 2, h / 2), rot, 1.0)
        Mr[0, 2] += (d_ - w) / 2
        Mr[1, 2] += (d_ - h) / 2
        im = cv2.warpAffine(im, Mr, (d_, d_), flags=cv2.INTER_LINEAR, borderValue=0)
        h0 = h
        w, h = d_, d_
        x0, y0 = int(it['x'] - w / 2), int(it['y'] - h0 / 2 - h / 2)
    else:
        x0, y0 = int(it['x'] - w / 2), int(it['y'] - h)
    pc = (im[..., :3] * (im[..., 3:4] / 255), im[..., 3:4] / 255)
    H, W = f.shape[:2]
    xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + w, W), min(y0 + h, H)
    if xa >= xb or ya >= yb:
        return f
    rgb, a = pc[0][ya - y0:yb - y0, xa - x0:xb - x0], pc[1][ya - y0:yb - y0, xa - x0:xb - x0]
    if it.get('behind') and m is not None:  # 人の後ろ（天使の羽など）
        keep = (1 - m[ya:yb, xa:xb])[..., None]
        rgb, a = rgb * keep, a * keep
    # やわらかい落ち影（シールが少し浮いている感じ）
    sh = cv2.GaussianBlur(a[..., 0], (0, 0), max(6 * ks, 0.8)) * 0.35
    sx, sy = int(round(6 * ks)), int(round(10 * ks))
    ya2, xa2 = min(ya + sy, H), min(xa + sx, W)
    hh, ww = min(yb + sy, H) - ya2, min(xb + sx, W) - xa2
    if hh > 0 and ww > 0:
        f[ya2:ya2 + hh, xa2:xa2 + ww] *= (1 - sh[:hh, :ww, None])
    f[ya:yb, xa:xb] = f[ya:yb, xa:xb] * (1 - a) + rgb
    return f
