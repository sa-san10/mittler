"""区間ごとの色（シーン別の色調整）：区間（segments）ごとに映像の空気感を変える。どれにも入らないところは「ふだん」（彩度とコントラストを少し上げ、打点で彩度がもう少し上がる）。
segments：[{t0, t1, kind, …}]（上から順に、最初に入った区間だけ。時刻は settings.beatfx.song_t0 があれば曲の秒）。kind：
  cool  氷のような青：彩度を desat（0.35）抜いて tint（[0.85, 1.02, 1.22]）を掛ける。頭 ramp_in・終わり ramp_out 秒でなじむ。
        contrast [c0, c1, 倍率] の間はコントラストを上げる（FREEZE! の直後）
  hot   オーバーヒート：ramp 秒で彩度を 1＋sat（0.55）倍まで上げ、mul（[1.14, 0.98, 1.06]）を掛けて add（[0.04, 0, 0.02]）を足す
  mono  時が止まるモノクローム：ramp_in・ramp_out でなじませて、amount（0.82）だけ高コントラストの白黒に（銀残し風）
  punch 彩度 sat（1.30）・コントラスト contrast（1.12）
ふだん（base）：彩度 sat（1.10）＋ env_sat（0.08）× 打点（env、1 まで）、コントラスト contrast（1.05）。最後に 0〜1 に切る。
打点の時計は settings.beatfx（_lib/beatfx.py）。px の値は無いので、そのまま 4K（scale_aware）。
元：作者のダンス動画（Attention）の OVERDRIVE 版（2026-10-14）の apply_scene_grading（氷結 → 灼熱 → STOP の無彩色 → ALL YOU NEED の3連打）。
色の値は作品ごとにユーザーが決める（頼まれない限り Claude が値を決めない）。"""
import sys
from pathlib import Path

import numpy as np

_LIB = str(Path(__file__).resolve().parent / '_lib')
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
import beatfx  # noqa: E402

STAGE = 'v7'
META = {'label': '区間ごとの色', 'label_en': 'Color by section','window': {'clip': True}, 'scale_aware': True,
        'params': {'segments': {'type': 'json'}, 'base': {'type': 'json'}}}

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def grade(out, t, env, segs, base):
    luma = (out @ LUMA)[..., None]
    for sg in segs:
        if not (sg['t0'] <= t < sg['t1']):
            continue
        kind = sg.get('kind')
        if kind == 'cool':
            s = min(1.0, (t - sg['t0']) / sg.get('ramp_in', 0.15)) * min(1.0, (sg['t1'] - t) / sg.get('ramp_out', 0.15))
            d = sg.get('desat', 0.35)
            desat = out * (1.0 - d * s) + luma * (d * s)
            tint = np.array(sg.get('tint', [0.85, 1.02, 1.22]), np.float32)
            out = desat * (1.0 - s + s * tint)
            c = sg.get('contrast')
            if c and c[0] <= t < c[1]:
                out = (out - 0.5) * c[2] + 0.5
        elif kind == 'hot':
            u = min(1.0, (t - sg['t0']) / sg.get('ramp', 0.55))
            out = luma + (out - luma) * (1.0 + sg.get('sat', 0.55) * u)
            out = out * np.array(sg.get('mul', [1.14, 0.98, 1.06]), np.float32) + np.array(sg.get('add', [0.04, 0.0, 0.02]), np.float32) * u
        elif kind == 'mono':
            s = min(1.0, (t - sg['t0']) / sg.get('ramp_in', 0.05)) * min(1.0, (sg['t1'] - t) / sg.get('ramp_out', 0.06))
            a = sg.get('amount', 0.82)
            hi_contrast = np.clip((luma - 0.48) * 1.35 + 0.48, 0.0, 1.0)
            out = out * (1.0 - a * s) + hi_contrast * (a * s)
        elif kind == 'punch':
            out = luma + (out - luma) * sg.get('sat', 1.30)
            out = (out - 0.5) * sg.get('contrast', 1.12) + 0.5
        return np.clip(out, 0.0, 1.0)
    boost = base.get('sat', 1.10) + base.get('env_sat', 0.08) * min(1.0, env)
    out = luma + (out - luma) * boost
    out = (out - 0.5) * base.get('contrast', 1.05) + 0.5
    return np.clip(out, 0.0, 1.0)


def apply(ctx, f, clip):
    B = beatfx.lib()
    p = clip.get('params', {})
    C = B.clock(ctx)
    t, k = B.song_t(ctx), B.frame(ctx)
    env = C.env(t, k)[0]
    return B.unpic(ctx, grade(B.pic(ctx, f), t, env, p.get('segments', []), p.get('base', {})))
