"""Blender の 3D（2026-11-13、3D 強化）。Blender で描いた 3D の場面を、このトラックの位置に重ねる（反射・影・ガラス・金属・被写界深度など、本格的な 3D）。
場面は作品の中のファイル：bpy のスクリプト `3d/<名前>.py`（ひな形は Mittler の templates/3d/。build(scene, args) で組み、frame(scene, t, args) でコマごとに動かす）か `.blend`。
描いた絵は作品の `work/3d/<クリップの id>/` にためて使い回す（場面・args・大きさ・fps・品質・Blender の版が変わると描き直す）。
書き出しは、区間に分ける前に範囲のコマを Blender でまとめて描く。プレビューは、ためた本番の絵が無ければ下描き（少ないサンプル・小さい大きさ）を 1 枚描く（数秒）。
params：scene（場面のファイル）, args（スクリプトに渡す JSON）, engine（CYCLES／EEVEE）, samples（本番のサンプル数）, draft_samples・draft_scale（プレビューの下描き）,
  device（auto＝OPTIX→CUDA→HIP→CPU）, denoise, transparent（背景を透明に）, view（色の見え方。scene＝場面のまま）, blend（over・add・screen）, opacity
Blender の場所は設定 mittler.blender.path（環境変数 MITTLER_BLENDER）。無い PC では「Blender が見つからない」で止まる。くわしくは pyengine/mittler/blender.py。"""
from mittler import blender

STAGE = 'v7'
DOC_EN = """Blender 3D. Composites a 3D scene rendered by Blender at this track's position (real 3D: reflections, shadows, glass, metal, depth of field).
The scene is a file in the project: a bpy script `3d/<name>.py` (templates in Mittler's templates/3d/: build(scene, args) builds it, frame(scene, t, args) moves it per frame) or a `.blend`.
Rendered frames are kept in the project's `work/3d/<clip id>/` and reused (they re-render when the scene, args, size, fps, quality or Blender version changes).
Export renders the range's frames with Blender in one go before splitting into segments. The preview renders one draft frame (few samples, smaller) when no final frame is kept (takes seconds).
params: scene, args (JSON passed to the script), engine (CYCLES / EEVEE), samples, draft_samples / draft_scale (preview draft),
  device (auto = OPTIX → CUDA → HIP → CPU), denoise, transparent (transparent background), view (color view; scene = keep), blend (over / add / screen), opacity
Blender's location: the mittler.blender.path setting (MITTLER_BLENDER). Without Blender, rendering stops with "Blender not found"."""
META = {
    'label': 'Blender の 3D', 'label_en': 'Blender 3D', 'window': {'clip': True}, 'scale_aware': True, 'blender': True,
    'params': {
        'scene': {'type': 'text'}, 'args': {'type': 'json'},
        'engine': {'type': 'choice', 'choices': ['CYCLES', 'EEVEE']},
        'samples': {'type': 'int', 'min': 1, 'max': 4096}, 'draft_samples': {'type': 'int', 'min': 1, 'max': 512},
        'draft_scale': {'type': 'number', 'min': 0.1, 'max': 1, 'step': 0.05},
        'device': {'type': 'choice', 'choices': ['auto', 'OPTIX', 'CUDA', 'HIP', 'CPU']},
        'denoise': {'type': 'bool'}, 'transparent': {'type': 'bool'},
        'view': {'type': 'choice', 'choices': ['scene', 'Standard', 'AgX']},
        'blend': {'type': 'choice', 'choices': ['over', 'add', 'screen']},
        'opacity': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01},
    },
    # 編集画面で置くときの値と長さ（場面はひな形のロゴ。「作品に入れる」で作品の 3d/logo.py に写る）
    'defaults': {'scene': '3d/logo.py', 'args': {'text': 'Mittler'}, 'engine': 'CYCLES', 'samples': 64, 'draft_samples': 8, 'draft_scale': 0.5,
                 'device': 'auto', 'denoise': True, 'transparent': True, 'view': 'scene', 'blend': 'over', 'opacity': 1.0},
    'dur': 5,
}


def apply(ctx, f, clip):
    return blender.layer(ctx, f, clip)


def prepare(eng, clip, n0, n1, step=1, check=None, progress=None):
    """書き出しの前に呼ばれる（pyengine/mittler/__main__.py）：範囲のコマを Blender でまとめて描いてためる"""
    return blender.prepare(eng, clip, n0, n1, step, check, progress)
