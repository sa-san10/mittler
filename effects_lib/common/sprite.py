"""重ね絵（フキダシ・描き文字・ロゴなど、透明の PNG を1枚）。指定の位置に出し方つきで出す。
params：img（root からの相対パス）, x, y（絵の真ん中の画面の位置 px）, t0, t1（出ている時間）, anim（出方）, scale（大きさの倍率）
anim：pop（小さく出て弾む）／soft（ふわっと）／slam（大きく叩きつける）／float（浮きながら上へ）／zip（横から滑り込み、終わりに左へ抜ける）／
      wobble（プルプル震える）／none
出方の数字は 作者の紙芝居の作品の重ね絵と同じ（ただしカメラの寄りには付いて動かない）。"""
import math

import numpy as np
from PIL import Image

STAGE = 'post'
DOC_EN = """Overlay image (one transparent PNG: speech bubble, hand-drawn text, logo, etc.), shown at a position with an entrance animation.
params: img (path relative to root), x, y (screen position of the image center, px), t0, t1 (visible time), anim (animation), scale (size factor)
anim: pop (appears small and bounces) / soft (fades in gently) / slam (slams in large) / float (rises while floating) / zip (slides in from the side, exits left at the end) /
      wobble (jiggles) / none"""
META = {'label': '重ね絵', 'label_en': 'Overlay', 'window': {'start': 't0', 'end': 't1'}, 'time_params': ['t0', 't1'],
        'params': {'img': {'type': 'image'}, 'x': {'type': 'number', 'step': 1}, 'y': {'type': 'number', 'step': 1},
                   'scale': {'type': 'number', 'min': 0.05, 'max': 5, 'step': 0.01},
                   'anim': {'type': 'choice', 'choices': ['pop', 'soft', 'slam', 'float', 'zip', 'wobble', 'none']}}}


def ease(p):
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def back_out(p):
    p = min(1.0, max(0.0, p))
    c1 = 1.9
    return 1 + (c1 + 1) * (p - 1) ** 3 + c1 * (p - 1) ** 2


def apply(ctx, f, clip):
    o = clip.get('params', {})
    t, anim = ctx.t, o.get('anim', 'pop')
    if not (o['t0'] <= t < o['t1'] + (.25 if anim == 'zip' else 0)):
        return f
    cache = ctx.cache.setdefault('sprite', {})
    if o['img'] not in cache:
        cache[o['img']] = Image.open(ctx.root / o['img']).convert('RGBA')
    img = cache[o['img']]
    p = t - o['t0']
    s, alpha, rot, ox, oy = 1.0, 1.0, 0.0, 0.0, 0.0
    if anim in ('pop', 'soft'):
        d = .28 if anim == 'pop' else .45
        s = .55 + .45 * back_out(p / d) if anim == 'pop' else .85 + .15 * ease(p / d)
        alpha = min(1, p / (d * .6))
    elif anim == 'slam':
        s = 1.0 + 0.5 * (1 - ease(p / .18))
        alpha = min(1, p / .08)
    elif anim == 'float':
        s = .7 + .3 * back_out(p / .3)
        alpha = min(1, p / .2)
        oy = -30 * p + 6 * math.sin(p * 9)
    elif anim == 'zip':
        ox = -260 * (1 - ease(p / .18)) + (-400 * ease((t - o['t1']) / .25) if t > o['t1'] else 0)
        alpha = min(1, p / .08) * (1 - ease((t - o['t1']) / .25) if t > o['t1'] else 1)
    elif anim == 'wobble':
        s = .8 + .2 * back_out(p / .25)
        alpha = min(1, p / .12)
        ox, oy = math.sin(t * 140) * 5, math.cos(t * 117) * 4
        rot = math.sin(t * 60) * 2.5
    k = s * float(o.get('scale', 1.0))
    if abs(k - 1) > .01 or rot:
        img = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.BICUBIC)
        if rot:
            img = img.rotate(rot, expand=True, resample=Image.BICUBIC)
    if alpha < 1:
        img = img.copy()
        img.putalpha(img.getchannel('A').point(lambda v, a=alpha: int(v * a)))
    if f.dtype != np.uint8:  # 'post' の段で float の絵を返すエフェクトのあとに置かれたとき（前は Image.fromarray が落ちた）。エンジンの切り方と同じに uint8 へ
        f = np.clip(f, 0, 255).astype(np.uint8)
    frame = Image.fromarray(f).convert('RGBA')
    px, py = o['x'] + ox, o['y'] + oy
    frame.alpha_composite(img, (int(px - img.width / 2), int(py - img.height / 2)))
    return np.asarray(frame.convert('RGB'))
