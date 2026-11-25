"""アナモルフィック・ブルーム（anamorph）：明るいところ（輝度 thr 以上）だけを抜き、1/4 に縮めて横長のぼかし（映画風の横の光）＋丸いぼかしを混ぜて足す。
いつも薄く（base）、打点で強く（env × gain、env は 1.25 まで）。白飛びしにくい足し方（out + bloom × 強さ × (1 − out × 0.5)）。
params：thr（0.64）, width（0.36：thr から thr＋width で 0→1 に抜く）, sigma_h（横長のぼかしの [横, 縦] 1/4 の大きさでの px [20, 3.2]）, sigma_r（丸いぼかし 6.5）,
  mix（[横長, 丸] の割合 [0.7, 0.3]）,
  base（0.18）, gain（0.30）, band（[上, 下] px：帯のところは光らせない）
打点の時計は settings.beatfx（_lib/beatfx.py）。マスター書き出し（ctx.scale）：ぼかしの半径・帯を s 倍（縮めた絵も s 倍の大きさ）。
ドラフト（ctx.draft）：丸いぼかしを省く（横長だけ）。
元：作者のダンス動画（Attention）の OVERDRIVE 版（2026-10-14）の apply_anamorphic_bloom、演出語彙 anamorph。"""
import sys
from pathlib import Path

import cv2
import numpy as np

_LIB = str(Path(__file__).resolve().parent / '_lib')
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
import beatfx  # noqa: E402

STAGE = 'v7'
META = {'label': 'アナモルフィック・ブルーム', 'label_en': 'Anamorphic bloom','window': {'clip': True}, 'scale_aware': True, 'draft': True,
        'params': {'thr': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01}, 'sigma_h': {'type': 'json'},
                   'sigma_r': {'type': 'number', 'min': 0, 'max': 50, 'step': 0.1}, 'width': {'type': 'number', 'min': 0.01, 'max': 1, 'step': 0.01}, 'mix': {'type': 'json'},
                   'base': {'type': 'number', 'min': 0, 'max': 2, 'step': 0.01}, 'gain': {'type': 'number', 'min': 0, 'max': 2, 'step': 0.01},
                   'band': {'type': 'json'}}}

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def bloom(out, env, p, s, draft=False):
    H, W = out.shape[:2]
    thr, width = p.get('thr', 0.64), p.get('width', 0.36)
    luma = out @ LUMA
    hi = np.clip((luma - thr) / width, 0.0, 1.0)[..., None] * out
    sh, sw = H // 4, W // 4
    small = cv2.resize(hi, (sw, sh), interpolation=cv2.INTER_AREA)
    sx, sy = p.get('sigma_h', [20.0, 3.2])
    bloom_h = cv2.GaussianBlur(small, (0, 0), sigmaX=sx * s, sigmaY=sy * s)
    mh, mr = p.get('mix', [0.7, 0.3])
    if draft:
        b = bloom_h * (mh + mr)
    else:
        sr = p.get('sigma_r', 6.5)
        bloom_s = cv2.GaussianBlur(small, (0, 0), sigmaX=sr * s, sigmaY=sr * s)
        b = bloom_h * mh + bloom_s * mr
    bl = cv2.resize(b, (W, H), interpolation=cv2.INTER_LINEAR)
    band = p.get('band', [0, 0])
    if band[0]:
        bl[:band[0] * s] = 0
    if band[1]:
        bl[H - band[1] * s:] = 0
    amt = p.get('base', 0.18) + p.get('gain', 0.30) * min(1.25, env)
    return out + bl * amt * (1.0 - out * 0.5)


def apply(ctx, f, clip):
    B = beatfx.lib()
    C = B.clock(ctx)
    t, k = B.song_t(ctx), B.frame(ctx)
    env = C.env(t, k)[0]
    return B.unpic(ctx, bloom(B.pic(ctx, f), env, clip.get('params', {}), B.scale(ctx), getattr(ctx, 'draft', False)))
