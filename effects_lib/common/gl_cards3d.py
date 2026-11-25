"""3D の板（GPU の 3D。2026-11-13、3D 強化）。絵・動画のコマ・今の画面を板に貼って 3D の空間に並べ、回す（画面の録画のカードが
輪になって回る・壁のように並んだ中をカメラが進む・扇に開く・1 枚がくるっと入ってくる）。床への映り込みと影も付けられる。
params：sources（1 行に 1 つ：作品の絵・動画のパス（root からの相対）、または @frame＝このエフェクトより下の今の絵）,
  layout（ring＝輪・wall＝壁・fan＝扇・single＝1 枚）, height（板の高さ＝画面の高さに対する割合）, spin（輪・扇の回る速さ 度/秒）,
  intro（板が飛んでくる秒）, stagger（板ごとのずれの秒）, orbit・pitch（カメラ）, corner（角の丸み）, light（光の当たり方 0〜1）,
  bg・bg_alpha（下の絵を塗る色と強さ。1 で黒などの空間にする）, floor・reflect（床の映り込みと影）, offset（動画の頭の秒）, opacity
動画は ffmpeg でその時刻のコマを取る（クリップの頭からの秒＋offset。長さをこえたら繰り返す）。
GPU（OpenGL 3.3、moderngl）が要る。無い PC では理由つきで止まる。絵は時刻だけで決まる。同じ PC・同じ設定なら同じ時刻は同じ絵。"""
import math

import numpy as np

from mittler import gl3d

STAGE = 'v7'
DOC_EN = """3D cards (GPU 3D). Puts images, video frames or the current picture on cards in 3D space and moves them (screen-capture cards
spinning in a ring, a wall of cards the camera flies along, a fan, or one card flipping in). Optional floor reflection and shadow.
params: sources (one per line: an image or video path relative to root, or @frame = the picture below this effect),
  layout (ring / wall / fan / single), height (card height as a fraction of the frame height), spin (ring/fan speed, deg/s),
  intro (seconds for cards to fly in), stagger (per-card delay), orbit / pitch (camera), corner (rounding), light (how much light affects the cards, 0-1),
  bg / bg_alpha (fill color for the picture below and its strength; 1 makes a dark space), floor / reflect, offset (video start offset, s), opacity
Videos are read frame-accurately with ffmpeg (seconds from the clip start + offset, looping).
Needs the GPU (OpenGL 3.3, moderngl); stops with a reason without it. Same PC and settings give the same picture."""
META = {
    'label': '3D の板', 'label_en': '3D Cards', 'window': {'clip': True}, 'scale_aware': True, 'draft': True, 'gl3d': True,
    'params': {
        'sources': {'type': 'lines'}, 'layout': {'type': 'choice', 'choices': ['ring', 'wall', 'fan', 'single']},
        'height': {'type': 'number', 'min': 0.05, 'max': 1.5, 'step': 0.01}, 'spin': {'type': 'number', 'min': -90, 'max': 90, 'step': 0.5},
        'intro': {'type': 'number', 'min': 0, 'max': 10, 'step': 0.05}, 'stagger': {'type': 'number', 'min': 0, 'max': 2, 'step': 0.01},
        'orbit': {'type': 'number', 'min': -180, 'max': 180, 'step': 1}, 'pitch': {'type': 'number', 'min': -30, 'max': 80, 'step': 1},
        'corner': {'type': 'number', 'min': 0, 'max': 0.5, 'step': 0.01}, 'light': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01},
        'bg': {'type': 'color'}, 'bg_alpha': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01},
        'floor': {'type': 'bool'}, 'reflect': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01},
        'offset': {'type': 'number', 'min': 0, 'max': 3600, 'step': 0.1}, 'opacity': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01},
    },
}
DEFAULTS = {'sources': ['@frame'], 'layout': 'ring', 'height': 0.32, 'spin': 14, 'intro': 1.2, 'stagger': 0.12, 'orbit': 16, 'pitch': 10,
            'corner': 0.04, 'light': 0.3, 'bg': [8, 9, 14], 'bg_alpha': 1.0, 'floor': True, 'reflect': 0.3, 'offset': 0.0, 'opacity': 1.0}
META.update(defaults=DEFAULTS, dur=4)  # 編集画面で置くときの値と長さ
FOV = 38.0


def _lines(v):
    if isinstance(v, str):
        v = v.split('\n')
    return [s.strip() for s in (v or []) if s.strip()]


def apply(ctx, f, clip):
    p = dict(DEFAULTS, **(clip.get('params') or {}))
    lt = ctx.t - clip['start']
    dur = max(1e-6, float(clip['dur']))
    srcs = _lines(p['sources']) or ['@frame']
    frame_img = None
    imgs = []
    for s in srcs:
        if s == '@frame':
            if frame_img is None:
                frame_img = np.clip(f, 0, 255).astype(np.uint8)
            imgs.append(frame_img)
        else:
            imgs.append(gl3d.media_frame(ctx.cache, ctx.root, s, lt + float(p['offset']), ctx.fps))
    n = len(imgs)
    h = 1.0
    size = max(0.02, float(p['height']))
    dist = 1.0 / (size * 2 * math.tan(math.radians(FOV) / 2))   # 板の高さ 1 が画面の高さの size に見える距離（輪の手前の板）
    layout = p.get('layout', 'ring')
    intro, stg = max(1e-3, float(p['intro'])), float(p['stagger'])
    spin = float(p['spin'])
    yaw = float(p['orbit']) * (lt / dur - 0.5)
    pitch = float(p['pitch'])
    light = float(p['light'])
    corner = float(p['corner'])
    floor_y = -h / 2 - 0.12
    # 並べ方：板 i の行列（入ってくる途中の e で、下から回りながら来る）
    widths = [h * im.shape[1] / im.shape[0] for im in imgs]
    W_ = max(widths) if widths else h * 16 / 9
    if layout == 'ring':
        R = max(1.2, n * (W_ * 1.15) / (2 * math.pi))
        target, eye_d = (0, -0.35 * h, 0), R + dist  # 少し下を狙う（手前の板が画面の真ん中あたりに来るように）
    elif layout == 'wall':
        target, eye_d = (0, 0, 0), dist * 1.15
    else:
        target, eye_d = (0, 0, 0), dist

    def card_matrix(i):
        e = gl3d.back_out((lt - i * stg) / intro, 1.0) if intro > 0 else 1.0
        a = gl3d.smooth((lt - i * stg) / (intro * 0.5))
        if layout == 'ring':
            ang = 360.0 * i / n + spin * lt
            m = gl3d.chain(gl3d.rot_y(ang), gl3d.translate(0, 0, R))
        elif layout == 'wall':
            cols = max(1, math.ceil(math.sqrt(n * 1.6)))
            r_, c_ = divmod(i, cols)
            rows = math.ceil(n / cols)
            x = (c_ - (cols - 1) / 2) * W_ * 1.12
            y = ((rows - 1) / 2 - r_) * h * 1.15
            m = gl3d.chain(gl3d.translate(x, y, -0.4 * abs(x)), gl3d.rot_y(-12 * x / max(W_, 1e-6)))
        elif layout == 'fan':
            ang = (i - (n - 1) / 2) * 18 + spin * 0.15 * math.sin(lt * 0.8)
            m = gl3d.chain(gl3d.translate(0, -1.6, 0), gl3d.rot_z(-ang), gl3d.translate(0, 1.6, 0.02 * i))
        else:
            m = gl3d.rot_y(spin * 0.2 * math.sin(lt * 0.6))
        fly = gl3d.chain(gl3d.translate(0, -2.5 * (1 - e), 1.5 * (1 - e)), gl3d.rot_x(70 * (1 - e)), gl3d.rot_y(-50 * (1 - e)))
        return m @ fly, a

    def build(sc):
        if layout == 'wall':
            pan = (lt / dur - 0.5) * W_ * 1.5
            sc.camera((pan + eye_d * math.sin(math.radians(yaw)), eye_d * math.sin(math.radians(pitch)), eye_d * math.cos(math.radians(yaw))), (pan * 0.8, 0, 0), fov=FOV)
        else:
            sc.camera(gl3d.orbit(target, yaw=yaw, pitch=pitch, dist=eye_d), target, fov=FOV)
        sc.light(dir=(-0.4, 0.7, 0.8))
        if p.get('floor') and layout != 'wall':
            sc.floor(y=floor_y if layout != 'fan' else -2.0, reflect=float(p['reflect']), shadow=0.45, fade=0.004, alpha=0.0)
        for i, im in enumerate(imgs):
            m, a = card_matrix(i)
            if a <= 0:
                continue
            w = widths[i]
            sc.card(im, m, w=w, h=h, radius=corner, light=light, alpha=a)

    rgba = gl3d.render(ctx.W, ctx.H, build, samples=gl3d.samples_for(ctx))
    ba = float(p['bg_alpha'])
    if ba > 0:  # 下の絵を塗る（3D の空間にする）
        bg = np.asarray((list(p['bg']) + [0, 0, 0])[:3], np.float32)
        f *= (1.0 - ba)
        f += bg * ba
    return gl3d.over(f, rgba, float(p['opacity']))
