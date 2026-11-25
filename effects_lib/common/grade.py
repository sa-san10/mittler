"""カットごとの色の手直し（UI の色の卓のスライダーで決める。カットの無い作品は全体に1つ）。sRGB の値のまま 明るさ b → コントラスト c → ビブランス v → 彩度 s、0〜1 に切る。
光とトーンマップのあと・外周ネオンと字の前（映像だけにかかる）。
偽マリアMV の彩度合わせ卓（スライダーで直す卓）と同じ式。編集画面の色の卓も同じ式で見せる（editor/calc.js の gradePixel。同じことは tools/smoke_same.py が確かめる）。
偽マリアMV もこのファイル（作者の取り込み器がここから写す）。
params：b, c, v, s（1.0 で変えない）"""
import numpy as np

STAGE = 'v7'
DOC_EN = """Per-cut color correction (set with the sliders in the Color panel; one for the whole project if it has no cuts). On sRGB values: brightness b → contrast c → vibrance v → saturation s, clipped to 0–1.
Applied after lighting/tone mapping and before the edge neon and text (affects the picture only).
params: b, c, v, s (1.0 = unchanged)"""
META = {'label': '色の手直し', 'label_en': 'Color correction', 'window': {'per_cut': True},
        'params': {k: {'type': 'number', 'min': 0.0, 'max': 2.0, 'step': 0.01} for k in ('b', 'c', 'v', 's')}}


def apply(ctx, f, clip):
    g = clip.get('params', {})
    x = np.asarray(f, np.float32) / 255.0
    b, c, v, s = (float(g.get(k, 1.0)) for k in ('b', 'c', 'v', 's'))
    if b != 1.0:
        x = x * b
    if c != 1.0:
        x = (x - 0.5) * c + 0.5
    w = np.array([0.2126, 0.7152, 0.0722], np.float32)
    if v != 1.0:
        L = (x @ w)[..., None]
        m = np.clip(x.max(axis=2, keepdims=True) - x.min(axis=2, keepdims=True), 0.0, 1.0)
        x = L + (x - L) * (1.0 + (v - 1.0) * (1.0 - m))
    if s != 1.0:
        L = (x @ w)[..., None]
        x = L + (x - L) * s
    return np.clip(x, 0.0, 1.0) * 255.0
