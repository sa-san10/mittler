"""外周ネオン（偽マリアのエフェクト集）：打ちのたびに、画面の外周がネオンのように光る。打ちの直後のコマを 1.0、次のコマ 0.3、そのあと消える
（コマ数で数えるので、拍がコマのどこに落ちても同じ強さ）。入りはフェードしない、0.04 秒早める。色は 1 発ごとに 2 色を交互（または hits の色の番号）。
人のマスク（ctx.m）があれば背景だけを光らせて人をその上に重ね、無ければ画面全体を光らせる。
params：hits（[[時刻, 色の番号], …]。空なら、クリップの中の拍（タイムラインの拍のメタデータ）、拍も無ければクリップの頭の 1 発）、
colors（[[r, g, b], [r, g, b]]。色の番号 0・1 の色）、gain（光の強さ）。
元は偽マリアMV（effects_lib/maria/edge_neon.py。作品の連続キックの演出）。部品にするときに、hits が空のときの打ち・色・強さのパラメータを足した。
マスター書き出し（ctx.scale）：縁の線・にじみ・奥まで届く光の幅（12・110・320 px）に ctx.scale を掛ける。
「打ちの直後のコマ・次のコマ」はタイムラインの fps のコマ（秒）で数える。"""
import bisect

import numpy as np

from mittler.lib import look

STAGE = 'v7'
DOC_EN = """Edge neon (False Maria effects): on each hit, the edges of the frame glow like neon. Full strength on the first frame after the hit, 0.3 on the next, then off
(counted in frames, so every hit looks the same wherever it falls). No fade-in; fires 0.04 s early. Two colors alternate (or use the color index in hits).
With a person mask (ctx.m) only the background glows and the person stays on top; without one the whole frame glows.
params: hits ([[time, color index], ...]. Empty = the beats inside the clip (the timeline's beat metadata), or one hit at the clip start if there are no beats),
colors ([[r, g, b], [r, g, b]] for color index 0 and 1), gain (glow strength).
From the False Maria MV (a neon flash on the outer edge for a run of kicks)."""
META = {'label': '外周ネオン（偽マリア）', 'label_en': 'Edge neon (False Maria)', 'time_params': ['hits'], 'scale_aware': True,
        'params': {'colors': {'type': 'json'}, 'gain': {'type': 'number', 'min': 0, 'max': 3, 'step': 0.05}},
        'defaults': {'colors': [[255, 70, 180], [170, 100, 255]], 'gain': 1.5}, 'dur': 2}

COLORS = ((255, 70, 180), (170, 100, 255))


def hits_of(ctx, clip):
    """打ちの並び [[時刻, 色の番号], …]（params.hits。空ならクリップの中の拍、それも無ければクリップの頭）"""
    ef = clip.get('params', {}).get('hits') or []
    if ef:
        return ef
    t0, t1 = clip.get('start', 0.0), clip.get('start', 0.0) + clip.get('dur', 0.0)
    bt = [b for b in ctx.beats.t if t0 <= b < t1]
    return [[b, i] for i, b in enumerate(bt)] or [[t0, 0]]


def apply(ctx, f, clip):
    p = clip.get('params', {})
    ef = hits_of(ctx, clip)
    mask = ctx.cache.get('fm_edge_neon_mask')
    if mask is None:
        H, W = ctx.H, ctx.W
        s = getattr(ctx, 'scale', 1)  # マスター書き出しの倍率（いつもは 1）
        ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
        d = np.minimum(np.minimum(xs, W - 1 - xs), np.minimum(ys, H - 1 - ys))  # 外周からの距離（px）
        # 縁の線 12px・にじみ 110px・奥まで届く光 320px（4K のキャンバスでは s 倍）
        mask = ctx.cache['fm_edge_neon_mask'] = (np.exp(-d / (12.0 * s)) * 1.0 + np.exp(-d / (110.0 * s)) * 0.95 + np.exp(-d / (320.0 * s)) * 0.6)[..., None]
    t = ctx.t + 0.04
    i = bisect.bisect_right([e[0] for e in ef], t) - 1
    if i < 0:
        return f
    fps0 = getattr(ctx.eng, 'tl_fps', ctx.fps)  # タイムラインの fps でコマを数える（マスター書き出しの 60fps でも光る長さは同じ）
    nf = int((t - ef[i][0]) * fps0 + 1e-6)
    k = (1.0, 0.3)[nf] if nf < 2 else 0.0
    if k <= 0:
        return f
    cols = p.get('colors') or COLORS
    col = np.array(cols[0] if int(ef[i][1]) % 2 == 0 else cols[1 % len(cols)], np.float32)
    lit = look.screen(f, np.clip(mask * col * k * p.get('gain', 1.5), 0, 255))
    m = ctx.m
    if m is None:
        return lit
    return lit * (1 - m[..., None]) + f * m[..., None]  # 人（前景）は光らせない＝光の上に人
