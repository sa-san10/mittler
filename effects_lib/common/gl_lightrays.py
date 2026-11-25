"""光の筋（GPU の 3D。2026-11-13、3D 強化）。3D の空間を走る光の筋：手前へ飛んでくるワープの筋・ゆっくり回るステージの光の帯・下からのぼる筋。
足して明るくする（下の絵は消さない）。
params：mode（warp＝ワープ・beams＝回る光の帯・rise＝のぼる筋）, count（筋の数）, length（筋の長さ）, width（太さ）, color・color2（色）,
  speed（速さ）, spread（広がり）, orbit（カメラの回り込み・度）, intensity（明るさ）, seed（並びの種）, fade_in・fade_out（秒）
GPU（OpenGL 3.3、moderngl）が要る。無い PC では理由つきで止まる。筋の位置は種と時刻だけで決まる。"""
import math

import numpy as np

from mittler import gl3d

STAGE = 'v7'
DOC_EN = """Light streaks (GPU 3D). Streaks of light running through 3D space: warp streaks flying at the camera, slowly turning stage-light beams,
or rising streaks. Additive (the picture below stays).
params: mode (warp / beams / rise), count, length, width, color / color2, speed, spread, orbit (camera, degrees), intensity, seed, fade_in / fade_out (seconds)
Needs the GPU (OpenGL 3.3, moderngl); stops with a reason without it. Positions depend only on the seed and time."""
META = {
    'label': '光の筋', 'label_en': 'Light Streaks', 'window': {'clip': True}, 'scale_aware': True, 'draft': True, 'gl3d': True,
    'params': {
        'mode': {'type': 'choice', 'choices': ['warp', 'beams', 'rise']}, 'count': {'type': 'int', 'min': 1, 'max': 5000},
        'length': {'type': 'number', 'min': 0.05, 'max': 40, 'step': 0.05}, 'width': {'type': 'number', 'min': 0.002, 'max': 2, 'step': 0.001},
        'color': {'type': 'color'}, 'color2': {'type': 'color'}, 'speed': {'type': 'number', 'min': 0, 'max': 60, 'step': 0.1},
        'spread': {'type': 'number', 'min': 0.5, 'max': 40, 'step': 0.1}, 'orbit': {'type': 'number', 'min': -180, 'max': 180, 'step': 1},
        'intensity': {'type': 'number', 'min': 0, 'max': 5, 'step': 0.01}, 'seed': {'type': 'int', 'min': 0, 'max': 9999},
        'fade_in': {'type': 'number', 'min': 0, 'max': 5, 'step': 0.05}, 'fade_out': {'type': 'number', 'min': 0, 'max': 5, 'step': 0.05},
    },
}
DEFAULTS = {'mode': 'warp', 'count': 260, 'length': 3.0, 'width': 0.035, 'color': [120, 190, 255], 'color2': [255, 160, 220], 'speed': 14.0,
            'spread': 6.0, 'orbit': 0, 'intensity': 1.2, 'seed': 11, 'fade_in': 0.4, 'fade_out': 0.4}
META.update(defaults=DEFAULTS, dur=4)  # 編集画面で置くときの値と長さ


def apply(ctx, f, clip):
    p = dict(DEFAULTS, **(clip.get('params') or {}))
    lt = ctx.t - clip['start']
    dur = max(1e-6, float(clip['dur']))
    n = int(p['count'])
    if ctx.draft:
        n = max(1, n // 2)
    rng = np.random.default_rng(int(p['seed']))
    U = rng.random((int(p['count']), 6))[:n]
    mode = p.get('mode', 'warp')
    L, sp, spd = float(p['length']), float(p['spread']), float(p['speed'])
    wd = float(p['width']) * (0.6 + 0.8 * U[:, 4])
    c1 = np.asarray(p['color'], np.float64)[:3] / 255
    c2 = np.asarray(p['color2'], np.float64)[:3] / 255
    C = c1[None, :] * (1 - U[:, 3:4]) + c2[None, :] * U[:, 3:4]
    fi, fo = float(p['fade_in']), float(p['fade_out'])
    k = float(p['intensity'])
    if fi > 0:
        k *= gl3d.smooth(lt / fi)
    if fo > 0:
        k *= 1 - gl3d.smooth((lt - (dur - fo)) / fo)
    if mode == 'warp':   # 筒の上に並んだ筋が手前へ飛んでくる
        depth = 60.0
        ang = U[:, 0] * 2 * math.pi
        r = sp * (0.25 + 0.75 * np.sqrt(U[:, 1]))
        zh = -depth + np.mod(U[:, 2] * depth + spd * lt * (0.7 + 0.6 * U[:, 5]), depth)
        P1 = np.stack([r * np.cos(ang), r * np.sin(ang), zh], axis=1)
        P0 = P1 - np.array([0, 0, 1.0]) * (L * (0.5 + U[:, 4]))[:, None]
        a = np.clip((zh + depth) / 10, 0, 1) * np.clip((1.0 - zh) / 2.0, 0, 1)
        eye, target, fov = (0, 0, 1.5), (0, 0, -10), 60
    elif mode == 'beams':  # 真ん中から放たれた長い光の帯が、ゆっくり回る
        base = np.array([0.0, -3.0, -8.0])
        az = U[:, 0] * 2 * math.pi + spd * 0.02 * lt * (U[:, 5] - 0.5) * 4
        el = math.radians(35) + U[:, 1] * math.radians(50) + 0.15 * np.sin(lt * 0.7 + U[:, 2] * 6.28)
        d = np.stack([np.cos(el) * np.cos(az), np.sin(el), np.cos(el) * np.sin(az)], axis=1)
        P0 = np.tile(base, (n, 1))
        P1 = P0 + d * (L * 4 * (0.6 + 0.6 * U[:, 4]))[:, None]
        wd = wd * 12
        a = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(lt * (0.8 + U[:, 3]) + U[:, 2] * 6.28))
        eye, target, fov = (0, 0.5, 6), (0, 1, -8), 55
    else:  # rise
        y = -sp + np.mod(U[:, 1] * sp * 2 + spd * 0.4 * lt * (0.6 + 0.8 * U[:, 5]), sp * 2)
        x = (U[:, 0] * 2 - 1) * sp
        z = -U[:, 2] * sp * 1.5
        P1 = np.stack([x, y, z], axis=1)
        P0 = P1 - np.array([0, 1.0, 0]) * (L * 0.5 * (0.5 + U[:, 4]))[:, None]
        a = np.ones(n)
        eye, target, fov = (0, 0, 6), (0, 0, -3), 55
    yaw = float(p['orbit']) * (lt / dur - 0.5)

    def build(sc):
        e = np.asarray(eye, np.float64)
        tg = np.asarray(target, np.float64)
        v = e - tg
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        e2 = tg + np.array([c * v[0] + s * v[2], v[1], -s * v[0] + c * v[2]])
        sc.camera(e2, tg, fov=fov, far=400)
        sc.streaks(P0, P1, wd, C * k, a)

    rgba = gl3d.render(ctx.W, ctx.H, build, samples=gl3d.samples_for(ctx))
    return gl3d.lighten(f, rgba)
