"""Blender の中で動く係（pyengine/mittler/blender.py が `blender -b … --python blender_runner.py -- <job.json>` で起こす）。

job.json：kind（'py'＝bpy のスクリプト・'blend'＝.blend のファイル）・scene_path・args・W・H・fps・engine・samples・device・denoise・transparent・view・
          out（ためるフォルダ）・frames（[[コマ番号, クリップの頭からの秒], …]）・kit_dir
- 'py'：まっさらの場面（--factory-startup）に、スクリプトの build(scene, args) で場面を組み、コマごとに frame(scene, t, args) を呼んでから描く。
  スクリプトは `import mittler_bpy as mb` で道具（blender_kit.py）が使える。場面の fps はタイムラインの fps にして、t 秒のところ（frame_set）にもする
  （キーフレームで動かしてもよい）。
- 'blend'：そのファイルの場面を、t 秒のところ（場面の frame_start ＋ t × 場面の fps）で描く。
- 描くたびに `MITTLER_FRAME <番号>` を出す。絵は一時の名前で書いてから置きかえる（止められても描きかけを残さない）。
"""
import importlib.util
import json
import math
import os
import sys
import time

import bpy

job = json.load(open(sys.argv[sys.argv.index('--') + 1], encoding='utf-8'))
sys.path.insert(0, job['kit_dir'])
spec = importlib.util.spec_from_file_location('mittler_bpy', os.path.join(job['kit_dir'], 'blender_kit.py'))
kit = importlib.util.module_from_spec(spec)
sys.modules['mittler_bpy'] = kit
spec.loader.exec_module(kit)

scene = bpy.context.scene
args = job.get('args') or {}
mod = None
if job['kind'] == 'py':
    kit.clear()
    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = (int(job['fps']), 1.0) if float(job['fps']).is_integer() else (round(job['fps'] * 1000), 1000.0)
    sp = importlib.util.spec_from_file_location('mittler_scene', job['scene_path'])
    mod = importlib.util.module_from_spec(sp)
    sys.modules['mittler_scene'] = mod
    sp.loader.exec_module(mod)
    if hasattr(mod, 'build'):
        mod.build(scene, args)

r = scene.render
r.resolution_x, r.resolution_y, r.resolution_percentage = int(job['W']), int(job['H']), 100
r.film_transparent = bool(job['transparent'])
r.image_settings.file_format = 'PNG'
r.image_settings.color_mode = 'RGBA'
r.image_settings.color_depth = '8'
r.image_settings.compression = 15
r.use_stamp = False
if job.get('view') in ('Standard', 'AgX', 'Filmic'):
    try:
        scene.view_settings.view_transform = job['view']
    except Exception as e:  # noqa: BLE001
        print('view_transform', e)
engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
if job['engine'] == 'EEVEE':
    r.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in engines else 'BLENDER_EEVEE'
    try:
        scene.eevee.taa_render_samples = int(job['samples'])
    except Exception:  # noqa: BLE001
        pass
else:
    r.engine = 'CYCLES'
    cy = scene.cycles
    cy.samples = int(job['samples'])
    cy.seed = 0
    cy.use_animated_seed = False
    cy.use_denoising = bool(job['denoise'])
    dev = job.get('device', 'AUTO')
    used = 'CPU'
    if dev != 'CPU':
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for ty in ([dev] if dev not in ('AUTO', '') else ['OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL']):
            try:
                prefs.compute_device_type = ty
                prefs.get_devices()
            except Exception:  # noqa: BLE001
                continue
            gs = [d for d in prefs.devices if d.type == ty]
            if gs:
                for d in prefs.devices:
                    d.use = d.type == ty
                cy.device = 'GPU'
                used = ty
                break
    if used == 'CPU':
        cy.device = 'CPU'
    print('MITTLER_DEVICE', used, flush=True)

fps = scene.render.fps / scene.render.fps_base
f0 = scene.frame_start
out = job['out']
os.makedirs(out, exist_ok=True)
for k, t in job['frames']:
    fr = f0 + t * fps if job['kind'] == 'blend' else 1 + t * fps
    i = math.floor(fr + 1e-9)
    scene.frame_set(i, subframe=max(0.0, fr - i))
    if mod is not None and hasattr(mod, 'frame'):
        mod.frame(scene, float(t), args)
    final = os.path.join(out, f'{int(k):06d}.png')
    tmp = os.path.join(out, f'_tmp_{os.getpid()}_{int(k):06d}.png')
    r.filepath = tmp
    t0 = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    os.replace(tmp, final)
    print('MITTLER_FRAME', k, round(time.perf_counter() - t0, 3), flush=True)
