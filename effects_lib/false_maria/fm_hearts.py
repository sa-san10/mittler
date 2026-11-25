"""ハート（偽マリアのエフェクト集）：光るハートが下から上へ大量に飛ぶ（加算の光）。粒 i は t+i/rate に生まれ、式どおりに上がる（前のコマを覚えない。乱数は粒の番号で決まった種）。
同じ t・dur のクリップを続けて置くと、粒はカットをまたいでつながる。ハートの形はコードで描く（画像は使わない）。
湧く元（source）：bottom＝画面の下の幅いっぱい（元のとおり）、point＝x・y の位置（画面の割合）から spread の幅で湧いて、少し広がりながら上がる、
full＝画面全体のあちこちに現れて上がる。人のマスク（ctx.m。前の段に人の切り抜きがある作品）があれば人の後ろに、無ければ画面全体に重ねる。
params：t（湧き始め＝クリップの頭）, dur（湧く長さ＝クリップの長さ）, rate（1秒あたり）, speed, size, colors, gain（光の量）, source, x, y, spread。
元は偽マリアMV（effects_lib/maria/hearts.py。人のマスクが無いと何もしなかった）。部品にするときに、マスク無しで画面全体に重ねる形と、湧く元のパラメータを足した。
source が bottom・マスクありのときの絵は元と同じ。
マスター書き出し（ctx.scale）：大きさ・速さ（px/秒）・横の揺れ（40 px）・横の広がり（120 px/秒）・画面の下の余白（200 px）に ctx.scale を掛ける。"""
import math

import cv2
import numpy as np

STAGE = 'v7'
DOC_EN = """Hearts (False Maria effects): lots of glowing hearts fly upward (added as light). Particle i is born at t+i/rate and rises by formula
(no memory of earlier frames; the randomness is seeded by the particle number). Clips with the same t and dur placed one after another continue across the cut.
The heart shape is drawn in code (no image files).
Source: bottom = across the bottom of the frame (as in the original), point = from x, y (fractions of the frame) over a spread width, rising and spreading a little,
full = appear all over the frame and rise. With a person mask (ctx.m, from an earlier person cut-out) the hearts go behind the person; without one they cover the whole frame.
params: t (start = clip start), dur (how long they keep coming = clip length), rate (per second), speed, size, colors, gain (amount of light), source, x, y, spread.
From the False Maria MV (it needed a person mask there)."""
META = {'label': 'ハート（偽マリア）', 'label_en': 'Hearts (False Maria)', 'window': {'start': 't', 'dur': 'dur'}, 'time_params': ['t'], 'scale_aware': True,
        'params': {'rate': {'type': 'number', 'min': 1, 'max': 300, 'step': 1}, 'speed': {'type': 'number', 'min': 50, 'max': 2000, 'step': 10},
                   'size': {'type': 'number', 'min': 4, 'max': 200, 'step': 1}, 'gain': {'type': 'number', 'min': 0, 'max': 2, 'step': 0.05},
                   'source': {'type': 'choice', 'choices': ['bottom', 'point', 'full']},
                   'x': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01}, 'y': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01},
                   'spread': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01}, 'colors': {'type': 'json'}},
        'defaults': {'rate': 40, 'speed': 520, 'size': 34, 'gain': 0.5, 'source': 'bottom', 'x': 0.5, 'y': 0.8, 'spread': 0.2,
                     'colors': [[255, 30, 150], [230, 0, 200], [170, 60, 255], [255, 60, 110]]}, 'dur': 3}

COLORS = ((255, 30, 150), (230, 0, 200), (170, 60, 255), (255, 60, 110))  # 濃いめ（白っぽいと明るいピンクの上で白い粒に見えた）


def apply(ctx, f, clip):
    ev = dict(clip.get('params', {}))
    ev.setdefault('t', clip.get('start', 0.0))
    ev.setdefault('dur', clip.get('dur', 2.0))
    t, t0, dur = ctx.t, ev['t'], ev['dur']
    if not (t0 <= t < t0 + dur):
        return f
    return hearts(ctx, f, ctx.m, t, ev)


def _heart_sprite(ctx, size):
    """光るハートの形（size px）：芯（くっきり）と光（ぼかし）の2枚、0〜1"""
    cache = ctx.cache.setdefault('fm_hearts', {})
    if size not in cache:
        n = size * 3
        ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
        x = (xs - n / 2) / (size * 0.55)
        y = -(ys - n / 2) / (size * 0.55) + 0.25
        core = ((x * x + y * y - 1) ** 3 - x * x * y ** 3 <= 0).astype(np.float32)
        core = cv2.GaussianBlur(core, (0, 0), max(size * 0.03, 0.6))
        glow = cv2.GaussianBlur(core, (0, 0), size * 0.35) * 1.6
        cache[size] = (core, np.clip(glow, 0, 1))
    return cache[size]


def hearts(ctx, f, m, t, ev):
    W, H = ctx.W, ctx.H
    t0, dur, rate = ev['t'], ev.get('dur', 2.0), max(float(ev.get('rate', 40)), 1e-3)
    cols = ev.get('colors') or COLORS
    sp0, sz0 = ev.get('speed', 520.0), ev.get('size', 34)
    src = ev.get('source') or 'bottom'
    cx, cy, spread = float(ev.get('x', 0.5)), float(ev.get('y', 0.8)), float(ev.get('spread', 0.2))
    s = getattr(ctx, 'scale', 1)  # マスター書き出しの倍率（いつもは 1）
    if s != 1:
        sp0, sz0 = sp0 * s, sz0 * s
    add = np.zeros((H, W, 3), np.float32)  # 光（加算）
    life = (H + 200 * s) / (sp0 * 0.6)
    i0 = max(int((t - life - t0) * rate), 0)
    i1 = int((min(t, t0 + dur) - t0) * rate)
    for i in range(i0, i1 + 1):
        ts = t0 + i / rate
        a_ = t - ts
        if a_ < 0:
            continue
        r = np.random.default_rng(i * 7919 + 17)
        u = r.random(6)
        sz = int(sz0 * (0.5 + 1.1 * u[0]))
        sp = sp0 * (0.6 + 0.8 * u[1])
        wob = 40 * s * math.sin(a_ * (1.5 + 2 * u[3]) + u[4] * 6.28)
        if src == 'point':  # x・y の位置から spread の幅で湧き、少し横に広がりながら上がる
            x = W * (cx + (u[2] - 0.5) * spread) + wob + (u[5] - 0.5) * 2 * 120 * s * a_
            y = H * cy - sp * a_
        elif src == 'full':  # 画面のあちこちに現れて上がる
            x = u[2] * W + wob
            y = H * r.random() + sz * 0.5 - sp * a_
        else:  # bottom：画面の下の幅いっぱい（元のとおり）
            x = u[2] * W + wob
            y = H + sz * 1.5 - sp * a_
        if y < -sz * 2:
            continue
        core, glow = _heart_sprite(ctx, sz)
        col = np.array(cols[i % len(cols)], np.float32)
        fade = min(1.0, a_ / 0.15) * min(1.0, max(y, 0) / (H * 0.25) + 0.15)
        n = core.shape[0]
        xa, ya = int(x - n / 2), int(y - n / 2)
        xb, yb = xa + n, ya + n
        cx0, cy0 = max(xa, 0), max(ya, 0)
        cx1, cy1 = min(xb, W), min(yb, H)
        if cx0 >= cx1 or cy0 >= cy1:
            continue
        c = core[cy0 - ya:cy1 - ya, cx0 - xa:cx1 - xa]
        g = glow[cy0 - ya:cy1 - ya, cx0 - xa:cx1 - xa]
        # 芯も光も、色の光として足す。芯は色そのまま、光はまわりに広がる
        add[cy0:cy1, cx0:cx1] += (c[..., None] * col * 1.0 + g[..., None] * col * 0.7) * fade
    lit = np.clip(f + np.clip(add, 0, 255) * ev.get('gain', 0.5), 0, 255)  # 加算（覆い焼き・リニア）
    if m is None:
        return lit
    return lit * (1 - m[..., None]) + f * m[..., None]  # 人の後ろ
