"""シャッターの白フラッシュ（偽マリアのエフェクト集）：プリ機のシャッターのような白い光。切れ目の 1 コマ前から立ち上がり（0.45）、切れ目で最大（0.9）、
そのあと 0.07 秒の指数で消える。
params：times（切れ目の時刻の並び。空ならクリップの頭の 1 回）。クリップの中の切れ目だけ光る（クリップの頭より前の立ち上がりは出ない）。
元は偽マリアMV（effects_lib/maria/shutter_flash.py。プリのカットの切れ目）。部品にするときに、times が空のときの 1 回を足し、作品のカットインのクリップを見る所を外した。
マスター書き出し（ctx.scale）：画面全体の色だけで px の値が無い。「1 コマ前」はタイムラインの fps の 1 コマ（秒）で数える。"""
import math

import numpy as np

STAGE = 'post'
DOC_EN = """Shutter flash (False Maria effects): a white flash like a photo-booth shutter. Rises one frame before the cut (0.45), peaks at the cut (0.9),
then fades out exponentially over about 0.07 s.
params: times (list of cut times. Empty = once at the clip start). Only cuts inside the clip flash.
From the False Maria MV (the photo-booth cuts)."""
META = {'label': 'シャッターの白フラッシュ（偽マリア）', 'label_en': 'Shutter flash (False Maria)', 'time_params': ['times'], 'scale_aware': True,
        'params': {'times': {'type': 'json'}}, 'defaults': {'times': []}, 'dur': 0.5}


def apply(ctx, f, clip):
    times = clip.get('params', {}).get('times') or [clip.get('start', 0.0)]
    t, a = ctx.t, 0.0
    fps0 = getattr(ctx.eng, 'tl_fps', ctx.fps)  # タイムラインの fps（マスター書き出しの 60fps でも「1コマ」はこれで数える）
    for ft in times:
        d = t - ft
        if -1.0 / fps0 - 1e-6 <= d < 0:
            a = max(a, 0.45)
        elif 0 <= d < 0.4:
            a = max(a, 0.9 * math.exp(-d / 0.07))
    if a > 0.004:
        f = (f.astype(np.float32) * (1 - a) + 255 * a).astype(np.uint8)
    return f
