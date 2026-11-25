"""明るさのガンマと彩度（偽マリアのエフェクト集）：下の絵の明るさ（ガンマ）と彩度を変える。前後のカットと色合いをそろえるのに。
params：gamma（明るさのガンマ。1 でそのまま、小さいほど明るい）、sat（彩度の倍率。1 でそのまま）。
元は偽マリアMV（effects_lib/maria/match.py。口パクのカットの明るさ・彩度を前後の動画に合わせた）。式は同じ。"""
import numpy as np

STAGE = 'v7'
DOC_EN = """Gamma and saturation (False Maria effects): changes the brightness (gamma) and saturation of the picture below. Handy for matching a shot to its neighbors.
params: gamma (1 = unchanged, smaller = brighter), sat (saturation multiplier, 1 = unchanged).
From the False Maria MV (matched the lip-sync shots to the shots around them)."""
META = {'label': 'ガンマと彩度（偽マリア）', 'label_en': 'Gamma and saturation (False Maria)', 'scale_aware': True,
        'params': {'gamma': {'type': 'number', 'min': 0.3, 'max': 2.0, 'step': 0.01}, 'sat': {'type': 'number', 'min': 0.0, 'max': 2.5, 'step': 0.01}},
        'defaults': {'gamma': 0.9, 'sat': 1.15}, 'dur': 3}


def apply(ctx, f, clip):
    mt = clip.get('params', {})
    f = 255.0 * np.power(f / 255.0, mt.get('gamma', 1.0))
    if mt.get('sat', 1.0) != 1.0:
        y = f @ np.array([0.299, 0.587, 0.114], np.float32)
        f = y[..., None] + (f - y[..., None]) * mt['sat']
    return np.clip(f, 0, 255)
