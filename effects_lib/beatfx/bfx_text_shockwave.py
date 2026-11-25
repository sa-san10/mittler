"""文字のショックウェーブ（shockwave）：打点で、前の字の輪郭（アルファを広げた − 縮めた）を少し大きく（scale、打点が強いほど小さめ）して字の後ろに薄く敷く。
色は 0.25 秒ごとに黄色とシアンが入れ替わる。打点（env）が env_min より弱い・字が無いときは何もしない。
params：grow（0.14：1＋grow 倍に広げる）, strength（0.42：濃さ＝env × これ、max まで）, max（0.60）, env_min（0.22）, colors（[[1.0, 0.85, 0.1], [0.0, 0.92, 1.0]]、0〜1）,
  ring（[広げる 5, 縮める 3] px）, band（[上, 下] px）
字の層が要る：Attention の前の字の層（ctx.attn_layers.front）に効く（字の合成 attn_compose より下、字のエフェクト・星のビート・バーストより上に置く）。層が無ければ何もしない。
打点の時計は settings.beatfx（_lib/beatfx.py）。マスター書き出し（ctx.scale）：輪郭の幅・帯を s 倍（大きくする倍率はそのまま）。
元：作者のダンス動画（Attention）の OVERDRIVE 版（2026-10-14）の apply_text_shockwave、演出語彙 shockwave。"""
import sys
from pathlib import Path

import cv2
import numpy as np

_LIB = str(Path(__file__).resolve().parent / '_lib')
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
import beatfx  # noqa: E402

STAGE = 'v7'
META = {'label': '文字のショックウェーブ', 'label_en': 'Text shockwave','window': {'clip': True}, 'scale_aware': True,
        'params': {'grow': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01}, 'strength': {'type': 'number', 'min': 0, 'max': 2, 'step': 0.01},
                   'max': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01}, 'env_min': {'type': 'number', 'min': 0, 'max': 2, 'step': 0.01},
                   'colors': {'type': 'json'}, 'ring': {'type': 'json'}, 'band': {'type': 'json'}}}


def shockwave(F, env, t, p, s, B):
    a = F[..., 3]
    if a.max() < 0.05 or env < p.get('env_min', 0.22):
        return F
    H, W = a.shape
    r1, r2 = p.get('ring', [5, 3])
    dil = cv2.dilate(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, ((r1 - 1) * s + 1, (r1 - 1) * s + 1)))
    ero = cv2.erode(a, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, ((r2 - 1) * s + 1, (r2 - 1) * s + 1)))
    ring = np.clip(dil - ero, 0.0, 1.0)
    sc = 1.0 + p.get('grow', 0.14) * (1.0 - min(1.0, env) * 0.4)
    M = np.float32([[sc, 0, (1 - sc) * W / 2], [0, sc, (1 - sc) * H / 2]])
    ring_w = cv2.warpAffine(ring, M, (W, H), flags=cv2.INTER_LINEAR)
    band = p.get('band', [0, 0])
    if band[0]:
        ring_w[:band[0] * s] = 0
    if band[1]:
        ring_w[H - band[1] * s:] = 0
    al = ring_w * min(p.get('max', 0.60), env * p.get('strength', 0.42))
    wave = np.zeros_like(F)
    wave[..., 3] = al
    c0, c1 = p.get('colors', [[1.0, 0.85, 0.1], [0.0, 0.92, 1.0]])
    col = np.array(c0, np.float32) if int(t * 4) % 2 == 0 else np.array(c1, np.float32)
    wave[..., :3] = al[..., None] * col
    B.over(wave, F)
    return wave


def apply(ctx, f, clip):
    B = beatfx.lib()
    L = B.text_layer(ctx)
    if L is None:
        return f
    C = B.clock(ctx)
    t, k = B.song_t(ctx), B.frame(ctx)
    env = C.env(t, k)[0]
    L.front = shockwave(L.front, env, t, clip.get('params', {}), B.scale(ctx), B)
    return f
