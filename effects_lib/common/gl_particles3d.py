"""奥行きのある粒子（GPU の 3D。2026-11-13、3D 強化）。3D の空間に光の粒を散らし、カメラの方へ流す・ただよわせる・上へのぼらせる。
遠い粒は小さく暗く、ピントの外の粒は大きくぼける（被写界深度のような見え方）。足して明るくする（下の絵は消さない）。
params：count（粒の数）, size（粒の大きさ）, color・color2（色。粒ごとに 2 色のあいだ）, mode（fly＝手前へ流れる・drift＝ただよう・rise＝のぼる）,
  speed（速さ）, spread（横の広がり）, depth（奥行き）, focus（ピントの距離。0 でぼかさない）, twinkle（またたき 0〜1）, orbit（カメラの回り込み・度）,
  intensity（明るさ）, seed（並びの種）, fade_in・fade_out（秒）
GPU（OpenGL 3.3、moderngl）が要る。無い PC では理由つきで止まる。粒の位置は種と時刻だけで決まる（前のコマを覚えない）。"""
import math

import numpy as np

from mittler import gl3d

STAGE = 'v7'
DOC_EN = """3D particles (GPU 3D). Scatters glowing particles in 3D space and streams them toward the camera, lets them drift, or makes them rise.
Far particles are smaller and dimmer; out-of-focus ones grow and soften (depth-of-field look). Additive (the picture below stays).
params: count, size, color / color2 (each particle between the two), mode (fly / drift / rise), speed, spread, depth, focus (0 = no blur),
  twinkle (0-1), orbit (camera orbit, degrees), intensity, seed, fade_in / fade_out (seconds)
Needs the GPU (OpenGL 3.3, moderngl); stops with a reason without it. Positions depend only on the seed and time."""
META = {
    'label': '奥行きのある粒子', 'label_en': '3D Particles', 'window': {'clip': True}, 'scale_aware': True, 'draft': True, 'gl3d': True,
    'params': {
        'count': {'type': 'int', 'min': 1, 'max': 50000}, 'size': {'type': 'number', 'min': 0.002, 'max': 0.5, 'step': 0.001},
        'color': {'type': 'color'}, 'color2': {'type': 'color'}, 'mode': {'type': 'choice', 'choices': ['fly', 'drift', 'rise']},
        'speed': {'type': 'number', 'min': 0, 'max': 20, 'step': 0.05}, 'spread': {'type': 'number', 'min': 0.5, 'max': 30, 'step': 0.1},
        'depth': {'type': 'number', 'min': 1, 'max': 100, 'step': 0.5}, 'focus': {'type': 'number', 'min': 0, 'max': 50, 'step': 0.1},
        'twinkle': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01}, 'orbit': {'type': 'number', 'min': -180, 'max': 180, 'step': 1},
        'intensity': {'type': 'number', 'min': 0, 'max': 5, 'step': 0.01}, 'seed': {'type': 'int', 'min': 0, 'max': 9999},
        'fade_in': {'type': 'number', 'min': 0, 'max': 5, 'step': 0.05}, 'fade_out': {'type': 'number', 'min': 0, 'max': 5, 'step': 0.05},
    },
}
DEFAULTS = {'count': 1500, 'size': 0.03, 'color': [255, 210, 140], 'color2': [140, 190, 255], 'mode': 'fly', 'speed': 1.5, 'spread': 8.0,
            'depth': 30.0, 'focus': 5.0, 'twinkle': 0.4, 'orbit': 10, 'intensity': 1.0, 'seed': 3, 'fade_in': 0.5, 'fade_out': 0.5}
META.update(defaults=DEFAULTS, dur=4)  # 編集画面で置くときの値と長さ


def apply(ctx, f, clip):
    p = dict(DEFAULTS, **(clip.get('params') or {}))
    lt = ctx.t - clip['start']
    dur = max(1e-6, float(clip['dur']))
    n = int(p['count'])
    if ctx.draft:
        n = max(1, n // 3)
    rng = np.random.default_rng(int(p['seed']))
    U = rng.random((int(p['count']), 7))[:n]          # 粒ごとの決まった値（ドラフトは頭の 1/3 の粒だけ。位置は同じ）
    sp, dp, spd = float(p['spread']), float(p['depth']), float(p['speed'])
    x = (U[:, 0] * 2 - 1) * sp
    y = (U[:, 1] * 2 - 1) * sp * 0.6
    z0 = U[:, 2] * dp
    mode = p.get('mode', 'fly')
    if mode == 'fly':      # 手前（+z）へ流れて、カメラを過ぎたら奥へ戻る
        z = -dp + np.mod(z0 + spd * lt * (0.6 + 0.8 * U[:, 3]), dp)
    elif mode == 'rise':
        z = -z0
        y = -sp * 0.6 + np.mod((U[:, 1]) * sp * 1.2 + spd * 0.3 * lt * (0.5 + U[:, 3]), sp * 1.2)
        x = x + 0.15 * np.sin(lt * (0.5 + U[:, 4]) + U[:, 5] * 6.28)
    else:                  # ただよう
        z = -z0
        x = x + 0.4 * np.sin(lt * spd * 0.3 * (0.5 + U[:, 3]) + U[:, 4] * 6.28)
        y = y + 0.3 * np.cos(lt * spd * 0.25 * (0.5 + U[:, 5]) + U[:, 6] * 6.28)
    P = np.stack([x, y, z], axis=1)
    cam_z = 1.0
    d = np.maximum(cam_z - z, 0.05)
    size = float(p['size']) * (0.5 + U[:, 4])
    focus = float(p['focus'])
    blur = np.zeros(n) if focus <= 0 else np.clip(np.abs(d - focus) / max(focus, 1e-3), 0, 3)
    size = size * (1 + 2.5 * blur)
    a = (1 / (1 + 1.5 * blur ** 2)) * np.clip(1.2 - d / (dp + 2), 0.05, 1.0)
    tw = float(p['twinkle'])
    a = a * (1 - tw * 0.5 * (1 + np.sin(lt * (2 + 5 * U[:, 5]) + U[:, 6] * 6.28)))
    a = a * np.clip((d - 0.1) / 0.6, 0, 1)            # カメラのすぐ前で消す（大きな粒が画面をふさがないように）
    c1 = np.asarray(p['color'], np.float64)[:3] / 255
    c2 = np.asarray(p['color2'], np.float64)[:3] / 255
    C = c1[None, :] * (1 - U[:, 3:4]) + c2[None, :] * U[:, 3:4]
    fi, fo = float(p['fade_in']), float(p['fade_out'])
    k = float(p['intensity'])
    if fi > 0:
        k *= gl3d.smooth(lt / fi)
    if fo > 0:
        k *= 1 - gl3d.smooth((lt - (dur - fo)) / fo)
    yaw = float(p['orbit']) * (lt / dur - 0.5)

    def build(sc):
        sc.camera((math.sin(math.radians(yaw)) * cam_z, 0, math.cos(math.radians(yaw)) * cam_z), (0, 0, -10), fov=50)
        sc.points(P, size, C * k, a)

    rgba = gl3d.render(ctx.W, ctx.H, build, samples=gl3d.samples_for(ctx))
    return gl3d.lighten(f, rgba)
