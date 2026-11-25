"""ラジアル・ズームブラー（radial）：強いヒットの瞬間（と字のフラッシュ）に、画面の真ん中から外へ放射の残像。真ん中は薄く、周りほど混ぜる（距離²のマスク）。
強さ＝max(強いヒットの打点 − hit_floor（1.02）, 字のフラッシュ × flash_gain（1.9））。0.02 以下なら何もしない。
params：zooms（[1.02, 1.042, 1.07]：真ん中まわりの拡大を順に重ねる）, amount（0.46）, mix（1枚あたり 0.24）, edge（マスクの強さ 0.88）, hit_floor, flash_gain
字のフラッシュは Attention の字の層（ctx.attn_layers.flash）。その字のエフェクトはこれより下のトラックに置く（先に描かれて強さが決まる）。
打点の時計は settings.beatfx（_lib/beatfx.py）。px の値は無い（倍率だけ）ので、そのまま 4K（scale_aware）。ドラフト（ctx.draft）：残像を1枚だけ（いちばん大きい倍率）。
元：作者のダンス動画（Attention）の OVERDRIVE 版（2026-10-14）の apply_radial_shock、演出語彙 radial。"""
import sys
from pathlib import Path

import cv2
import numpy as np

_LIB = str(Path(__file__).resolve().parent / '_lib')
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
import beatfx  # noqa: E402

STAGE = 'v7'
META = {'label': 'ラジアル・ズームブラー', 'label_en': 'Radial zoom blur','window': {'clip': True}, 'scale_aware': True, 'draft': True,
        'params': {'zooms': {'type': 'json'}, 'amount': {'type': 'number', 'min': 0, 'max': 2, 'step': 0.01},
                   'mix': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01}, 'edge': {'type': 'number', 'min': 0, 'max': 3, 'step': 0.01},
                   'hit_floor': {'type': 'number', 'min': 0, 'max': 3, 'step': 0.01}, 'flash_gain': {'type': 'number', 'min': 0, 'max': 5, 'step': 0.1}}}


def radial(out, env, is_hit, flash_val, p, draft=False):
    trig = max(env - p.get('hit_floor', 1.02) if is_hit else 0.0, flash_val * p.get('flash_gain', 1.9))
    if trig <= 0.02:
        return None
    H, W = out.shape[:2]
    amt = min(1.0, trig) * p.get('amount', 0.46)
    mix = p.get('mix', 0.24)
    acc = out.copy()
    ys = np.linspace(-1.0, 1.0, H, dtype=np.float32)[:, None]
    xs = np.linspace(-1.0, 1.0, W, dtype=np.float32)[None, :]
    edge_mask = np.clip((xs ** 2 + ys ** 2) * p.get('edge', 0.88), 0.0, 1.0)[..., None]
    zs = p.get('zooms', [1.02, 1.042, 1.07])
    for z in (zs[-1:] if draft else zs):
        M = np.float32([[z, 0, (1 - z) * W / 2], [0, z, (1 - z) * H / 2]])
        warped = cv2.warpAffine(out, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        acc = acc * (1.0 - mix * amt * edge_mask) + warped * (mix * amt * edge_mask)
    return acc


def apply(ctx, f, clip):
    B = beatfx.lib()
    C = B.clock(ctx)
    t, k = B.song_t(ctx), B.frame(ctx)
    env, is_hit, _ = C.env(t, k)
    out = radial(B.pic(ctx, f), env, is_hit, B.text_flash(ctx), clip.get('params', {}), getattr(ctx, 'draft', False))
    return f if out is None else B.unpic(ctx, out)
