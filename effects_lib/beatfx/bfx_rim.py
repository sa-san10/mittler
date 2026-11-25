"""ネオン・リムライト（rim）：人のマスク（ctx.m）の輪郭が打点で光る。太いぼかし（オーラ）＋細いぼかし（芯）を、画面の上（top）から下（mid）への
2色のグラデーションで足す。拍ごとに色の組を入れ替える（偶数の拍＝colors[0]、奇数＝colors[1]）。白飛びしにくい足し方（out + rim × (1 − out × 0.6)）。
params：colors（[[上の色, 下の色], [上の色, 下の色]]、0〜255）, base（ふつうの拍の強さ 0.58）, hit（強いヒット 1.25）,
  windows（[{t0, t1, top, mid}]：その区間だけ色を替える）, aura（[太いぼかしの半径, 濃さ, 芯の半径, 濃さ]＝[15, 0.75, 3, 0.65]）,
  dilate・erode（輪郭の幅 11・5 px）, band（[上, 下] px：帯のところは光らせない）
強さ＝（強いヒットなら hit、ほかは base）× 打点（env、1.15 まで）。打点が無いところ・人のマスクが無いところは何もしない。
人のマスクのトラックより上に置く（needs matte）。打点の時計は settings.beatfx（_lib/beatfx.py）。
マスター書き出し（ctx.scale）：輪郭の幅・ぼかしの半径・帯を s 倍。ドラフト（ctx.draft）：芯のぼかしを省く。
元：作者のダンス動画（Attention）の OVERDRIVE 版（2026-10-14）のリムライトの関数（ブルー×シアン×グリーン×スターゴールド）、
演出語彙 rim（references/演出語彙_ビート演出）。"""
import sys
from pathlib import Path

import cv2
import numpy as np

_LIB = str(Path(__file__).resolve().parent / '_lib')
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
import beatfx  # noqa: E402

STAGE = 'v7'
META = {'label': 'ネオン・リムライト', 'label_en': 'Neon rim light','window': {'clip': True}, 'needs': ['matte'], 'scale_aware': True, 'draft': True,
        'params': {'colors': {'type': 'json'}, 'base': {'type': 'number', 'min': 0, 'max': 3, 'step': 0.01},
                   'hit': {'type': 'number', 'min': 0, 'max': 3, 'step': 0.01}, 'windows': {'type': 'json'}, 'aura': {'type': 'json'},
                   'dilate': {'type': 'int', 'min': 1, 'max': 60}, 'erode': {'type': 'int', 'min': 1, 'max': 60}, 'band': {'type': 'json'}}}

DEF_COLORS = [[[255, 215, 0], [70, 245, 110]], [[0, 235, 255], [20, 150, 255]]]


def rim(out, m, env, is_hit, beat_idx, t, p, s, draft=False):
    """元のリムライトの関数（値は params）"""
    H, W = m.shape
    di, er = p.get('dilate', 11), p.get('erode', 5)
    dil = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, ((di - 1) * s + 1, (di - 1) * s + 1)))
    ero = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, ((er - 1) * s + 1, (er - 1) * s + 1)))
    edge = np.clip(dil - ero, 0.0, 1.0)
    r1, a1, r2, a2 = p.get('aura', [15.0, 0.75, 3.0, 0.65])
    if draft:
        aura = cv2.GaussianBlur(edge, (0, 0), r1 * s) * (a1 + a2)
    else:
        aura = cv2.GaussianBlur(edge, (0, 0), r1 * s) * a1 + cv2.GaussianBlur(edge, (0, 0), r2 * s) * a2
    band = p.get('band', [0, 0])
    if band[0]:
        aura[:band[0] * s] = 0
    if band[1]:
        aura[H - band[1] * s:] = 0
    cols = p.get('colors', DEF_COLORS)
    top, mid = cols[beat_idx % len(cols)]
    for w in p.get('windows', []):
        if w['t0'] <= t < w['t1']:
            top, mid = w['top'], w['mid']
            break
    c_top = np.array(top, np.float32) / 255.0
    c_mid = np.array(mid, np.float32) / 255.0
    ys = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None, None]
    col_map = c_top * (1.0 - ys) + c_mid * ys
    strength = (p.get('hit', 1.25) if is_hit else p.get('base', 0.58)) * min(1.15, env)
    rim_ = aura[..., None] * col_map * strength
    return out + rim_ * (1.0 - out * 0.6)


def apply(ctx, f, clip):
    B = beatfx.lib()
    p = clip.get('params', {})
    m = ctx.m
    if m is None or m.max() < 0.05:
        return f
    C = B.clock(ctx)
    t, k = B.song_t(ctx), B.frame(ctx)
    env, is_hit, i = C.env(t, k)
    if env <= 0.02:
        return f
    return B.unpic(ctx, rim(B.pic(ctx, f), m, env, is_hit, i, t, p, B.scale(ctx), getattr(ctx, 'draft', False)))
