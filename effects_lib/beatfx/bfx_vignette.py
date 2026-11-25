"""シネマティック・ビネット（vignette）：四隅を楕円に暗くして、真ん中の人物を立たせる。いつも同じ（時刻で変わらない）。
暗さ＝1 − amount × r2^power（r2 は画面の真ん中からの楕円の距離²：横 sx・縦 sy で縮めたもの）、floor より暗くしない。
params：amount（0.24）, power（1.35）, sx（0.92）, sy（0.82）, floor（0.45）
画面の大きさに対する割合だけで描くので、そのまま 4K（scale_aware）。
元：作者のダンス動画（Attention）の OVERDRIVE 版（2026-10-14）の get_vignette、演出語彙 vignette。"""
import sys
from pathlib import Path

import numpy as np

_LIB = str(Path(__file__).resolve().parent / '_lib')
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
import beatfx  # noqa: E402

STAGE = 'v7'
META = {'label': 'ビネット', 'label_en': 'Vignette','window': {'clip': True}, 'scale_aware': True,
        'params': {'amount': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01}, 'power': {'type': 'number', 'min': 0.1, 'max': 5, 'step': 0.05},
                   'sx': {'type': 'number', 'min': 0, 'max': 3, 'step': 0.01}, 'sy': {'type': 'number', 'min': 0, 'max': 3, 'step': 0.01},
                   'floor': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01}}}


def vignette(H, W, p):
    ys = np.linspace(-1.0, 1.0, H, dtype=np.float32)[:, None]
    xs = np.linspace(-1.0, 1.0, W, dtype=np.float32)[None, :]
    r2 = (xs * p.get('sx', 0.92)) ** 2 + (ys * p.get('sy', 0.82)) ** 2
    return np.clip(1.0 - p.get('amount', 0.24) * (r2 ** p.get('power', 1.35)), p.get('floor', 0.45), 1.0)[..., None]


def apply(ctx, f, clip):
    B = beatfx.lib()
    p = clip.get('params', {})
    H, W = f.shape[:2]
    key = ('bfx_vignette', H, W, repr(sorted(p.items())))
    if key not in ctx.cache:
        ctx.cache[key] = vignette(H, W, p)
    return B.unpic(ctx, B.pic(ctx, f) * ctx.cache[key])
