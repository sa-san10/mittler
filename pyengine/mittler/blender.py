"""Blender の 3D レイヤー（2026-11-13、3D 強化）。タイムラインのエフェクトのクリップ `blender3d`（effects_lib/common/blender3d.py）が使う。

クリップ（effect: "blender3d"）の params：
  scene（作品の root からの相対：bpy のスクリプト `3d/<名前>.py` か `.blend`）・args（スクリプトに渡す dict）・engine（CYCLES／EEVEE）・samples・
  draft_samples・draft_scale（プレビューのドラフトの品質）・device（auto／OPTIX／CUDA／HIP／CPU）・denoise・transparent（背景を透明に）・
  view（色の見え方：scene＝場面のまま・Standard・AgX）・blend（over／add／screen）・opacity
描き方：
- コマごとに Blender で RGBA の PNG を描いて、作品の `work/3d/<クリップの id>/<鍵>/<コマ>.png` にためる。鍵は場面のファイル（とスクリプトの道具）の中身・
  args・大きさ・fps・品質・Blender の版・この仕組みの版から作る（どれか変われば別の鍵＝描き直す。数の書き方 3 と 3.0 は同じ値とみなす）。コマはクリップの頭からの番号（クリップを動かしても使い回す）。
  エンジンはためた絵を読んで、ほかのレイヤーと重ねる（'v7' 段。重ね順はトラックの順）。
- 書き出し（`mittler video`・🏆 マスター）：区間に分けて描き始める前に、範囲のコマを Blender 1 回でまとめて描く（prepare。Blender を 1 コマごとに起こさない）。
  並列の区間は、ためた絵を読むだけ（取り合わない。足りないコマがあっても、鍵のフォルダの錠で 1 本ずつ描く）。
- 静止画（`mittler stills`）・📷：足りないコマは、その場で本番の品質で描く。
- プレビュー（描画サーバーの JPEG）：本番の品質の絵がためてあればそれ、無ければドラフトの品質（少ないサンプル・小さい大きさ）で 1 枚だけ描く（数秒かかる）。
  先読みでは Blender を起こさない（足りなければ先読みをやめる）。だから本番の品質の絵がたまるまでは、プレビューと書き出しの絵は品質が違う
  （本番の品質で描けば、プレビュー・静止画・書き出しは同じファイルを読むので同じ絵）。
- Cycles を GPU で描くと、同じ設定でも描き直すたびに数画素が 1〜6 違う（作者の PC の RTX 3090 で確かめた）。だから「同じ時刻は同じ絵」は、ためた絵を使い回すことで守る。
- Blender の場所：環境変数 MITTLER_BLENDER（編集画面のサーバーが設定 mittler.blender.path から入れる）→ 既定 BLENDER_DEFAULT → PATH の blender。
- 止める：書き出しの「止める」・サーバーを閉じると、Blender も止まる（procs.kill_tree。描きかけのコマは残さない：一時の名前で書いてから置きかえる）。
"""
import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from .defaults import author
from .names import cache_root

VERSION = 1                                        # ためる絵の形・描き方を変えたら上げる（鍵に入る）
BLENDER_DEFAULT = author('blenderPath', '')          # 作者の PC に置いた場所（server/defaults.author.json。無ければ空＝PATH の blender。docs/インストールガイド.md の 12）
HERE = Path(__file__).resolve().parent
RUNNER = HERE / 'blender_runner.py'                 # Blender の中で動く
KIT = HERE / 'blender_kit.py'                       # 場面のスクリプトが使う道具（Blender の中で `import mittler_bpy`）
DEFAULTS = {'scene': '3d/scene.py', 'args': {}, 'engine': 'CYCLES', 'samples': 64, 'draft_samples': 8, 'draft_scale': 0.5, 'device': 'auto',
            'denoise': True, 'transparent': True, 'view': 'scene', 'blend': 'over', 'opacity': 1.0}
STALL = 600                                          # 新しいコマが出ないまま、これだけ秒がたったら止める


def _t(key, **kw):
    from .i18n import t
    return t(key, **kw)


class BlenderError(RuntimeError):
    pass


def find():
    """blender.exe の場所。無ければ BlenderError（どこを見たか）。MITTLER_BLENDER（設定 mittler.blender.path・--blender）を書いたのに
    そこに無いときは、既定や PATH に替えずに止まる（書きまちがいのまま、黙ってほかの Blender で描かない）"""
    tried = []
    env = os.environ.get('MITTLER_BLENDER', '').strip()
    if env:
        if os.path.isfile(env):
            return env
        raise BlenderError(_t('bl.noBlender', where=env))
    for p in [BLENDER_DEFAULT]:
        tried.append(p)
        if p and os.path.isfile(p):
            return p
    w = shutil.which('blender')
    if w:
        return w
    tried.append('PATH の blender')
    raise BlenderError(_t('bl.noBlender', where=' / '.join(tried)))


_VER = {}


def version(exe):
    """Blender の版の 1 行（'Blender 5.2.4 LTS' など。鍵に入る）"""
    st = os.stat(exe)
    k = (exe, st.st_mtime_ns, st.st_size)
    if k not in _VER:
        r = subprocess.run([exe, '-b', '--factory-startup', '--version'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
        line = next((ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith('Blender')), '')
        if not line:
            raise BlenderError(_t('bl.fail', err=(r.stdout + r.stderr)[-400:]))
        _VER[k] = line
    return _VER[k]


_SHA = {}


def _sha(p):
    """ファイルの中身の SHA-1（更新時刻と大きさが同じあいだは覚えておく。.blend が大きくても毎コマ読まない）"""
    st = os.stat(p)
    k = (str(p), st.st_mtime_ns, st.st_size)
    if k not in _SHA:
        h = hashlib.sha1()
        with open(p, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''):
                h.update(b)
        _SHA[k] = h.hexdigest()
    return _SHA[k]


def params(clip):
    p = dict(DEFAULTS)
    p.update(clip.get('params') or {})
    return p


def spec(eng, clip, quality):
    """描き方（Blender に渡すもの）と、ためるフォルダ。quality：'full'（本番）・'draft'（プレビューの下描き）"""
    p = params(clip)
    scene = eng.root / str(p['scene'])
    if not scene.is_file():
        raise BlenderError(_t('bl.noScene', path=str(p['scene'])))
    exe = find()
    W, H = int(eng.W), int(eng.H)
    if quality == 'draft':
        s = min(1.0, max(0.1, float(p.get('draft_scale') or 0.5)))
        W, H = max(2, int(W * s) // 2 * 2), max(2, int(H * s) // 2 * 2)
        samples = int(p.get('draft_samples') or 8)
    else:
        samples = int(p.get('samples') or 64)
    args = dict(p.get('args') or {})
    args.setdefault('dur', float(clip['dur']))  # クリップの長さ（スクリプトが args に dur を書いていなければ。カメラの回り込みの割り振りなど）
    sp = {
        'v': VERSION, 'blender': version(exe), 'runner': _sha(RUNNER), 'kit': _sha(KIT),
        'scene': str(p['scene']).replace('\\', '/'), 'scene_sha': _sha(scene), 'kind': 'blend' if scene.suffix.lower() == '.blend' else 'py',
        'args': args, 'W': W, 'H': H, 'fps': eng.fps, 'engine': str(p['engine']).upper(), 'samples': samples,
        'device': str(p.get('device') or 'auto').upper(), 'denoise': bool(p.get('denoise')), 'transparent': bool(p.get('transparent', True)),
        'view': str(p.get('view') or 'scene'), 'quality': quality,
    }
    base = cache_root(eng.dir) / '3d' / _safe(clip.get('id', 'clip'))  # ふつうは作品の work/3d（names.py の cache_root）
    d = base / _key(_canon(sp))
    if not d.exists():  # 前の鍵（数の書き方 3 と 3.0 で変わっていた）でためた絵があれば、新しい鍵の名前に付けかえて使い回す
        old = base / _key(sp)
        if old != d and old.exists():
            try:
                os.replace(old, d)
            except OSError:  # 描いている最中などで動かせない：今回は前のフォルダのまま
                d = old
    sp.update(exe=exe, scene_path=str(scene), root=str(eng.root), out=str(d), kit_dir=kit_dir())
    return sp, d


def _key(sp):
    return hashlib.sha1(json.dumps(sp, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]


def _canon(v):
    """鍵のための形：整数の値の小数（3.0）を整数（3）に。タイムラインを編集画面（JS）が保存すると 3.0 が 3 になり、
    Python が書くと 3.0 のままなので、同じ値でも鍵が変わって全部描き直していた（2026-11-16）。Blender に渡す値はそのまま"""
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def kit_dir():
    """Blender に渡す道具（blender_kit.py）のフォルダ：一時フォルダの写し（<一時>/mittler_bpy/<中身の SHA>/）。2026-11-13 パッケージ化。
    Blender の中の python は環境変数 PYTHONDONTWRITEBYTECODE を読まない（既定で環境を見ない）ので、ここ（Mittler の置き場。配布版は拡張のフォルダ＝読むだけ）を
    渡すと、そこに __pycache__ を書く。写しは中身が同じなので絵も鍵（spec の 'kit' は元の中身の SHA）も変わらない。写せなければ前と同じくここ"""
    try:
        d = Path(tempfile.gettempdir()) / 'mittler_bpy' / _sha(KIT)[:16]
        if not (d / KIT.name).is_file():
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / (KIT.name + f'.{os.getpid()}.part')
            shutil.copyfile(KIT, tmp)
            os.replace(tmp, d / KIT.name)
        return str(d)
    except OSError:
        return str(HERE)


def _safe(s):
    """クリップの id → フォルダの名前（ASCII の英数字と - _ のほかは _。server.js の /api/blender/clear と同じ決まり）"""
    return ''.join(c if ((c.isascii() and c.isalnum()) or c in '-_') else '_' for c in str(s))[:80] or 'clip'


def frame_no(eng, clip, t):
    """クリップの頭から数えたコマ番号（タイムラインのコマ n の時刻 t＝n / fps）"""
    return int(round((t - float(clip['start'])) * eng.fps))


def frame_file(d, k):
    return Path(d) / f'{k:06d}.png'


_LIVE = set()  # 動いている Blender（このプロセスが終わるときに止める：描画サーバーが /quit で止まったとき、描きかけの Blender を残さない）


@atexit.register
def kill_all():
    from .procs import kill_tree
    for pr in list(_LIVE):
        try:
            kill_tree(pr)
        except Exception:  # noqa: BLE001
            pass


class _Lock:
    """鍵のフォルダの錠（同じフォルダを 2 本の Blender で描かない。並列の区間・プレビューと書き出し）"""
    def __init__(self, d):
        self.f = None
        self.p = Path(d) / '.lock'

    def __enter__(self):
        import msvcrt
        self.p.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.p, 'a+b')
        while True:
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                time.sleep(0.2)

    def __exit__(self, *a):
        import msvcrt
        try:
            self.f.seek(0)
            msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.f.close()


def render_frames(sp, d, ks, check=None, progress=None):
    """コマ ks（クリップの頭からの番号）を Blender 1 回で描いて d にためる。ためてあるコマは飛ばす。
    check()：途中で呼ぶ（例外を投げると Blender を止めて、その例外を投げ直す）。progress(できた数, 全部)"""
    d = Path(d)
    with _Lock(d):
        todo = sorted(set(k for k in ks if not frame_file(d, k).exists()))
        if not todo:
            return 0
        d.mkdir(parents=True, exist_ok=True)
        job = dict(sp, frames=[[k, k / sp['fps']] for k in todo])
        jf = d / f'job_{os.getpid()}_{threading.get_ident()}.json'
        jf.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
        (d / 'spec.json').write_text(json.dumps({k: v for k, v in sp.items() if k not in ('exe',)}, ensure_ascii=False, indent=1), encoding='utf-8')
        cmd = [sp['exe'], '-b'] + ([sp['scene_path']] if sp['kind'] == 'blend' else ['--factory-startup']) + \
              ['--python-exit-code', '3', '--python', str(RUNNER), '--', str(jf)]
        from .procs import kill_tree
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=sp['root'], text=True, encoding='utf-8', errors='replace',
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        _LIVE.add(pr)
        tail, state = [], {'done': 0, 'last': time.time()}

        def reader():
            for ln in pr.stdout:
                ln = ln.rstrip()
                if ln.startswith('MITTLER_FRAME '):
                    state['done'] += 1
                    state['last'] = time.time()
                    state.setdefault('log', []).append(ln)
                    del state['log'][:-200]
                elif ln.startswith('MITTLER_DEVICE '):
                    state['dev'] = ln
                else:
                    tail.append(ln)
                    del tail[:-40]
        th = threading.Thread(target=reader, daemon=True)
        th.start()
        try:
            while pr.poll() is None:
                if check is not None:
                    check()
                if progress is not None:
                    progress(state['done'], len(todo))
                if time.time() - state['last'] > STALL:
                    raise BlenderError(_t('bl.fail', err=f'{STALL} 秒のあいだ新しいコマが出ない'))
                time.sleep(0.2)
        except BaseException:
            kill_tree(pr)
            pr.wait()
            raise
        finally:
            _LIVE.discard(pr)
            th.join(timeout=5)
            jf.unlink(missing_ok=True)
        if progress is not None:
            progress(state['done'], len(todo))
        try:  # Blender の出力の終わり（どのデバイスで描いたか MITTLER_DEVICE・1 コマの秒 MITTLER_FRAME）を残す（確かめ用。上書き）
            (d / 'render.log').write_text('\n'.join([state.get('dev', 'MITTLER_DEVICE ?')] + state.get('log', []) + tail[-40:]) + '\n', encoding='utf-8')
        except OSError:
            pass
        missing = [k for k in todo if not frame_file(d, k).exists()]
        if pr.returncode or missing:
            raise BlenderError(_t('bl.fail', err=f'終了コード {pr.returncode}・描けなかったコマ {len(missing)}\n' + '\n'.join(tail[-25:])))
        return len(todo)


def _read(ctx, path, W, H):
    from PIL import Image
    box = ctx.cache.setdefault('blender.frames', {})
    k = (str(path), W, H)
    got = box.get(k)
    if got is None:
        im = Image.open(path).convert('RGBA')
        if im.size != (W, H):  # ドラフト（小さく描いた絵）を画面の大きさに
            im = im.resize((W, H), Image.BILINEAR)
        got = np.asarray(im)
        box[k] = got
        while len(box) > 12:
            box.pop(next(iter(box)))
    return got


def layer(ctx, f, clip):
    """'v7' 段：このコマの Blender の絵を f に重ねる（effects_lib/common/blender3d.py の apply）"""
    eng = ctx.eng
    p = params(clip)
    k = frame_no(eng, clip, ctx.t)
    sp, d = spec(eng, clip, 'full')
    path = frame_file(d, k)
    if not path.exists():
        if getattr(eng, 'preview', False) or eng.draft:  # プレビュー・ドラフトの書き出し：下描きの品質（プレビューの先読みでは描かない）
            sd, dd = spec(eng, clip, 'draft')
            dpath = frame_file(dd, k)
            if not dpath.exists():
                if eng.check is not None:  # 先読みの途中：Blender を起こさずに先読みをやめる
                    from .engine import Interrupted
                    raise Interrupted()
                print(f'[blender] プレビューの下描き {clip.get("id")} コマ {k}', file=sys.stderr, flush=True)
                render_frames(sd, dd, [k])
            path = dpath
            eng.used_draft = True  # このコマは下描き（fcache：ディスクにためない）
        else:
            render_frames(sp, d, [k])
    img = _read(ctx, path, ctx.W, ctx.H)
    a = img[..., 3:4].astype(np.float32) * (float(p.get('opacity', 1.0)) / 255.0)
    rgb = img[..., :3].astype(np.float32)
    mode = p.get('blend', 'over')
    if mode == 'add':
        f += rgb * a
    elif mode == 'screen':
        fc = np.clip(f, 0, 255)
        f[:] = fc + (rgb * a) * (1 - fc / 255.0)
    else:
        f *= (1 - a)
        f += rgb * a
    return f


def prepare(eng, clip, n0, n1, step=1, check=None, progress=None):
    """書き出しの前に、タイムラインのコマ [n0, n1)（step おき）のうち、このクリップがかかるコマを本番の品質でまとめて描く"""
    s, e = float(clip['start']), float(clip['start']) + float(clip['dur'])
    ks = []
    for n in range(n0, n1, max(1, int(step))):
        t = n / eng.fps
        if s <= t < e:
            ks.append(frame_no(eng, clip, t))
    if not ks:
        return 0
    sp, d = spec(eng, clip, 'full')
    if eng.draft:  # ドラフトの書き出し：本番の絵がためてあるコマはそれを使い、無いコマだけ下描きの品質で
        ks = [k for k in ks if not frame_file(d, k).exists()]
        sp, d = spec(eng, clip, 'draft')
    return render_frames(sp, d, ks, check=check, progress=progress)
