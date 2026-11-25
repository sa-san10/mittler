"""描いた絵をコマごとにディスクにためる（2026-11-16）。書き出したあとのプレビューや、Blender の描画が終わった区間を、
毎回描き直さずにためた絵で出すため。捨てる範囲は「直したクリップの区間だけ」。

- ためる：書き出しの区間（__main__.segment）・編集画面のプレビューの描画サーバー（serve.py）・裏で先に描く係（bake.py）が、本番の品質で描いたコマを
  作品の `work/cache/frames/<鍵の頭 2 字>/<鍵>.png`（等倍・劣化なし）と `<鍵>.p.jpg`（プレビュー用の小さな JPEG）に。
  読む：描画サーバー（描く前に同じ鍵の絵があればそれ）・書き出し（差分書き出し：同じ鍵の PNG があれば描かずに使う。絵は描いたものとビット単位で同じ）・
  編集画面の ▶（ためた区間は小さな JPEG を流す。サーバーの /api/cframe）。
- 鍵（key）は、そのコマの絵に効くものから作る。どれかが変われば別の鍵（＝描き直す）。ほかの区間の直しでは変わらない：
  - 全体：大きさ・fps・長さ・settings（cache を除く）・meta（拍・カット・区切り…）・映像のトラックの並び・タイムラインの頭の値（tracks・preview のほか）。
  - そのコマの前後 PAD 秒にかかるクリップ（映像・🎬・エフェクト・字幕・音。トラックの id と 👁 も）の中身と、それが指すファイル・フォルダの更新時刻。
    カットがあれば、そのカットと前後のカットの映像のクリップも（切り替えが前後の場面を描くため）。
  - かかっているエフェクトのコード（effects/<名前>.py と、それが import する作品のエフェクト）と、effects/ の下のフォルダ（_lib など）の全部のファイル。
    エフェクトのコードが `clips_of('名前')` を読む・`CACHE_READS = ['名前', …]` と書いてあるなら、その名前のクリップ全部も。
    ほかの時刻のカメラ（`camera_at`）を読む・`CACHE = 'all'` と書いてあるなら、映像に効くクリップ全部を鍵に入れる（広めに捨てる）。
    タイムラインそのもの（`.tl`）・`clips_of(変数)` は、そのコマの時刻のクリップを探すのがふつうなので、前後 PAD 秒のクリップで足りるとみなす。
    `source_time`（コマ止めなど）を持つエフェクトがあれば、映像のクリップ全部も。
  - Blender の 3D のクリップは、そのコマのためた絵のファイルの更新時刻（描き直したら変わる）。
- ためないもの：ドラフト（ctx.draft）・Blender の下描きを使ったコマ・マスター（倍率・fps・素材の差し替え）・書き出しで字幕（ASS）を後で焼く区間・
  settings.cache.frames が false の作品。上限は settings.cache.frames_gb（既定 FRAMES_GB。こえたら古いものから消す）。
- エンジンの描き方を変えて絵が変わるときは VERSION を上げる（全部描き直しになる）。
"""
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

import numpy as np

from .names import cache_root

VERSION = 2        # 2：劣化なしの PNG（書き出しにも使う）＋プレビュー用の小さな JPEG（2026-11-16。1 は等倍の JPEG）
PAD = 2.0          # そのコマの前後、これだけ秒の中にかかるクリップを鍵に入れる（前後のコマを読むエフェクトのため）
PREVIEW_W, PREVIEW_Q = 960, 85   # プレビュー用の JPEG の幅の上限と品質
FRAMES_GB = 40     # ためる上限の既定（settings.cache.frames_gb）。FHD の PNG で 1 コマ 3〜5 MB（3 分の作品で 20〜25 GB）
KEEP_FREE_GB = 20  # ディスクの空きがこれを切りそうなら、上限を半分にして消す
VISUAL = ('video', 'plan', 'effect', 'subtitle', 'tts', 'audio')
SOUND = ('tts', 'audio')  # 音のクリップは絵に効かない（タイムラインそのものを読むエフェクトのときだけ鍵に入れる）
_lock = threading.Lock()


def canon(v):
    """鍵のための形：整数の値の小数（3.0）を整数（3）に（編集画面の JS が保存すると 3.0 が 3 になるため。blender._canon と同じ）"""
    if isinstance(v, dict):
        return {k: canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [canon(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _h(obj):
    return hashlib.sha1(json.dumps(canon(obj), sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()


def enabled(eng, draft_ok=False):
    """この描き方の絵をためてよいか（本番の品質・タイムラインの大きさと fps・素材の差し替えなし）。draft_ok：ドラフトでも（読むだけ）"""
    if (eng.settings.get('cache') or {}).get('frames') is False:
        return False
    return ((draft_ok or not eng.draft) and eng.scale == 1 and eng.fps == eng.tl_fps and not eng.src_map and not eng.clip_src_map)


def folder(eng):
    return cache_root(eng.dir) / 'cache' / 'frames'  # ふつうは作品の work/。PC の設定 mittler.cache.dir があればその下（names.py）


def _stat(p):
    try:
        st = os.stat(p)
        return [st.st_mtime_ns, st.st_size]
    except OSError:
        return None


class _Index:
    """タイムラインを読んだときに 1 回作る（Engine.load のたびに作り直す）"""

    def __init__(self, eng):
        self.eng = eng
        tl = eng.tl
        top = {k: v for k, v in tl.items() if k not in ('tracks', 'preview', 'settings')}
        settings = {k: v for k, v in (tl.get('settings') or {}).items() if k != 'cache'}
        tracks = [tr for tr in tl.get('tracks', []) if tr.get('kind') in VISUAL]
        order = [[tr.get('id'), tr.get('kind'), bool(tr.get('hidden'))] for tr in tracks if tr.get('kind') not in SOUND]
        self.gfiles = sorted(self._files({'top': top, 'settings': settings}))
        self.gsig = _h({'v': VERSION, 'top': top, 'settings': settings, 'order': order})
        self.clips = []  # (start, end, kind, effect, cut, hash, files)
        for tr in tracks:
            if tr.get('hidden'):
                continue
            for c in tr.get('clips', []):
                try:
                    s, d = float(c.get('start', 0)), float(c.get('dur', 0))
                except (TypeError, ValueError):
                    s, d = 0.0, float('inf')
                eff = c.get('effect') or ('subtitle' if tr.get('kind') == 'subtitle' else None)
                self.clips.append((s, s + d, tr.get('kind'), eff, c.get('cut'), _h({'track': tr.get('id'), 'clip': c}), sorted(self._files(c))))
        self.all_sig = _h(sorted(x[5] for x in self.clips))
        self.all_files = sorted({f for x in self.clips for f in x[6]})
        self._fx = {}
        fx = eng.dir / 'effects'
        self.mods = {}  # 作品のエフェクトの下のフォルダの .py（_lib など）：名前 → パス
        self.lib = []
        if fx.is_dir():
            for p in sorted(fx.rglob('*')):
                if '__pycache__' in p.parts or not p.is_file():
                    continue
                if p.parent != fx:
                    self.lib.append(str(p))
                    if p.suffix == '.py':
                        self.mods.setdefault(p.stem, p)

    def _files(self, v):
        """値の中の、作品の root の下に実在するファイル・フォルダを指す文字列（serve.media_files の walk と同じ考え。フォルダはマスクの置き場など）"""
        out, root = set(), self.eng.root
        top = {str(root.resolve())} | {str(q) for q in root.resolve().parents}  # 作品の根とその上のフォルダは入れない（タイムラインの "root": "." など。
        # フォルダの更新時刻は、書き出しのファイルができるだけで変わる）

        def walk(x, depth=0):
            if isinstance(x, str):
                if 0 < len(x) < 300 and '\n' not in x and ('.' in x or '/' in x):
                    try:
                        p = root / x
                        if p.exists() and not (p.is_dir() and str(p.resolve()) in top):
                            out.add(str(p))
                            if p.suffix.lower() in ('.html', '.htm') and p.is_file():  # HTML のレイヤーのページ：フォルダの中身と vendor/（htmllayer.page_files）
                                from .htmllayer import page_files
                                out.update(str(q) for q in page_files(p))
                    except (OSError, ValueError):
                        pass
            elif depth < 8 and isinstance(x, dict):
                for y in x.values():
                    walk(y, depth + 1)
            elif depth < 8 and isinstance(x, list):
                for y in x[:500]:
                    walk(y, depth + 1)
        walk(v)
        return out

    def fx(self, name):
        """エフェクトのコードの印と、読むもの：(印, 'all'＝映像に効くもの全部 | None, clips_of で読む名前の集まり | '*', source_time を持つか)"""
        p = self.eng.dir / 'effects' / f'{name}.py'
        got = self._fx.get(name)
        if got and all(_stat(q) == s for q, s in got[0]):  # 読み込む部品も含めて変わっていない
            return got[1]
        seen, todo, sigs, src = set(), [p], [], []
        while todo:
            q = todo.pop()
            if str(q) in seen:
                continue
            seen.add(str(q))
            sigs.append([str(q), _stat(q)])
            try:
                s = q.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            src.append(s)
            for m in re.findall(r'^\s*(?:from|import)\s+([A-Za-z_]\w*)', s, re.M):
                for cand in (self.eng.dir / 'effects' / f'{m}.py', self.mods.get(m)):
                    if cand is not None and Path(cand).is_file():
                        todo.append(Path(cand))
        text = '\n'.join(src)
        # ほかの時刻のカメラ（camera_at）を読む・エフェクトが CACHE = 'all' と書いた：映像に効くもの全部。
        # タイムラインそのもの（.tl）・clips_of(変数)・scene_frame は、そのコマの時刻のクリップを探すのがふつうなので、前後 PAD 秒のクリップで足りるとみなす
        # （遠くのクリップを読むなら、エフェクトに CACHE_READS = ['名前', …] か CACHE = 'all' を書く。docs/エフェクトの書き方.md）
        wide = 'all' if re.search(r'camera_at|^CACHE\s*=\s*[\'"]all[\'"]', text, re.M) else None
        names = set(re.findall(r"clips_of\(\s*['\"]([\w-]+)['\"]", text))
        for m in re.findall(r'^CACHE_READS\s*=\s*[\[(]([^\])]*)[\])]', text, re.M):
            names.update(re.findall(r"['\"]([\w-]+)['\"]", m))
        info = (_h(sorted(sigs, key=lambda x: x[0])), wide, names, bool(re.search(r'def\s+source_time\b', text)))
        self._fx[name] = ([(q, s) for q, s in sigs], info)
        return info

    def key(self, t):
        eng = self.eng
        w0, w1 = t - PAD, t + PAD
        sel = [x for x in self.clips if x[0] < w1 and x[1] > w0 and x[2] not in SOUND]
        if eng.cuts:  # そのカットと前後のカットの映像（切り替え・コマ止めがカットの頭まで戻る）
            labels = [str(c['label']) for c in eng.cuts]
            i = labels.index(str(eng.cut_at(t)['label'])) if str(eng.cut_at(t)['label']) in labels else 0
            near = set(labels[max(0, i - 1):i + 2])
            sel += [x for x in self.clips if x[2] in ('video', 'plan') and x[4] is not None and str(x[4]) in near]
        wide, more, codes = False, set(), []
        effects = {x[3] for x in sel if x[3]}
        for name in sorted(effects):
            code, w, names, st = self.fx(name)
            codes.append([name, code])
            if name == 'html':  # HTML のレイヤーの下地（時刻と乱数を決める。pyengine/mittler/html_runtime.js）
                from .htmllayer import RUNTIME
                codes.append(['html_runtime', _stat(RUNTIME)])
            if w or names == '*':
                wide = wide or bool(w)
                if names == '*':
                    more.update(x[3] for x in self.clips if x[3])
            else:
                more.update(names)
            if st:  # コマ止め（source_time）：映像の時刻が前に戻る
                sel += [x for x in self.clips if x[2] in ('video', 'plan')]
        for name in sorted(more - effects):  # clips_of で読むほかのエフェクトのクリップ（とそのコード）
            sel += [x for x in self.clips if x[3] == name]
            if (eng.dir / 'effects' / f'{name}.py').is_file():
                codes.append([name, self.fx(name)[0]])
        if wide:
            hashes, files = [self.all_sig], self.all_files
        else:
            hashes = sorted({x[5] for x in sel})
            files = sorted({f for x in sel for f in x[6]})
        bl = self._blender(t)
        if bl is False:
            return None
        return _h({'n': int(round(t * eng.fps)), 'g': self.gsig, 'c': hashes, 'fx': codes, 'lib': [[p, _stat(p)] for p in self.lib],
                   'f': [[p, _stat(p)] for p in list(self.gfiles) + list(files)], 'bl': bl})

    def _blender(self, t):
        """そのコマにかかる Blender の 3D のクリップの、ためた絵のファイルの更新時刻（描き直したら変わる）。描き方が決められなければ False（ためない）"""
        out = []
        for c in self.eng.effect_clips:
            if c.get('effect') != 'blender3d' or not (float(c['start']) <= t < float(c['start']) + float(c['dur'])):
                continue
            try:
                from . import blender
                sp, d = blender.spec(self.eng, c, 'full')
                f = blender.frame_file(d, blender.frame_no(self.eng, c, t))
                out.append([c.get('id'), d.name, _stat(f)])
            except Exception:  # noqa: BLE001  Blender が無いなど
                return False
        return out


def key(eng, t, draft_ok=False):
    """時刻 t のコマの鍵（ためない描き方なら None）。draft_ok：ドラフトの描き方でも鍵を作る（ためた本番の絵を読むだけ。ドラフトの書き出し・プレビュー）"""
    if not enabled(eng, draft_ok):
        return None
    idx = getattr(eng, '_fcache_idx', None)
    if idx is None or idx.eng is not eng or getattr(eng, '_fcache_tl', None) is not eng.tl:
        idx = _Index(eng)
        eng._fcache_idx, eng._fcache_tl = idx, eng.tl
    try:
        return idx.key(t)
    except Exception:  # noqa: BLE001  鍵が作れない（読めないエフェクトなど）：ためない
        return None


def path_of(eng, k):
    """劣化なしの絵（PNG。書き出しにも使う）"""
    return folder(eng) / k[:2] / f'{k}.png'


def preview_of(eng, k):
    """プレビュー用の小さな JPEG（幅 PREVIEW_W まで。編集画面が ▶ でためた絵を流すとき、サーバーがそのまま渡す）"""
    return folder(eng) / k[:2] / f'{k}.p.jpg'


def _cv2():
    try:
        import cv2
        return cv2
    except ImportError:
        return None


def _read_png(p):
    cv2 = _cv2()
    if cv2 is not None:
        a = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if a is None:
            raise OSError(f'読めない {p}')
        return np.ascontiguousarray(a[..., ::-1])
    from PIL import Image
    with Image.open(p) as im:
        return np.asarray(im.convert('RGB'))


def has(eng, t, draft_ok=False):
    """時刻 t の絵がためてあるか（鍵, ある）"""
    k = key(eng, t, draft_ok)
    return k, bool(k) and path_of(eng, k).is_file()


def get(eng, t, draft_ok=False):
    """ためた絵（uint8 H×W×3）と鍵。無ければ (None, 鍵)"""
    k = key(eng, t, draft_ok)
    if k is None:
        return None, None
    p = path_of(eng, k)
    if not p.is_file():
        return None, k
    try:
        img = _read_png(p)
        try:
            os.utime(p)  # 使った印（上限をこえたとき、古いものから消す）
        except OSError:
            pass
        if img.shape[:2] != (eng.H, eng.W):
            return None, k
        return img, k
    except OSError:
        return None, k


_puts = [0]


def _write(tmp, img, kind):
    a = np.ascontiguousarray(img, dtype=np.uint8)
    cv2 = _cv2()
    if kind == 'png':
        if cv2 is not None:
            ok, buf = cv2.imencode('.png', a[..., ::-1], [cv2.IMWRITE_PNG_COMPRESSION, 1])  # 速さ優先の圧縮（劣化なし）
            if not ok:
                raise OSError('PNG にできない')
            tmp.write_bytes(buf.tobytes())
        else:
            from PIL import Image
            Image.fromarray(a).save(tmp, 'PNG', compress_level=1)
        return
    h, w = a.shape[:2]
    if w > PREVIEW_W:
        nh = max(2, int(round(h * PREVIEW_W / w)))
        if cv2 is not None:
            a = cv2.resize(a, (PREVIEW_W, nh), interpolation=cv2.INTER_AREA)
        else:
            from PIL import Image
            a = np.asarray(Image.fromarray(a).resize((PREVIEW_W, nh), Image.BILINEAR))
    if cv2 is not None:
        ok, buf = cv2.imencode('.jpg', np.ascontiguousarray(a[..., ::-1]), [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_Q])
        if not ok:
            raise OSError('JPEG にできない')
        tmp.write_bytes(buf.tobytes())
    else:
        from PIL import Image
        Image.fromarray(a).save(tmp, 'JPEG', quality=PREVIEW_Q)


def put(eng, t, img, k=None):
    """描いたコマ（uint8 H×W×3）をためる（劣化なしの PNG と、プレビュー用の小さな JPEG）。鍵は描いたあとに作る（Blender の絵ができてから）"""
    if getattr(eng, 'used_draft', False):
        return False
    k = k or key(eng, t)
    if k is None:
        return False
    p, pv = path_of(eng, k), preview_of(eng, k)
    if p.is_file() and pv.is_file():
        return True
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        for dst, kind in ((pv, 'jpg'), (p, 'png')):  # PNG（あるかどうかの印）を後に置く
            if dst.is_file():
                continue
            tmp = dst.with_name(f'{dst.name}.{os.getpid()}.{threading.get_ident()}.part')
            _write(tmp, img, kind)
            os.replace(tmp, dst)
    except OSError:
        return False
    with _lock:
        _puts[0] += 1
        n = _puts[0]
    if n % 300 == 1:
        trim(eng)
    return True


def _files(eng):
    """ためた絵のファイル（PNG・小さな JPEG・前の版の JPEG・書きかけ）"""
    return [p for p in folder(eng).glob('*/*') if p.is_file()]


def trim(eng):
    """上限（settings.cache.frames_gb、既定 FRAMES_GB）をこえたら、使っていない古いものから消す。ディスクの空きが KEEP_FREE_GB を切りそうなときも"""
    try:
        cap = float((eng.settings.get('cache') or {}).get('frames_gb', FRAMES_GB)) * (1 << 30)
    except (TypeError, ValueError):
        cap = FRAMES_GB * (1 << 30)
    try:
        import shutil
        free = shutil.disk_usage(folder(eng)).free
        if free < KEEP_FREE_GB * (1 << 30):
            cap = 0.5 * cap
    except OSError:
        pass
    groups = {}
    for p in _files(eng):
        st = _stat(p)
        if st:
            g = groups.setdefault(p.name.split('.')[0], [0, 0, []])
            g[0] = max(g[0], st[0])
            g[1] += st[1]
            g[2].append(p)
    total = sum(g[1] for g in groups.values())
    if total <= cap:
        return 0
    n = 0
    for _, size, ps in sorted(groups.values(), key=lambda g: g[0]):
        for p in ps:
            try:
                p.unlink()
            except OSError:
                pass
        total -= size
        n += 1
        if total <= cap * 0.9:
            break
    return n


def clear(eng):
    """ためた絵を全部消す（API frame-cache clear）。消したコマの数"""
    n = 0
    for p in _files(eng):
        try:
            p.unlink()
            n += p.suffix == '.png'
        except OSError:
            pass
    return n


def stats(eng):
    n, size = 0, 0
    for p in _files(eng):
        st = _stat(p)
        if st:
            n += p.suffix == '.png'
            size += st[1]
    return {'frames': n, 'bytes': size, 'dir': str(folder(eng)), 't': time.time()}
