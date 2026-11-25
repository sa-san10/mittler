"""Blender の場面のスクリプト（作品の `3d/<名前>.py`）が使う道具。Blender の中で `import mittler_bpy as mb` で読める（blender_runner.py が入れる）。

場面のスクリプトの決まり（ひな形は templates/3d/）：
    import mittler_bpy as mb
    def build(scene, args):        # 1 回だけ：場面を組む（カメラ・光・物・材質）。args はクリップの params.args
        ...
    def frame(scene, t, args):     # コマごと：クリップの頭から t 秒の形にする（t だけで決める。前のコマを覚えない）
        ...
長さの単位はメートル（Blender のまま）。y が奥・z が上（Blender の座標）。
"""
import math

import bpy
from mathutils import Euler, Vector


def clear():
    """まっさらにする（物・材質・光・カメラ・世界を消す）"""
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras, bpy.data.curves):
        for x in list(coll):
            coll.remove(x)
    sc = bpy.context.scene
    if sc.world is None:
        sc.world = bpy.data.worlds.new('World')
    return sc


# ---- 時間の曲線（t だけで決める）
def clamp01(x):
    return min(1.0, max(0.0, float(x)))


def smooth(x):
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def ease_out(x, k=3.0):
    x = clamp01(x)
    return 1 - (1 - x) ** k


def back_out(x, s=1.7):
    x = clamp01(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def lerp(a, b, k):
    return a + (b - a) * k


# ---- 色・材質・世界
def srgb(c):
    """0〜255 か 0〜1 の sRGB → Blender の線形の色（RGBA）"""
    c = [float(x) for x in c][:3]
    if max(c) > 1.0:
        c = [x / 255.0 for x in c]

    def lin(x):
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return (lin(c[0]), lin(c[1]), lin(c[2]), 1.0)


def material(name, color=(0.8, 0.8, 0.8), metal=0.0, rough=0.4, emit=0.0, emit_color=None, alpha=1.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = srgb(color)
    b.inputs['Metallic'].default_value = float(metal)
    b.inputs['Roughness'].default_value = float(rough)
    if 'Coat Weight' in b.inputs:
        b.inputs['Coat Weight'].default_value = float(coat)
    if emit > 0:
        b.inputs['Emission Color'].default_value = srgb(emit_color or color)
        b.inputs['Emission Strength'].default_value = float(emit)
    if alpha < 1:
        b.inputs['Alpha'].default_value = float(alpha)
    return m


def world(color=(10, 12, 18), strength=1.0):
    """世界（背景と、まわりからの光）の色。クリップの transparent が true なら、背景は透明に描かれる（光だけ効く）"""
    w = bpy.context.scene.world
    w.use_nodes = True
    bg = w.node_tree.nodes.get('Background')
    bg.inputs['Color'].default_value = srgb(color)
    bg.inputs['Strength'].default_value = float(strength)
    return w


# ---- カメラ・光
def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def camera(loc=(0, -8, 1.5), target=(0, 0, 0.6), lens=50.0, dof=None):
    """カメラを置いて場面のカメラにする。dof＝ピントの距離（m。None でぼかさない）"""
    cd = bpy.data.cameras.new('Camera')
    cd.lens = float(lens)
    if dof:
        cd.dof.use_dof = True
        cd.dof.focus_distance = float(dof)
        cd.dof.aperture_fstop = 2.8
    o = bpy.data.objects.new('Camera', cd)
    bpy.context.scene.collection.objects.link(o)
    o.location = Vector(loc)
    look_at(o, target)
    bpy.context.scene.camera = o
    return o


def orbit_pos(target=(0, 0, 0), yaw=0.0, pitch=10.0, dist=8.0):
    """target のまわりを回るカメラの位置（yaw：z 軸のまわりの角度・度。0 で手前（−y）から、pitch：見下ろす角度・度）"""
    a, b = math.radians(yaw), math.radians(pitch)
    tx, ty, tz = target
    return (tx + dist * math.cos(b) * math.sin(a), ty - dist * math.cos(b) * math.cos(a), tz + dist * math.sin(b))


def light(kind='AREA', loc=(3, -3, 4), target=(0, 0, 0), energy=500.0, color=(255, 255, 255), size=2.0):
    ld = bpy.data.lights.new(kind.lower(), kind)
    ld.energy = float(energy)
    ld.color = srgb(color)[:3]
    if kind == 'AREA':
        ld.size = float(size)
    o = bpy.data.objects.new(kind.lower(), ld)
    bpy.context.scene.collection.objects.link(o)
    o.location = Vector(loc)
    look_at(o, target)
    return o


def studio(key=800.0, fill=250.0, rim=600.0, target=(0, 0, 0.6)):
    """3 灯（キー・フィル・リム）の光を置く"""
    return [light('AREA', (-4, -4, 5), target, key, size=4), light('AREA', (5, -3, 2), target, fill, (200, 220, 255), size=5),
            light('AREA', (0, 5, 4), target, rim, (180, 210, 255), size=3)]


# ---- 物
def text3d(body, font=None, size=1.0, extrude=0.12, bevel=0.015, mat=None, align='CENTER', loc=(0, 0, 0)):
    """立体の文字（Blender の文字の物）。font：書体のファイル（無ければ Blender の書体。日本語は書体を渡す）。立てて（xz の面）手前を向く"""
    cu = bpy.data.curves.new('text', 'FONT')
    cu.body = str(body)
    if font:
        cu.font = bpy.data.fonts.load(str(font), check_existing=True)
    cu.size = float(size)
    cu.extrude = float(extrude)
    cu.bevel_depth = float(bevel)
    cu.bevel_resolution = 3
    cu.align_x = align
    cu.align_y = 'CENTER'
    o = bpy.data.objects.new('text', cu)
    bpy.context.scene.collection.objects.link(o)
    o.location = Vector(loc)
    o.rotation_euler = Euler((math.radians(90), 0, 0))
    if mat:
        o.data.materials.append(mat)
    return o


def letters(text, font=None, size=1.0, extrude=0.12, bevel=0.015, mat=None, tracking=0.06, z=0.0):
    """字を 1 字ずつの物にして横に並べる（ロゴの組み上がり用）。返すのは [(物, 組み上がった位置), …]"""
    objs = []
    x = 0.0
    for ch in str(text):
        if not ch.strip():
            x += size * 0.35
            continue
        o = text3d(ch, font, size, extrude, bevel, mat, align='LEFT')
        bpy.context.view_layer.update()
        w = o.dimensions.x
        objs.append([o, x, w])
        x += w + size * tracking
    total = x - size * tracking
    out = []
    for o, x0, w in objs:
        home = Vector((x0 - total / 2, 0.0, z))
        o.location = home
        out.append((o, home.copy()))
    return out


def floor(size=60.0, color=(8, 9, 12), rough=0.15, metal=0.0, z=0.0, catcher=False):
    """床。catcher=True なら影だけを受ける床（背景は透明のまま。Cycles）"""
    bpy.ops.mesh.primitive_plane_add(size=float(size), location=(0, 0, z))
    o = bpy.context.object
    o.data.materials.append(material('floor', color, metal, rough))
    if catcher:
        o.is_shadow_catcher = True
    return o
