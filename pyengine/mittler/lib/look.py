"""v7 の後付けの光と空気。2026-10-16。どれも時刻とコマ番号だけで決まる（並列の書き出しで区間に分けても同じ絵）。

- bloom：明るい所のにじみ（スクリーン合成）
- halation：明るい所のふちの赤いにじみ（フィルム）
- grain：16mm 風の粒（中間と暗い所に多め、毎コマ変わる）
- vignette：周辺をほんの少し落とす
- glints：画面のいちばん明るい小さな点（ラインストーン・アクセ・スパンコール・照明）に十字のキラ
- glitter：ラメの粒（手前の六角の箔がきらっと光る＋奥のぼけた玉）。ゆっくり漂う＋拍でバースト
"""
import math

import cv2
import numpy as np


def _f(img):
    return img.astype(np.float32) if img.dtype != np.float32 else img


def screen(a, b):
    return 255 - (255 - a) * (255 - b) / 255


def bloom(img, thr=0.78, radius=18, amt=0.35, tint=(255, 220, 240)):
    f = _f(img)
    lum = f.mean(axis=2) / 255
    m = np.clip((lum - thr) / (1 - thr), 0, 1) ** 1.5
    hi = f * m[..., None]
    b = cv2.GaussianBlur(hi, (0, 0), radius) + cv2.GaussianBlur(hi, (0, 0), radius * 3) * 0.6
    b = b * np.array(tint, np.float32) / 255 * amt
    return screen(f, np.clip(b, 0, 255))


def halation(img, thr=0.85, radius=6, amt=0.25):
    f = _f(img)
    lum = f.max(axis=2) / 255
    m = np.clip((lum - thr) / (1 - thr), 0, 1)
    h = cv2.GaussianBlur(m, (0, 0), radius) - cv2.GaussianBlur(m, (0, 0), radius * 0.3)
    h = np.clip(h, 0, 1)[..., None] * np.array((255, 70, 40), np.float32) * amt
    return screen(f, h)


_GR = {}


def grain(img, fi, amt=7.0, size=1.3, seed=7):
    f = _f(img)
    H, W = f.shape[:2]
    rng = np.random.default_rng(seed * 100003 + fi)
    h, w = int(H / size) + 1, int(W / size) + 1
    n = rng.standard_normal((h, w)).astype(np.float32)
    n = cv2.resize(n, (W, H), interpolation=cv2.INTER_CUBIC)
    c = rng.standard_normal((h // 2 + 1, w // 2 + 1, 3)).astype(np.float32)
    c = cv2.resize(c, (W, H), interpolation=cv2.INTER_CUBIC) * 0.35  # 色の粒（少し）
    lum = f.mean(axis=2, keepdims=True) / 255
    wgt = 0.55 + 0.9 * lum * (1 - lum) * 4 * 0.5 + (1 - lum) * 0.3  # 中間・暗部で多め
    wgt = np.clip(wgt, 0.3, 1.2) * (1 - np.clip((lum - 0.92) / 0.08, 0, 1) * 0.7)
    return f + (n[..., None] + c) * amt * wgt


def vignette(img, amt=0.18):
    f = _f(img)
    H, W = f.shape[:2]
    key = (H, W)
    if key not in _GR:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
        _GR[key] = (np.clip((r - 0.45) / 0.55, 0, 1) ** 1.8)[..., None]
    return f * (1 - amt * _GR[key])


# ---- キラ ----
def _star(size, rays=4, long=1.0, thin=0.06):
    """十字（＋短い斜め）のキラの型。0〜1 の float、中心は size。"""
    S = int(size * 2 + 3)
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32) - S // 2
    r = np.sqrt(xx ** 2 + yy ** 2) + 1e-3
    out = np.exp(-(r / (size * 0.12)) ** 2)  # 芯
    for k in range(rays):
        a = k * math.pi / rays * 2 / 2 if rays == 4 else k * math.pi / rays
        ca, sa = math.cos(a), math.sin(a)
        along = xx * ca + yy * sa
        across = -xx * sa + yy * ca
        ln = size * (long if k % 2 == 0 else long * 0.95)
        out += np.exp(-(across / (size * thin)) ** 2) * np.clip(1 - np.abs(along) / ln, 0, 1) ** 2.2
    for k in range(4):  # 短い斜め
        a = math.pi / 4 + k * math.pi / 2
        along = xx * math.cos(a) + yy * math.sin(a)
        across = -xx * math.sin(a) + yy * math.cos(a)
        out += 0.45 * np.exp(-(across / (size * thin * 0.8)) ** 2) * np.clip(1 - np.maximum(along, 0) / (size * 0.38), 0, 1) ** 2 * (along > 0)
    return np.clip(out, 0, 1.5)


_STARS = {}


def star(size):
    s = max(int(round(size)), 3)
    if s not in _STARS:
        _STARS[s] = _star(s)
    return _STARS[s]


def find_highlights(img, n=24, thr=0.90, min_dist=40, mask=None, k=9):
    """明るい小さな点（top-hat）。[(x, y, 強さ, 色)]"""
    f = _f(img)
    g = f.max(axis=2) / 255
    th = g - cv2.morphologyEx(g, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    score = th * np.clip((g - thr * 0.85) / (1 - thr * 0.85), 0, 1)
    if mask is not None:
        score = score * mask
    dil = cv2.dilate(score, np.ones((min_dist // 2 * 2 + 1,) * 2, np.uint8))
    ys, xs = np.nonzero((score >= dil) & (score > 0.04))
    v = score[ys, xs]
    order = np.argsort(-v)[:n * 3]
    pts = []
    for i in order:
        x, y = int(xs[i]), int(ys[i])
        if all((x - px) ** 2 + (y - py) ** 2 >= min_dist ** 2 for px, py, *_ in pts):
            pts.append((x, y, float(v[i]), f[y, x].copy()))
        if len(pts) >= n:
            break
    return pts


def glints(img, fi, t, pts, size=34, amt=1.0, beat=0.0, tw_speed=5.0):
    """pts のところに十字のキラ。またたきは点の位置から決まる位相で。beat（0〜1）で大きく明るく。"""
    f = _f(img)
    H, W = f.shape[:2]
    add = np.zeros_like(f)
    for x, y, v, col in pts:
        ph = ((x // 24) * 7.31 + (y // 24) * 3.17) % (2 * math.pi)
        tw = 0.55 + 0.45 * math.sin(t * tw_speed + ph)
        s = size * (0.6 + 0.8 * min(v * 3, 1)) * (0.7 + 0.3 * tw) * (1 + 0.6 * beat)
        st = star(s)
        S = st.shape[0]
        x0, y0 = x - S // 2, y - S // 2
        xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + S, W), min(y0 + S, H)
        if xa >= xb or ya >= yb:
            continue
        c = np.array(col, np.float32)
        c = c * 0.35 + np.array((255, 255, 255), np.float32) * 0.65
        a = st[ya - y0:yb - y0, xa - x0:xb - x0, None] * (tw * (1 + beat)) * amt
        add[ya:yb, xa:xb] += a * c
    return screen(f, np.clip(add, 0, 255))


# ---- ラメ ----
def _flake(size, seed):
    rng = np.random.default_rng(seed)
    S = int(size * 2 + 3)
    img = np.zeros((S, S), np.float32)
    n = 6
    rot = rng.uniform(0, math.pi)
    pts = np.array([[S / 2 + size * math.cos(rot + k * 2 * math.pi / n) * rng.uniform(0.8, 1.0),
                     S / 2 + size * 0.75 * math.sin(rot + k * 2 * math.pi / n) * rng.uniform(0.8, 1.0)] for k in range(n)], np.int32)
    cv2.fillConvexPoly(img, pts, 1.0, lineType=cv2.LINE_AA)
    return img


GLITTER_COLORS = [(255, 120, 200), (255, 215, 120), (235, 235, 255), (190, 150, 255), (255, 255, 255), (140, 230, 255)]


class Glitter:
    """ラメの粒。時刻だけで位置が決まる（状態を持たない）。"""

    def __init__(self, W, H, n=140, seed=3, size=(3, 9), fall=40.0, drift=18.0, area=None):
        self.W, self.H = W, H
        rng = np.random.default_rng(seed)
        self.n = n
        self.x0 = rng.uniform(0, W, n)
        self.y0 = rng.uniform(0, H, n)
        self.z = rng.uniform(0, 1, n)  # 0＝奥（ぼけた玉）、1＝手前（箔）
        self.sz = rng.uniform(*size, n) * (0.5 + self.z)
        self.vy = fall * (0.4 + self.z)
        self.ph = rng.uniform(0, 2 * math.pi, n)
        self.spin = rng.uniform(4, 11, n)
        self.col = [GLITTER_COLORS[i] for i in rng.integers(0, len(GLITTER_COLORS), n)]
        self.drift = drift
        self.flakes = [_flake(4, s) for s in range(8)]

    def draw(self, img, t, amt=1.0, beat=0.0):
        f = _f(img)
        W, H = self.W, self.H
        add = np.zeros_like(f)
        for i in range(self.n):
            x = (self.x0[i] + self.drift * math.sin(t * 0.7 + self.ph[i])) % W
            y = (self.y0[i] + self.vy[i] * t) % (H + 40) - 20
            flash = max(0.0, math.sin(t * self.spin[i] + self.ph[i])) ** 6  # 箔が光をはねる瞬間
            if self.z[i] < 0.35:  # 奥：ぼけた玉
                r = self.sz[i] * 2.2
                a = 0.18 + 0.25 * flash
                cv2.circle(add, (int(x), int(y)), int(r), tuple(float(c) * a * amt for c in self.col[i]), -1, cv2.LINE_AA)
            else:
                s = self.sz[i]
                fl = self.flakes[i % 8]
                k = cv2.resize(fl, (int(s * 2 + 3), int(s * 2 + 3)))
                br = (0.35 + 1.6 * flash) * amt * (1 + beat)
                self._stamp(add, k, x, y, np.array(self.col[i], np.float32) * br)
                if flash > 0.6:
                    st = star(s * 3.2) * (flash - 0.6) * 2.5 * amt
                    self._stamp(add, st, x, y, np.array((255, 255, 255), np.float32))
        add = cv2.GaussianBlur(add, (0, 0), 0.6)
        return screen(f, np.clip(add, 0, 255))

    @staticmethod
    def _stamp(dst, k, x, y, col):
        H, W = dst.shape[:2]
        S = k.shape[0]
        x0, y0 = int(x) - S // 2, int(y) - S // 2
        xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + S, W), min(y0 + S, H)
        if xa >= xb or ya >= yb:
            return
        dst[ya:yb, xa:xb] += k[ya - y0:yb - y0, xa - x0:xb - x0, None] * col


def burst(img, t, t0, cx, cy, n=60, seed=0, dur=1.2, speed=520, amt=1.0):
    """t0 に (cx, cy) からラメがはじける（重力で落ちる）。"""
    dt = t - t0
    if dt < 0 or dt > dur:
        return _f(img)
    f = _f(img)
    rng = np.random.default_rng(seed)
    ang = rng.uniform(0, 2 * math.pi, n)
    sp = speed * rng.uniform(0.3, 1.0, n)
    add = np.zeros_like(f)
    fade = (1 - dt / dur) ** 1.5
    for i in range(n):
        x = cx + math.cos(ang[i]) * sp[i] * dt * (1 - 0.35 * dt)
        y = cy + math.sin(ang[i]) * sp[i] * dt * (1 - 0.35 * dt) + 380 * dt * dt
        s = rng.uniform(3, 8)
        col = np.array(GLITTER_COLORS[i % len(GLITTER_COLORS)], np.float32)
        fl = max(0.0, math.sin(dt * 25 + i)) ** 4
        Glitter._stamp(add, star(s * (1.5 + 2 * fl)), x, y, col * fade * amt * (0.6 + fl))
    return screen(f, np.clip(add, 0, 255))


def finish(img, fi, grain_amt=7.0, vig=0.16, hal=0.22, blo=0.3):
    """仕上げ（光のにじみ → ハレーション → 周辺 → 粒）。uint8 を返す。"""
    f = _f(img)
    if blo:
        f = bloom(f, amt=blo)
    if hal:
        f = halation(f, amt=hal)
    if vig:
        f = vignette(f, vig)
    if grain_amt:
        f = grain(f, fi, grain_amt)
    return np.clip(f, 0, 255).astype(np.uint8)


# ---- トーンマップ（フィルミック） ----
# 8bit の sRGB → リニア → 明るい所を少し伸ばして余白を作る（逆トーンマップ）→ 露出 → カーブ → sRGB。
def srgb_to_lin(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def expand(lin, k=0.75):
    """白を 1/(1-k) まで伸ばす（明るい所だけ強く伸びる）。"""
    return lin / np.maximum(1 - k * lin, 1e-3)


def _hable(x):
    A, B, C, D, E, F = 0.15, 0.50, 0.10, 0.20, 0.02, 0.30
    return ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) - E / F


def tm_hable(x, exposure=2.0, white=11.2):
    return _hable(x * exposure) / _hable(white)


def tm_aces(x, exposure=0.8):
    x = x * exposure
    return np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)


_S2R = np.array([[0.6274, 0.0691, 0.0164], [0.3293, 0.9195, 0.0880], [0.0433, 0.0113, 0.8956]], np.float32)
_R2S = np.array([[1.6605, -0.1246, -0.0182], [-0.5876, 1.1329, -0.1006], [-0.0728, -0.0083, 1.1187]], np.float32)
_AGX_IN = np.array([[0.856627153315983, 0.137318972929847, 0.11189821299995],
                    [0.0951212405381588, 0.761241990602591, 0.0767994186031903],
                    [0.0482516061458583, 0.101439036467562, 0.811302368396859]], np.float32)
_AGX_OUT = np.array([[1.1271005818144368, -0.1413297634984383, -0.14132976349843826],
                     [-0.11060664309660323, 1.157823702216272, -0.11060664309660294],
                     [-0.016493938717834573, -0.016493938717834257, 1.2519364065950405]], np.float32)


def tm_agx(x, exposure=1.0, punch=0.0):
    """AgX（Blender の新しい Filmic）。three.js の近似。punch で彩度とコントラストを足す（Punchy ルック）。"""
    c = (x * exposure) @ _S2R
    c = c @ _AGX_IN
    c = np.log2(np.maximum(c, 1e-10))
    c = np.clip((c + 12.47393) / (4.026069 + 12.47393), 0, 1)
    x2 = c * c
    x4 = x2 * x2
    c = 15.5 * x4 * x2 - 40.14 * x4 * c + 31.96 * x4 - 6.868 * x2 * c + 0.4298 * x2 + 0.1191 * c - 0.00232
    if punch:
        lum = (c * np.array([0.2126, 0.7152, 0.0722], np.float32)).sum(-1, keepdims=True)
        c = np.clip(lum + (c - lum) * (1 + 0.4 * punch), 0, None)
        c = np.power(np.clip(c, 0, None), 1 + 0.35 * punch)
    c = c @ _AGX_OUT
    c = np.power(np.maximum(c, 0), 2.2)
    return np.clip(c @ _R2S, 0, 1)


def tonemap(img, mode='agx', k=0.75, **kw):
    """img（0〜255 の sRGB、float か uint8）→ 0〜255 の float。"""
    lin = expand(srgb_to_lin(_f(img) / 255), k)
    fn = {'hable': tm_hable, 'aces': tm_aces, 'agx': tm_agx}[mode]
    return lin_to_srgb(fn(lin, **kw)) * 255
