"""黒からのフェード・黒へのフェード（画面全体）。クリップの頭から fade_in 秒で黒から明けて、終わりの fade_out 秒で黒へ。
params：fade_in, fade_out（秒）
マスター書き出し（ctx.scale、機能追加案03 v2）：px の値が無い（画面全体の明るさを時刻だけで掛ける）ので、そのまま scale_aware と宣言している。"""
import numpy as np

STAGE = 'post'
DOC_EN = """Fade from black / fade to black (whole frame). Fades in from black over fade_in seconds from the clip start, and out to black over the last fade_out seconds.
params: fade_in, fade_out (seconds)"""
META = {'label': 'フェード', 'label_en': 'Fade', 'window': {'clip': True}, 'scale_aware': True,
        'params': {'fade_in': {'type': 'number', 'min': 0, 'max': 5, 'step': 0.05}, 'fade_out': {'type': 'number', 'min': 0, 'max': 5, 'step': 0.05}}}


def ease(p):
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def apply(ctx, f, clip):
    p = clip.get('params', {})
    fi, fo = float(p.get('fade_in', 0)), float(p.get('fade_out', 0))
    lt, end = ctx.t - clip['start'], clip['start'] + clip['dur']
    k = 1.0
    if fi > 0 and lt < fi:
        k *= ease(lt / fi)
    if fo > 0 and ctx.t > end - fo:
        k *= 1 - ease((ctx.t - (end - fo)) / fo)
    if k >= 1:
        return f
    return (f.astype(np.float32) * k).astype(np.uint8)
