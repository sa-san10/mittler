"""星のビート・バースト：決めた区間（windows）の拍ごとに、顔のまわり（主に左上〜両脇）へ星が 6 個はじけて飛び、回りながら 0.32 秒で消える。
星は黄・シアン・緑・白（palette）の星形に暗いふち・発光・落ち影。位置と大きさは拍ごとに決まった種の乱数（拍の番号から）。
params：windows（[[t0, t1], …]：出す区間）, palette（[[r, g, b], …]）, n（6）, life（0.32 秒）, dist（[110, 290] px）, size（[26, 46) px）, seed（77000）,
  center（顔が無いときの中心 [540, 480] px）, face_y（顔の箱の縦の位置 0.4）, margin（端から 50 px）, band（[上, 下] px）
顔の表は settings.beatfx.faces（無ければ center）。Attention の字の層があれば、そこに描く（字といっしょに合成・粒・ショックウェーブ）。無ければ絵に直接重ねる。
打点の時計は settings.beatfx（_lib/beatfx.py）。マスター書き出し（ctx.scale）：星の大きさ・飛ぶ距離・位置・ふちを s 倍（乱数は同じ引き方）。
元：作者のダンス動画（Attention）の OVERDRIVE 版（2026-10-14）の apply_star_sparks・get_star_sprite（星ピンとカエルの緑）。"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

_LIB = str(Path(__file__).resolve().parent / '_lib')
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
import beatfx  # noqa: E402

STAGE = 'v7'
META = {'label': '星のビート・バースト', 'label_en': 'Star beat burst','window': {'clip': True}, 'scale_aware': True,
        'params': {'windows': {'type': 'json'}, 'palette': {'type': 'json'}, 'n': {'type': 'int', 'min': 0, 'max': 30},
                   'life': {'type': 'number', 'min': 0.05, 'max': 2, 'step': 0.01}, 'dist': {'type': 'json'}, 'size': {'type': 'json'},
                   'seed': {'type': 'int', 'min': 0, 'max': 999999}, 'center': {'type': 'json'}, 'margin': {'type': 'number', 'min': 0, 'max': 400, 'step': 1},
                   'band': {'type': 'json'}}}

PALETTE = [[255, 215, 0], [0, 235, 255], [70, 245, 110], [255, 255, 255]]


def star_sprite(cache, size, col, s, B):
    """星ピンモチーフの ★（元の get_star_sprite。s 倍の大きさで描く）"""
    key = ('bfx_star', size, tuple(col), s)
    if key not in cache:
        sz = size * s
        im = Image.new("RGBA", (sz * 2, sz * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        cx, cy = sz, sz
        pts = []
        for i in range(10):
            ang = math.pi * i / 5.0 - math.pi / 2.0
            r = sz * 0.72 if i % 2 == 0 else sz * 0.32
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        d.polygon(pts, fill=(*col, 255), outline=(10, 20, 40, 255), width=max(3 * s, sz // 12))
        im = B.outline_img(im, (8, 18, 38), stroke=4 * s, glow=col, s=s)
        cache[key] = B.Sprite(im, sz, sz)
    return cache[key]


def apply(ctx, f, clip):
    B = beatfx.lib()
    p = clip.get('params', {})
    C = B.clock(ctx)
    t, k = B.song_t(ctx), B.frame(ctx)
    if not any(a <= t <= b for a, b in p.get('windows', [])):
        return f
    s = B.scale(ctx)
    H, W = f.shape[:2]
    W0, H0 = W // s, H // s
    fc = C.face(k)
    if fc is not None:
        fx, fy, fw, fh = fc
        cx, cy = fx + fw * 0.5, fy + fh * p.get('face_y', 0.4)
    else:
        cx, cy = p.get('center', [540.0, 480.0])
    i = C.index(t)
    if i < 0:
        return f
    life = p.get('life', 0.32)
    tau = t - C.beats[i]
    if tau < 0 or tau > life:
        return f
    u = B.ease_out(tau / life)
    alpha = (1.0 - u) * 0.92
    rng = np.random.default_rng(p.get('seed', 77000) + i * 31)
    palette = [tuple(c) for c in p.get('palette', PALETTE)]
    d0, d1 = p.get('dist', [110, 290])
    z0, z1 = p.get('size', [26, 46])
    mg = p.get('margin', 50)
    bt, bb = p.get('band', [0, 0])
    L = B.text_layer(ctx, create=True)
    canvas = L.front if L is not None else np.zeros((H, W, 4), np.float32)
    drew = False
    for s_idx in range(p.get('n', 6)):
        ang = rng.uniform(-math.pi * 0.85, math.pi * 0.15) if s_idx < 4 else rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(d0, d1) * (0.35 + 0.65 * u)
        sx = cx + math.cos(ang) * dist * 1.15
        sy = cy + math.sin(ang) * dist * 0.85
        if not (bt + mg < sy < H0 - bb - mg and mg < sx < W0 - mg):
            continue
        col = palette[(i + s_idx) % len(palette)]
        sz = int(rng.integers(z0, z1))
        spr = star_sprite(ctx.cache, sz, col, s, B)
        B.blit(canvas, spr, sx * s, sy * s, scale=(1.15 - 0.45 * u), rot=tau * 260 * (1 if s_idx % 2 == 0 else -1), alpha=alpha)
        drew = True
    if L is not None or not drew:
        return f
    out = B.pic(ctx, f)   # 字の層が無い作品：★ を絵に直接重ねる（premultiplied）
    out = out * (1 - canvas[..., 3:4]) + canvas[..., :3]
    return B.unpic(ctx, out)
