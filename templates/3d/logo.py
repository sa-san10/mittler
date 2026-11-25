"""Blender の場面のひな形：ロゴ（文字）の組み上がり。Mittler の「Blender の 3D」のクリップ（effect: blender3d）の scene に `3d/logo.py` と書いて使う。
作品の `3d/` に写して直す（このファイルは Mittler のひな形。作品の外のものを直接指さない）。

args（クリップの params.args。無いものは下の ARGS）：
  text（字）, font（書体のファイル。作品の root からの相対か絶対。日本語の字は書体が要る）, color（字の色 0〜255）, metal・rough（金属らしさ・ざらつき）,
  intro（組み上がる秒）, stagger（字ごとのずれ）, orbit（クリップのあいだにカメラが回る角度）, dur（orbit の割り振りの長さ。書かなければクリップの長さ）, floor（影を受ける床）,
  size（字の大きさ）, light（光の強さの倍率）
決まり：build(scene, args) は 1 回、frame(scene, t, args) はコマごと（t はクリップの頭からの秒）。絵は t だけで決める（前のコマを覚えない。乱数は決まった種）。
"""
import math
import os
import random

import mittler_bpy as mb
from mathutils import Euler, Vector

ARGS = {'text': 'Mittler', 'font': '', 'color': [235, 196, 120], 'metal': 1.0, 'rough': 0.22, 'intro': 1.8, 'stagger': 0.07,
        'orbit': 30, 'dur': 5.0, 'floor': True, 'size': 1.0, 'light': 1.0}
S = {}  # build で作ったもの（コマごとの frame が使う。場面の組み立ては 1 回だけ）


def _a(args):
    a = dict(ARGS)
    a.update(args or {})
    return a


def build(scene, args):
    a = _a(args)
    font = a['font'] or None
    if font and not os.path.isabs(font):
        font = os.path.join(os.getcwd(), font)  # Blender は作品の root で起動している
    gold = mb.material('logo', a['color'], metal=a['metal'], rough=a['rough'], coat=0.3)
    S['letters'] = mb.letters(a['text'], font, size=a['size'], extrude=0.14 * a['size'], bevel=0.02 * a['size'], mat=gold, z=0.9 * a['size'])
    rnd = random.Random(7)  # 字ごとの、ばらばらの位置と回り方（決まった種）
    S['scatter'] = [(Vector((rnd.uniform(-5, 5), rnd.uniform(-6, 2), rnd.uniform(-1, 5))), Euler((rnd.uniform(-3, 3), rnd.uniform(-3, 3), rnd.uniform(-3, 3))))
                    for _ in S['letters']]
    mb.studio(key=a['light'] * 1600, fill=a['light'] * 600, rim=a['light'] * 1200, target=(0, 0, 0.9 * a['size']))
    mb.world((40, 44, 60), 0.8)  # まわりの光（金属に映る。背景は透明に描かれる）
    if a['floor']:
        mb.floor(catcher=True)
    S['cam'] = mb.camera(lens=50)
    S['target'] = (0, 0, 0.8 * a['size'])


def frame(scene, t, args):
    a = _a(args)
    for i, (o, home) in enumerate(S['letters']):
        q = (t - i * a['stagger']) / a['intro']
        e = mb.ease_out(q, 4)
        off, rot = S['scatter'][i]
        o.location = home + off * (1 - e)
        o.rotation_euler = Euler((math.radians(90) + rot.x * (1 - e), rot.y * (1 - e), rot.z * (1 - e)))
        o.hide_render = q <= 0
    yaw = a['orbit'] * (t / max(a['dur'], 1e-6) - 0.5)
    cam = S['cam']
    w = max((abs(h.x) for _, h in S['letters']), default=1.0) * 2 + 2  # 組み上がった字の幅（動いている途中の位置は使わない）
    cam.location = Vector(mb.orbit_pos(S['target'], yaw=yaw, pitch=8, dist=max(6.0, w * 1.25)))
    mb.look_at(cam, S['target'])
