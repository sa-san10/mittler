"""Mittler の Python 描画エンジン。タイムライン（*.cut.json）を読んで、時刻 t の1コマ（uint8, H×W×3）を作る。

偽マリアMV の make_animatic.py（カットの動画）＋ fx7.py（演出）＋ 前のリリックの1コマの流れを、
「映像クリップ」と「エフェクトクリップ」（プロジェクトの effects/<名前>.py）に分けたもの。
- トラックの並び（タイムラインの先頭がいちばん手前）＝処理の順（いちばん下のトラックから順にかける）。
- エフェクトの段：'v7'（float32 の絵。曲の終わりまで。最後に 0〜255 に切って uint8）→ 'post'（uint8 の絵）。
- エフェクトのクリップに "cut" があれば、そのカットを映しているあいだだけかかる（元の表のカットごとの演出）。
- 絵は時刻・コマ番号・マスクだけで決める（前のコマを覚えない）。どのコマからでも描ける。
- カメラ（2026-10-21）：camera() を持つエフェクト（パンチ・シェイク）がそのコマのカメラ ctx.cam を決め、"sample": "source" の映像クリップは
  素材のコマのまま読んで、拡大とカメラを1回の補間でかける（Attention ダンス動画の assemble.py と同じ。形は docs/タイムライン形式.md の「素材のコマのまま読む」）。
- 場面の段（2026-10-21、作者の紙芝居の作品）：STAGE 'scene' のエフェクトは「場面（カット）の絵」の一部（フキダシ・キラキラ…）。映像クリップの絵に重ねてから 'v7' へ。
  切り替えのエフェクトは scene_frame(t, カット) で前後の場面の絵を描いて混ぜる。画像クリップもカメラ（camera()）を受ける（揺れ・つつき）。
- settings.frame_time：時刻を n / fps に直して描く。settings.subtitle.renderer = "ass"：字幕は ass.py で最後に焼く。
- 計測（2026-10-30）：render(t, prof={}) で、段ごと（video＝映像の取り出し・scene・v7・post・subtitle＝ASS の字幕）とエフェクトのクリップ1本ごとの
  所要 ms を prof に入れる（描画サーバーの /frame?prof=1）。prof を渡さなければ何も測らない（今までと同じ動き）。
- 読み込み（2026-10-30）：人のマスクの PNG はデコードしたものを LRU で覚える（helpers.read_gray。上限 settings.cache.mask_mb、既定 512）。
  映像クリップの ffmpeg に -hwaccel を通せる（settings.decode.hwaccel＝"cuda" など、既定なし＝CPU。Engine(…, hwaccel=) か --hwaccel が優先）。
  出る rgb24 は同じ（偽マリアの素材で CPU とビット単位で同じことを確かめた）。GPU で読めなかったら、そこから CPU に戻す。
- 途中でやめる（2026-10-30）：Engine.check（描画サーバーの先読みが入れる）が、エフェクトの区切りで Interrupted を投げると、その1コマをやめる。
- ドラフト品質（2026-10-30、機能追加案01）：Engine(…, draft=True) なら ctx.draft が True。対応したエフェクトだけが軽く描く（読まないエフェクトは今までどおり）。
  draft でないときの絵は今までと1ビットも変わらない。ドラフトでも「時刻・コマ番号・マスクだけで決める・前のコマを覚えない」は同じ。
- マスター書き出し（2026-10-30、機能追加案03 v2）：Engine(…, scale=2) ならキャンバスが W×2・H×2（self.W・self.H・ctx.W・ctx.H がその大きさ。
  タイムラインの大きさは self.W0・self.H0）、ctx.scale＝2（いつもは 1）。対応したエフェクト（META の 'scale_aware': True）は px の値に ctx.scale を掛ける。
  人のマスク（helpers.load_matte の ctx.m_s。ctx.m はそれを ctx.W×ctx.H に）と顔の箱（helpers.face_box）はエンジンの側で s 倍にして渡す。
  Engine(…, fps=60) はタイムラインの fps（self.tl_fps）の代わりに 60 でコマを刻む（絵は時刻だけで決まるので、エフェクトは本当の 60fps になる。
  ctx.fi・ctx.sfi は 60fps の番号。マスク・顔の箱のコマはタイムラインの fps の番号に直して読む）。
  Engine(…, src_map={素材のパス: 差し替えるファイル}) は映像の素材を読み替える（アプスケ・補間したキャッシュ。タイムラインのファイルは書き換えない）。
  src_map の '@clips'＝{クリップの id: {素材のパス: ファイル}} は、そのクリップだけの読み替え（2026-10-31、アップスケールのモデルをクリップで変えたとき。master.py）。
  scale=1・fps なし・src_map なし（いつも）は今までと1ビットも変わらない。
- クリップの色（2026-10-31）：映像・画像・🎬 のクリップに "grade": {b, c, v, s} があれば、そのクリップの絵を読んだ直後（エフェクトより前）に
  色の卓と同じ式（effects_lib/common/grade.py）をかける。クリップを動かすと色も一緒に動く。カットの色の卓（grade エフェクト）とは別で、両方かかる。
  grade が無い・全部 1 のクリップは今までと1ビットも変わらない（式を通さない）。
エフェクトの形は docs/エフェクトの書き方.md。
"""
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import helpers
from . import warp as warp_mod
from .helpers import Beats

def affine_render(img, out_w, out_h, zoom=1.0, dx=0.0, dy=0.0, rot_deg=0.0):
    """画面を覆うように拡大（cover）してから、中心まわりに zoom 倍・rot_deg 度回し、dx, dy ずらす（Pillow の bicubic、1回の補間）。
    Attention ダンス動画の assemble.py の affine_render をそのまま写したもの（"sample": "source" の映像クリップが使う）。"""
    iw, ih = img.size
    s = max(out_w / iw, out_h / ih) * zoom
    th = math.radians(rot_deg)
    c, si = math.cos(th), math.sin(th)
    a, b = c / s, si / s
    d, e = -si / s, c / s
    ox, oy = out_w / 2 + dx, out_h / 2 + dy
    cx, cy = iw / 2, ih / 2
    return img.transform((out_w, out_h), Image.Transform.AFFINE,
                         (a, b, cx - (a * ox + b * oy), d, e, cy - (d * ox + e * oy)),
                         resample=Image.Resampling.BICUBIC)


def _probe_frames(path):
    """素材の幅・高さ・fps・コマ数（パケットを数える。assemble.py の probe と同じ）"""
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets',
                          '-show_entries', 'stream=width,height,r_frame_rate,nb_read_packets', '-of', 'json', str(path)],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)['streams'][0]
    n, d = s['r_frame_rate'].split('/')
    return dict(w=int(s['width']), h=int(s['height']), fps=float(n) / float(d), n=int(s['nb_read_packets']))


class VideoClip:
    """1本の映像クリップ（元の make_animatic.py の VideoCut と同じ読み方）。
    clip：{src:[動画…]（1本なら文字列でもよい）, in（素材の何秒目から。offset とも書ける）, speed, warp（表の JSON か、点 {points, smooth}。warp.py）, curve（カーブの JSON か null）}。
    素材のパスは root からの相対。
    "sample": "source"（2026-10-21、Attention ダンス動画の取り込みで足した）：素材を素材のままの大きさ・fps で頭から読み、
    素材のコマを番号で選ぶ（round(素材の秒 × 素材の fps)。warp の表の3列目＝速さが blend_below より遅いところは隣のコマと混ぜる）。
    画面へは Pillow の bicubic で1回だけ拡大する（cover）。そのときカメラのエフェクト（camera() を持つエフェクト：パンチ・シェイク）の
    ズーム・ずらし・回転も同じ1回でかける（ctx.cam）。src は1本だけ。"""
    def __init__(self, eng, clip):
        self.eng, self.clip = eng, clip
        self.W, self.H, self.fps = eng.W, eng.H, eng.fps
        mid = clip.get('map_id', clip.get('id'))  # 差し替え表でのクリップの id（🎬 のテイクは予定のクリップの id）
        self.clips = [eng.src_path(s, mid) for s in ([clip['src']] if isinstance(clip['src'], str) else clip['src'])]
        self.source = clip.get('sample') == 'source'
        if self.source:
            self.info = _probe_frames(self.clips[0])
            self.durs = [self.info['n'] / self.info['fps']]
            self.frames = {}  # 素材のコマ番号 → PIL の絵（いま読んでいるあたりだけ）
            self.pos = 0      # 次に読む素材のコマ番号
        else:
            self.durs = [float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(c)],
                                              capture_output=True, text=True).stdout.strip() or 0) for c in self.clips]
        self.proc, self.key, self.last = None, None, np.zeros((self.H, self.W, 3), np.uint8)
        self.hw = False  # 開いている ffmpeg が GPU で読んでいるか
        self.got = False  # 本物のコマを1枚でも読んだか（読む前に「尽きた」となったら、黒ではなく素材の最後のコマを出す）
        self.offset = float(clip.get('in', clip.get('offset', 0.0)))  # 編集画面は in と書く
        self.speed = float(clip.get('speed', 1.0))
        self.warp, self.warp_in = None, True  # 時間の付け替え（warp.py：表のファイルか、編集画面で作る点）
        wl = warp_mod.load(clip, eng.root)
        if wl:
            self.warp, self.warp_in = wl
        self.warp_speed = None  # 表の3列目（速さ。"sample": "source" の blend_below 用）
        if isinstance(clip.get('warp'), str):
            tab = np.asarray(json.loads((eng.root / clip['warp']).read_text(encoding='utf-8'))['table'], dtype=np.float64)
            if tab.shape[1] > 2:
                self.warp_speed = (tab[:, 0], tab[:, 2])
        self.grade = eng.curve_lut(clip['curve']) if clip.get('curve') else None
        if clip.get('land') and len(self.clips) == 1 and self.speed == 1.0 and self.warp is None:
            # 最後の画像に着地するクリップがクリップの長さより長いときは、頭を切って最後のコマを終わりにそろえる（等速のまま）
            over = self.durs[0] - clip['dur']
            if over > 0.5 / self.fps:
                self.offset = over

    def close(self):
        if self.proc:
            self.proc.kill()
            self.proc = None

    def release(self):
        """開いている ffmpeg を止める（Engine._opened が、しばらく使っていないクリップに。2026-11-12）。最後に読んだ絵（self.last・self.got）は残す：
        素材が尽きたあとのコマはそれを出す。次に読むときは、今までも通っていた道（開き直してシーク。"sample": "source" は頭から読み直し）になる"""
        if self.proc:
            self.proc.kill()
            try:
                self.proc.stdout.close()
                self.proc.wait(timeout=5)
            except Exception:
                pass
            self.proc = None
        self.key = None

    def _open(self, ci, fi):
        if self.proc:
            self.proc.kill()
        vf = f'scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H},fps={self.fps}'
        hw = ['-hwaccel', self.eng.hwaccel] if self.eng.hwaccel else []  # GPU で読む（settings.decode.hwaccel。出る rgb24 は同じ）
        # 素材のコマ fi（素材を頭から読んで fps にそろえた並びの fi 番目）から読み始める。どこから開いても「頭から順に読んだ絵」と同じコマが出るようにする（2026-11-12）。
        # 前は -ss <fi / fps を小数 4 桁> で飛んでいた。(1) x.x667 のように丸めて大きくなるコマは、目当てのコマが捨てられて次のコマから始まった（30fps で 3 コマに 1 つ。
        # プレビュー・📷・静止画が素材 1 コマ先を見せ、並列の書き出しは区間の頭がクリップの途中に当たると、そのクリップが 1 コマずれた）。
        # (2) 素材と作品の fps が違うと、fps の目盛りが「飛んだ先」から数え直されて、頭から読んだときと違う素材のコマが選ばれた。
        # 今：頭に近いコマ（1 秒ぶんより前）は、頭から読んで fi コマ捨てる。それより先は、手前のキーフレームへ飛び（-noaccurate_seek）、時刻は素材のまま
        # （-copyts -start_at_zero）で fps の目盛りを素材の頭から数え、fi 番目より前を trim で落とす。
        skip = 0
        if fi < max(1, int(self.fps)):
            seek, skip = [], fi
        else:
            seek, vf = ['-noaccurate_seek', '-ss', f'{fi / self.fps:.6f}', '-copyts', '-start_at_zero'], vf + f',trim=start_pts={fi}'
        self.proc = subprocess.Popen(['ffmpeg', '-v', 'error'] + hw + seek + ['-i', str(self.clips[ci]), '-vf', vf,
                                      '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
        self.hw = bool(hw)
        self.key = (ci, fi)
        self.eng._opened(self)
        if skip:
            self.proc.stdout.read(self.W * self.H * 3 * skip)

    def _read(self, ci, fi):
        """開いている ffmpeg から1コマ読む。GPU で読んでいて ffmpeg が失敗して終わったら（GPU が無い・使えない）、
        この先はエンジンごと CPU で読むことにして、開き直して読む（素材の終わりで読めないのは失敗ではない：ffmpeg は 0 で終わる）"""
        n = self.W * self.H * 3
        buf = self.proc.stdout.read(n)
        if len(buf) < n and self.hw and self.proc.wait() != 0:
            print(f'GPU（-hwaccel {self.eng.hwaccel}）で読めなかったので CPU で読みます: {self.clips[ci]}', file=sys.stderr, flush=True)
            self.eng.hwaccel = None
            self._open(ci, fi)
            buf = self.proc.stdout.read(n)
        return buf

    def _tail(self, ci):
        """素材 ci の最後のコマ（画面の大きさ）。尽きたあとの時刻を、ほかのコマを読む前に頼まれたとき（すき間・終わりのコマへの直接のシーク）。
        前は黒（まだ何も読んでいない self.last）を返していて、採用した動画のつなぎ目に黒いコマが入った（2026-10-24）"""
        vf = f'scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H}'
        out = subprocess.run(['ffmpeg', '-v', 'error', '-sseof', '-1', '-i', str(self.clips[ci]), '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                             capture_output=True).stdout
        fs = self.W * self.H * 3
        n = len(out) // fs
        if not n:
            return
        img = np.frombuffer(out[(n - 1) * fs:n * fs], np.uint8).reshape(self.H, self.W, 3)
        if self.grade:
            from .lib import curve
            img = np.asarray(curve.apply(Image.fromarray(img), *self.grade))
        self.last, self.got = img, True

    def _source_frame(self, i):
        """素材のコマ i（PIL、素材の大きさ）。頭から順に読む（assemble.py の decode と同じ ffmpeg の読み方）。戻るときは読み直す"""
        if i in self.frames:
            return self.frames[i]
        if self.proc is None or i < self.pos:
            if self.proc:
                self.proc.kill()
            self.proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', str(self.clips[0]), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                         stdout=subprocess.PIPE)
            self.pos, self.frames = 0, {}
            self.eng._opened(self)
        w, h = self.info['w'], self.info['h']
        while self.pos <= i:
            buf = self.proc.stdout.read(w * h * 3)
            if len(buf) < w * h * 3:  # 素材が尽きた：最後に読めたコマ
                return self.frames[max(self.frames)] if self.frames else Image.new('RGB', (w, h))
            self.frames[self.pos] = Image.frombuffer('RGB', (w, h), buf, 'raw', 'RGB', 0, 1).copy()
            for k in [k for k in self.frames if k < self.pos - 2]:
                del self.frames[k]
            self.pos += 1
        return self.frames[i]

    def _frame_source(self, t, cam):
        """"sample": "source" の1コマ（assemble.py の plan と書き出しのループの、そのコマの部分と同じ計算）"""
        st = (self.warp(t) + (self.offset if self.warp_in else 0.0)) if self.warp is not None else t * self.speed + self.offset
        p = st * self.info['fps']
        n = self.info['n']
        if self.warp_speed is not None:   # 速さ（表の3列目）
            sp = float(np.interp(t, *self.warp_speed))
        elif self.warp is not None:       # 点：傾き（beatwarp.TimeMap.speed と同じ h = 1e-3）
            sp = (self.warp(t + 1e-3) - self.warp(t - 1e-3)) / 2e-3
        else:
            sp = self.speed
        p = min(max(p, 0.0), n - 1.0)
        i0 = int(math.floor(p))
        fr = p - i0
        bb = self.clip.get('blend_below')
        if bb is not None and sp < bb and 0.2 < fr < 0.8 and i0 + 1 < n:  # ゆっくりのところ：隣のコマと混ぜる
            src = Image.blend(self._source_frame(i0), self._source_frame(i0 + 1), fr)
        else:
            src = self._source_frame(min(int(round(p)), n - 1))
        if self.grade:
            from .lib import curve
            src = curve.apply(src, *self.grade)
        cam = cam or {}
        img = affine_render(src, self.W, self.H, cam.get('zoom', 1.0), cam.get('dx', 0.0), cam.get('dy', 0.0), cam.get('rot', 0.0))
        self.last = np.asarray(img)
        return self.last

    def frame(self, t, cam=None):
        """クリップの頭から t 秒の絵（cam は "sample": "source" のときだけ使う）"""
        self.eng._used(self)
        if self.source:
            return self._frame_source(t, cam)
        t = (self.warp(t) + (self.offset if self.warp_in else 0.0)) if self.warp is not None else t * self.speed + self.offset
        for ci, d in enumerate(self.durs):
            if t < d - 0.5 / self.fps:
                break
            t -= d
        else:
            if not self.got:
                self._tail(len(self.durs) - 1)
            return self.last  # 動画が尽きたら最後のコマで止める
        fi = int(round(t * self.fps))
        if self.key and self.key[0] == ci and 0 < fi - self.key[1] <= 8 and self.proc:
            self.proc.stdout.read(self.W * self.H * 3 * (fi - self.key[1]))
            self.key = (ci, fi)
        if self.key != (ci, fi):
            self._open(ci, fi)
        buf = self._read(ci, fi)
        self.key = (ci, fi + 1)
        if len(buf) == self.W * self.H * 3:
            img = np.frombuffer(buf, np.uint8).reshape(self.H, self.W, 3)
            if self.grade:
                from .lib import curve
                img = np.asarray(curve.apply(Image.fromarray(img), *self.grade))
            self.last, self.got = img, True
        elif not self.got:  # 素材の終わりぎわで読めなかった（シークした先にコマが無い）
            self._tail(ci)
        return self.last


def _ease(p):
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def _back_out(p):
    p = min(1.0, max(0.0, p))
    c1 = 1.9
    return 1 + (c1 + 1) * (p - 1) ** 3 + c1 * (p - 1) ** 2


class ImageClip:
    """静止画のクリップ（紙芝居のコマ・タイトルカード）。camera＝[[クリップの頭からの秒, 寄り, 中心x, 中心y（画像に対する割合）], …] を
    なめらかにつなぐ（無ければ全体を映す）。pop＝true ならタイトルカードのように 0.93 倍から弾んで出る（黒地）。
    カメラのエフェクト（camera()：揺れ・つつき。2026-10-21 作者の紙芝居の作品の完全再現で足した）：そのコマのカメラ cam の zoom を寄りにかけ、
    dx・dy（画面の px）だけ切り取りをずらす。ずれているあいだは cam の zoom_min より寄りを小さくしない（揺れでふちが見えないように）。
    follow_cam＝false のクリップ（タイトルカード）はカメラを受けない（元の build.py と同じ：揺れ・つつきは場面のコマだけ）。
    切り取りの位置（view：x0・y0・scale・base）は 'scene' 段のエフェクト（フキダシ・キラキラ）が画像に貼りつくのに使う（ctx.view）。"""
    def __init__(self, eng, clip):
        self.clip, self.W, self.H = clip, eng.W, eng.H
        self.src = Image.open(eng.root / clip['src']).convert('RGB')
        self.view = None

    def close(self):
        pass

    def camera(self, tl):
        keys = self.clip.get('camera')
        if not keys:
            return 1.0, .5, .5
        if tl <= keys[0][0]:
            return tuple(keys[0][1:])
        for a, b in zip(keys, keys[1:]):
            if tl <= b[0]:
                p = _ease((tl - a[0]) / (b[0] - a[0]))
                return tuple(a[i] + (b[i] - a[i]) * p for i in (1, 2, 3))
        return tuple(keys[-1][1:])

    def frame(self, tl, cam=None):
        W, H, src = self.W, self.H, self.src
        sw, sh = src.size
        tl = min(max(tl, 0.0), self.clip['dur'])
        z, cx, cy = self.camera(tl)
        dx = dy = 0.0
        if cam and self.clip.get('follow_cam', True):  # カメラのエフェクト（揺れ・つつき）。無ければ zoom 1・ずれ 0（今までと同じ絵）
            z *= cam.get('zoom', 1.0)
            dx, dy = cam.get('dx', 0.0), cam.get('dy', 0.0)
        if self.clip.get('pop'):
            z = .93 + .07 * _back_out(tl / .45)
        if (dx or dy) and cam.get('zoom_min'):
            z = max(z, cam['zoom_min'])  # 揺れ幅ぶんの余白
        cw, ch = sw / z, sh / z
        x0 = min(max(cx * sw - cw / 2 + dx * sw / W, 0), sw - cw)
        y0 = min(max(cy * sh - ch / 2 + dy * sh / H, 0), sh - ch)
        self.view = {'x0': x0, 'y0': y0, 'cw': cw, 'ch': ch, 'sw': sw, 'sh': sh, 'scale': W / cw, 'base': W / sw}
        if z < 1:  # 縮小（タイトルの弾み）：黒地の真ん中
            small = src.resize((int(W * z), int(H * z)), Image.BICUBIC)
            frame = Image.new('RGB', (W, H), (0, 0, 0))
            frame.paste(small, ((W - small.width) // 2, (H - small.height) // 2))
        else:
            frame = src.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + cw, y0 + ch))
        return np.asarray(frame)


class PlanClip:
    """動画化予定のクリップ（🎬 kind "plan"）。映像ができるまでの仮の絵：スタートの絵 → エンドの絵を、クリップの長さでなめらかに入れ替える
    （片方だけならその絵。どちらも無ければ黒）。絵は縦横の比を保って画面を覆う（はみ出たところは切る）。素材のパスは root からの相対。
    動画のテイクを選んでいれば（video.activeTake）、採用する前でもそのテイクの動画を頭から映す（2026-10-24。採用する前に流れの中で見比べられるように）。
    映像トラックのすぐ下に置くので、採用した映像クリップが上にあれば、そちらが映る。"""
    def __init__(self, eng, clip):
        self.clip, self.W, self.H = clip, eng.W, eng.H
        tk = plan_take(clip)
        self.take = VideoClip(eng, {'id': clip['id'] + '__take', 'map_id': clip['id'], 'src': [tk['src']], 'in': 0, 'speed': 1}) if tk and (eng.root / tk['src']).is_file() else None
        self.imgs = []
        for k in ('start_frame', 'end_frame'):
            src = (clip.get(k) or {}).get('src')
            p = eng.root / src if src else None
            self.imgs.append(self._cover(p) if p and p.is_file() else None)

    def _cover(self, p):
        im = Image.open(p).convert('RGB')
        sw, sh = im.size
        r = self.W / self.H
        cw, ch = (sh * r, sh) if sw / sh > r else (sw, sw / r)
        x0, y0 = (sw - cw) / 2, (sh - ch) / 2
        return np.asarray(im.resize((self.W, self.H), Image.BICUBIC, box=(x0, y0, x0 + cw, y0 + ch)), dtype=np.float32)

    def close(self):
        if self.take:
            self.take.close()

    def frame(self, tl, cam=None):
        if self.take:
            return self.take.frame(tl, cam)
        a, b = self.imgs
        if a is None and b is None:
            return np.zeros((self.H, self.W, 3), np.uint8)
        if a is None or b is None:
            return (a if a is not None else b).astype(np.uint8)
        p = _ease(tl / max(float(self.clip['dur']), 1e-6))
        return np.clip(np.rint(a + (b - a) * p), 0, 255).astype(np.uint8)


_GRADE = []


def _grade_mod():
    """クリップの色（映像・画像・🎬 のクリップの "grade"）の式：色の卓の effects_lib/common/grade.py をそのまま読む（式は1か所。
    編集画面の editor/calc.js の gradePixel と同じことは tools/smoke_same.py が確かめる）。作品の effects/grade.py（写し）は使わない"""
    if not _GRADE:
        p = Path(__file__).resolve().parent.parent.parent / 'effects_lib' / 'common' / 'grade.py'
        spec = importlib.util.spec_from_file_location('mittler_clip_grade', p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GRADE.append(mod)
    return _GRADE[0]


def plan_take(clip):
    """動画化予定のクリップで選んでいる動画のテイク（{id, src, …}）。無ければ None"""
    v = clip.get('video') or {}
    return next((k for k in v.get('takes') or [] if k.get('id') == v.get('activeTake') and k.get('src')), None)


def has_plan_frame(clip):
    return bool(plan_take(clip)) or any((clip.get(k) or {}).get('src') for k in ('start_frame', 'end_frame'))


class Ctx:
    """エフェクトに渡す、そのコマの情報。m / m_s は人のマスク（matte エフェクトが入れ、背景ビートが動かす。無ければ None）。"""
    def __init__(self, eng, t, ts, cut):
        self.eng, self.t, self.ts, self.cut = eng, t, ts, cut
        self.W, self.H, self.fps = eng.W, eng.H, eng.fps
        self.fi = int(round(t * eng.fps))     # 曲のコマ番号
        self.sfi = int(round(ts * eng.fps))   # 動画（とマスク）のコマ番号（カットインのコマ止めなどで t とずれる）
        self.m = None
        self.m_s = None
        self.cam = {'zoom': 1.0, 'dx': 0.0, 'dy': 0.0, 'rot': 0.0}  # そのコマのカメラ（camera() を持つエフェクトが決める。Engine.camera）
        self.view = None  # 画像クリップの切り取り（x0・y0・scale・base。'scene' 段のエフェクトが画像に貼りつくのに使う）
        self.beats = eng.beats
        self.settings = eng.settings
        self.cache = eng.cache
        self.root = eng.root
        self.draft = eng.draft  # ドラフト品質で描いてよいか（docs/エフェクトの書き方.md。読まなければ今までどおりの絵）
        self.scale = eng.scale  # キャンバスの倍率（いつもは 1、マスター書き出しは 2。対応したエフェクトは px の値に掛ける。docs/エフェクトの書き方.md）

    def level(self, t=None):
        return self.eng.level(self.t if t is None else t)

    def clips_of(self, effect):
        return self.eng.clips_of(effect)


class Interrupted(Exception):
    """描いている途中でやめた（Engine.check が投げる。描画サーバーの先読みが、新しい頼みに場所をゆずるとき）"""


class Engine:
    def __init__(self, timeline_file, hwaccel=None, draft=False, scale=1, fps=None, src_map=None):
        self.file = Path(timeline_file).resolve()
        self.dir = self.file.parent
        # ドラフト品質（ctx.draft）：True なら、対応したエフェクト（ctx.draft を読むもの）が軽い描き方をしてよい。読まないエフェクトは今までどおり。
        # 書き出しは --draft、描画サーバーは /frame?draft=1 の間だけ True。読み直し（load）では変えない
        self.draft = bool(draft)
        # マスター書き出し（機能追加案03 v2）：キャンバスの倍率（ctx.scale）・コマを刻む fps の上書き・映像の素材の差し替え表。読み直し（load）でも同じ
        # 倍率は整数なら int のまま（いつもの 1 は int。エフェクトが px の値に掛けても型が変わらない）
        s = float(scale)
        if not s > 0:
            raise ValueError(f'scale は正の数（{scale}）')
        self.scale = int(s) if s.is_integer() else s
        self._fps_arg = fps  # None ならタイムラインの fps
        sm = dict(src_map or {})
        clip_map = sm.pop('@clips', None) or {}  # クリップごとの差し替え（{クリップの id: {素材のパス: ファイル}}。アップスケールのモデルをクリップで変えたもの）
        self.src_map = {str(k): str(v) for k, v in sm.items()}  # 素材のパス（タイムラインに書いたまま）→ 差し替えるファイル（絶対パス）
        self.clip_src_map = {str(c): {str(k): str(v) for k, v in m.items()} for c, m in clip_map.items()}
        self._prof = None  # 計測中だけ dict（render(t, prof=…)）
        # 描く途中（映像の取り出しと、v7・post のエフェクト1本ずつの前）に呼ぶもの。Interrupted を投げると、その1コマはやめる
        # （描画サーバーの先読み。エフェクトの途中では止めないので、ctx.cache などが半端にならない）。None なら何もしない
        self.check = None
        # 編集画面のプレビュー（描画サーバーの JPEG）を描いている間だけ True（serve.py）。Blender の 3D（blender.py）が、ためた本番の絵が無いときに
        # 下描きの品質で描いてよいかを見る。ほかのエフェクトは見ない（絵は変わらない）
        self.preview = False
        self.used_draft = False
        self._tree_sig = None   # effects/ の下の .py の印（_fx_tree）
        self._tree_frame = None
        # 作品の effects/（_lib など）に __pycache__ を書かない（作品のフォルダを汚さない。2026-11-16 使ってみた知らせ）。読む速さはほぼ同じ
        sys.dont_write_bytecode = True
        self._hwaccel_arg = hwaccel  # 映像を GPU で読む（"cuda" など）。None ならタイムラインの settings.decode.hwaccel、"none" なら CPU
        self.load()

    # ---- 読み込み ----
    def load(self):
        for i in range(40):  # 編集画面のサーバーが置きかえている瞬間（Windows）は開けないことがある。一瞬なので待って読み直す
            try:
                text = self.file.read_text(encoding='utf-8')
                break
            except PermissionError:
                if i == 39:
                    raise
                time.sleep(0.01)
        tl = json.loads(text)
        self.tl = tl
        self.root = (self.dir / tl.get('root', '.')).resolve()
        os.environ['MITTLER_ROOT'] = str(self.root)  # 作品のエフェクトの部品（effects/_lib/ など）が素材の場所に使う
        os.environ['CC_ROOT'] = str(self.root)  # 古い名前の互換：今までの作品の部品（作者の作品の effects/_lib/ など）は CC_ROOT を読む
        self.W0, self.H0, self.tl_fps = tl['width'], tl['height'], tl['fps']  # タイムラインの大きさ・fps
        self.W, self.H, self.fps = tl['width'], tl['height'], tl['fps']
        if self.scale != 1:  # マスター：キャンバスを s 倍に
            self.W, self.H = int(round(self.W0 * self.scale)), int(round(self.H0 * self.scale))
        if self._fps_arg:  # マスター：コマを刻む fps（タイムラインの fps の代わり）
            f = float(self._fps_arg)
            self.fps = int(f) if f.is_integer() else f
        self.duration, self.song_end = tl['duration'], tl.get('song_end', tl['duration'])
        self.settings = tl.get('settings', {})
        hw = self._hwaccel_arg if self._hwaccel_arg is not None else (self.settings.get('decode') or {}).get('hwaccel')
        self.hwaccel = None if hw in (None, '', 'none') else str(hw)  # 映像クリップの ffmpeg の -hwaccel（読めなければ VideoClip が None に戻す）
        helpers.set_mask_cache_mb((self.settings.get('cache') or {}).get('mask_mb', 512))  # マスクの LRU の上限
        meta = {m['id']: m for m in tl.get('meta', [])}
        self.meta = meta
        self.beats = Beats([tuple(b) for b in self._meta_kind('beats').get('items', [])])
        self.sections = self._meta_kind('sections').get('items', [])
        self.cuts = sorted(self._meta_kind('cuts').get('items', []), key=lambda c: c['start'])
        self.cache = {}
        self._luts = {}
        self._mods = {}
        self._frame_no = 0
        self._videos = {}
        self._live = []  # ffmpeg を開いている映像クリップ（使った順。_opened・_used）
        # 下のトラックから順に（タイムラインの先頭がいちばん手前）
        self.tracks = [tr for tr in reversed(tl.get('tracks', [])) if not tr.get('hidden')]
        # 映像：映像トラック＋動画化予定（🎬）のトラック（絵のあるクリップだけ）。並びはトラックの順（上のトラックが手前）
        self.video_clips = [c for tr in self.tracks if tr.get('kind') in ('video', 'plan') for c in tr.get('clips', [])
                            if not c.get('disabled') and (tr.get('kind') == 'video' or has_plan_frame(c))]
        # エフェクトと字幕（字幕のトラックのクリップは effects/subtitle.py がかける）。音のトラック（tts・audio）は絵には関係しない
        # settings.subtitle.renderer = "ass"（2026-10-21、作者の紙芝居の作品）：字幕は ASS にして ffmpeg の ass（libass）で最後に焼く（ass.py）
        sub = self.settings.get('subtitle') or {}
        self.ass_mode = sub.get('renderer') == 'ass'
        self.ass_clips = [c for tr in self.tracks if tr.get('kind') == 'subtitle' for c in tr.get('clips', []) if not c.get('disabled')] if self.ass_mode else []
        self.ass_burn = True  # 1コマずつ焼く（静止画・プレビュー）。書き出しの区間は、エンコードの ffmpeg でまとめて焼く（__main__.segment が False に）
        if not self.ass_mode:
            for tr in self.tracks:
                if tr.get('kind') == 'subtitle':
                    for c in tr.get('clips', []):
                        c.setdefault('effect', 'subtitle')
        kinds = ('effect',) if self.ass_mode else ('effect', 'subtitle')
        self.effect_clips = [c for tr in self.tracks if tr.get('kind') in kinds for c in tr.get('clips', []) if not c.get('disabled')]
        self._by_effect = {}
        for c in self.effect_clips:
            self._by_effect.setdefault(c['effect'], []).append(c)
        # settings.frame_time = true：時刻をコマ番号から n / fps に直して描く（2026-10-21、作者の紙芝居の作品の元の t0 + i / FPS と同じ小数）
        self.frame_time = bool(self.settings.get('frame_time'))
        self.has_scene = any(self._stage(c['effect']) == 'scene' for c in self.effect_clips)

    def _meta_kind(self, kind):
        return next((m for m in self.tl.get('meta', []) if m.get('kind') == kind), {})

    def clips_of(self, effect):
        return self._by_effect.get(effect, [])

    def _stage(self, name):
        """エフェクトの段（ファイルが読めなければ 'v7'。読めないエラーは描くときに出す）"""
        try:
            return getattr(self.effect(name), 'STAGE', 'v7')
        except Exception:
            return 'v7'

    def level(self, t):
        for it in self.sections:
            if it['start'] <= t < it['end']:
                return it['value']
        return 0.3

    def curve_lut(self, rel):
        if rel not in self._luts:
            from .lib import curve
            cfg = json.loads((self.root / rel).read_text(encoding='utf-8'))
            self._luts[rel] = (curve.monotone_lut(cfg['points']), cfg.get('mode', 'luma'))
        return self._luts[rel]

    def _fx_tree(self):
        """effects/ の下の .py 全部（_lib など、エフェクトが import する部品も）の更新時刻と大きさ。1コマに1回だけ見る。
        変わっていたら、作品の effects/ の下から import された部品を sys.modules から外し、エフェクトも全部読み直す（2026-11-16。
        前は、エフェクトのファイルは読み直しても、エフェクトが import した部品（effects/_lib/*.py・ほかのエフェクト）は最初に読んだ版が
        描画サーバーの中に残り、書きかけの古い部品と新しい部品の組み合わせで落ちていた）"""
        if self._tree_frame == self._frame_no:
            return
        self._tree_frame = self._frame_no
        base = self.dir / 'effects'
        sig = []
        if base.is_dir():
            for p in sorted(base.rglob('*.py')):
                if '__pycache__' in p.parts:
                    continue
                try:
                    st = p.stat()
                    sig.append((str(p), st.st_mtime_ns, st.st_size))
                except OSError:
                    pass
        sig = tuple(sig)
        if self._tree_sig is not None and sig != self._tree_sig:
            root = str(base.resolve()).lower() + os.sep
            for k, m in list(sys.modules.items()):
                f = getattr(m, '__file__', None)
                if f and str(Path(f).resolve()).lower().startswith(root):
                    sys.modules.pop(k, None)
            self._mods = {}
        self._tree_sig = sig

    def effect(self, name):
        """プロジェクトの effects/<name>.py（変わっていたら読み直す。確かめるのは1コマに1回。import した部品が変わったときも：_fx_tree）"""
        self._fx_tree()
        got = self._mods.get(name)
        if got and got[2] == self._frame_no:
            return got[1]
        p = self.dir / 'effects' / f'{name}.py'
        mt = p.stat().st_mtime_ns
        if got and got[0] == mt:
            self._mods[name] = (mt, got[1], self._frame_no)
            return got[1]
        spec = importlib.util.spec_from_file_location(f'mittler_effect_{name}', p)
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # エフェクトから mittler を import できるように（古い名前 ccpy も同じ場所の受け口から）
        spec.loader.exec_module(mod)
        self._mods[name] = (mt, mod, self._frame_no)
        return mod

    def src_path(self, rel, clip_id=None):
        """映像の素材のファイル：差し替え表（マスター書き出しのアプスケ・補間のキャッシュ）にあればそれ、無ければ root からの相対。
        clip_id のクリップだけの差し替え（'@clips'。アップスケールのモデルをクリップで変えたもの）があれば、それが先"""
        if clip_id is not None and self.clip_src_map:
            got = self.clip_src_map.get(str(clip_id), {}).get(str(rel))
            if got:
                return Path(got)
        got = self.src_map.get(str(rel)) if self.src_map else None
        return Path(got) if got else self.root / rel

    def video(self, clip):
        k = clip['id']
        if k not in self._videos:
            t = clip.get('type')
            self._videos[k] = ImageClip(self, clip) if t == 'image' else PlanClip(self, clip) if t == 'plan' else VideoClip(self, clip)
        return self._videos[k]

    def close(self):
        for v in self._videos.values():
            v.close()
        self._live = []

    # 映像クリップの ffmpeg は、開いたままにするのを MAX_OPEN 本まで（2026-11-12）。前は、クリップ 1 本ごとに開いたまま、再生位置が過ぎても止めなかった
    # （止めるのはタイムラインを読み直したときと終わるときだけ）。書き出しの区間は前へ進むだけなので、通ったクリップの数だけ ffmpeg がたまっていた。
    # こえたら、いちばん長く使っていないものの ffmpeg を止める（VideoClip.release。絵は覚えたまま）。同じコマで使うクリップ（切り替えの前後の場面など）は
    # MAX_OPEN より少ないので、止めたり開いたりを繰り返すことは無い
    MAX_OPEN = 6

    def _used(self, vc):
        """vc を今使った（いちばん新しい側へ）"""
        lv = self._live
        if lv and lv[-1] is vc:
            return
        if vc in lv:
            lv.remove(vc)
            lv.append(vc)

    def _opened(self, vc):
        """vc が ffmpeg を開いた：開いているものが MAX_OPEN 本をこえたら、長く使っていないものから止める"""
        lv = self._live
        if vc in lv:
            lv.remove(vc)
        lv.append(vc)
        while len(lv) > self.MAX_OPEN:
            lv.pop(0).release()

    # ---- 1コマ ----
    def cut_at(self, t):
        """t を映しているカット（最後のカットの後ろは最後のカット）。カットの表が空なら、全体で1つのカット（ラベル ''）"""
        if not self.cuts:
            return {'start': 0.0, 'label': ''}
        c = self.cuts[0]
        for x in self.cuts:
            if t >= x['start']:
                c = x
        return c

    def source_time(self, t):
        """動画とマスクを取り出す時刻（カットインのコマ止めなど、source_time を持つエフェクトが決める）"""
        for c in self.effect_clips:
            mod = self.effect(c['effect'])
            if hasattr(mod, 'source_time'):
                ts = mod.source_time(self, c, t)
                if ts is not None:
                    return ts
        return t

    def active(self, c, t, cut):
        if c.get('cut') is not None and str(c['cut']) != str(cut):
            return False
        return c['start'] <= t < c['start'] + c['dur']

    def camera(self, ctx):
        """そのコマのカメラ {zoom, dx, dy, rot}：camera(ctx, cam, clip) を持つエフェクトのクリップ（かかっているもの）を処理の順に通す。
        "sample": "source" の映像クリップが拡大と同じ1回の補間でかける。エフェクトも ctx.cam で読める（床に貼る字をカメラに合わせるなど）。"""
        cam = dict(ctx.cam)
        for c in self.effect_clips:
            if not self.active(c, ctx.t, ctx.cut):
                continue
            mod = self.effect(c['effect'])
            if hasattr(mod, 'camera'):
                cam = mod.camera(ctx, cam, c) or cam
        return cam

    def camera_at(self, t):
        """ほかのコマ（曲の時刻 t）のカメラ（エフェクトが別のコマの位置を求めるとき）"""
        cut = self.cut_at(t)
        return self.camera(Ctx(self, t, t, str(cut['label'])))

    def _clip_frame(self, c, tl, cam):
        v = self.video(c)
        img = v.frame(tl, cam)
        g = c.get('grade')
        if g and any(float(g.get(k, 1.0)) != 1.0 for k in ('b', 'c', 'v', 's')):
            img = _grade_mod().apply(None, img, {'params': g})  # クリップの色（素材を読んだ直後・エフェクトより前。0〜255 の float32）
        return img

    def _tick(self):
        """描く途中の区切り（先読みをやめるか、self.check が決める）"""
        if self.check is not None:
            self.check()

    def _timed(self, key, fn, *args):
        """fn(*args) を呼ぶ。計測中（self._prof が dict）だけ、かかった ms を key に足す（入れ子の場面の絵も足していく）"""
        pf = self._prof
        if pf is None:
            return fn(*args)
        t0 = time.perf_counter()
        try:
            return fn(*args)
        finally:
            pf[key] = pf.get(key, 0.0) + (time.perf_counter() - t0) * 1000

    @staticmethod
    def _prof_summary(pf, total):
        """計測の結果：{total, stages: {video, scene, v7, post, subtitle, other}, fx: [[段, エフェクト, クリップの id, ms], …（重い順）]}。
        other は段に入らない分（カット・カメラ・source_time・0〜255 に切る、など）。切り替えのエフェクトが前後の場面を描くときは、
        その場面の映像・'scene' 段も数えるので、other が負になることがある"""
        fx = sorted(([k[1], k[2], k[3], v] for k, v in pf.items() if isinstance(k, tuple)), key=lambda x: -x[3])
        st = {s: sum(x[3] for x in fx if x[0] == s) for s in ('scene', 'v7', 'post')}
        st['video'] = pf.get('video', 0.0)
        st['subtitle'] = pf.get('subtitle', 0.0)
        st['other'] = total - sum(st.values())
        return {'total': round(total, 1), 'stages': {k: round(v, 1) for k, v in st.items()}, 'fx': [x[:3] + [round(x[3], 1)] for x in fx]}

    def _pick_clip(self, ts, label):
        """そのカットの映像クリップのうち、ts を含むもの（いちばん手前）。無ければ（曲の後ろなど）そのカットの最後のクリップ。どちらも無ければ None"""
        for c in reversed(self.video_clips):  # 上のトラックから。cut の無いクリップ（画面から置いた画像など）は時刻だけで選ぶ
            if (c.get('cut') is None or str(c.get('cut')) == label) and c['start'] <= ts < c['start'] + c['dur']:
                return c
        vs = [c for c in self.video_clips if str(c.get('cut')) == label]
        return vs[-1] if vs else None

    def scene_active(self, c, t, label, vclip):
        """'scene' 段のエフェクトのクリップが、カット label の絵にかかるか。クリップの頭（終わり）が場面の映像クリップの頭（終わり）と
        同じなら、場面が映っているかぎり（前後の切り替えの途中も）かかる"""
        if c.get('cut') is not None and str(c['cut']) != str(label):
            return False
        s, e = c['start'], c['start'] + c['dur']
        if vclip is not None:
            vs, ve = vclip['start'], vclip['start'] + vclip['dur']
            if abs(s - vs) < 1e-6:
                s = -math.inf
            if abs(e - ve) < 1e-6:
                e = math.inf
        return s <= t < e

    def _scene(self, ctx, label, ts):
        """カット label の場面の絵（float32）：映像クリップ（カメラ込み）＋ 'scene' 段のエフェクト（処理の順）"""
        c = self._pick_clip(ts, label)
        if c is None:
            img, ctx.view = np.zeros((self.H, self.W, 3), np.uint8), None
        else:
            img = self._timed('video', self._clip_frame, c, ts - c['start'], ctx.cam)
            ctx.view = getattr(self.video(c), 'view', None)
        f = img.astype(np.float32)
        if self.has_scene:
            for e in self.effect_clips:
                mod = self.effect(e['effect'])
                if getattr(mod, 'STAGE', 'v7') == 'scene' and self.scene_active(e, ctx.t, label, c):
                    f = self._timed(('fx', 'scene', e['effect'], e.get('id')), mod.apply, ctx, f, e)
        return f

    def scene_frame(self, t, label):
        """カット label の場面の絵（float32、t の時刻）。切り替えのエフェクト（前の場面と次の場面を混ぜる）が使う。
        カメラ（camera()）もそのカットとして決める（場面ごとのつつき・揺れ）"""
        ctx = Ctx(self, t, t, str(label))
        ctx.cam = self.camera(ctx)
        return self._scene(ctx, str(label), t)

    def render(self, t, prof=None):
        """時刻 t の1コマ（uint8, H×W×3）。prof に dict を渡すと、計測の結果（_prof_summary の形）をそこに入れる"""
        if prof is None:
            return self._render(t)
        self._prof = {}
        t0 = time.perf_counter()
        try:
            return self._render(t)
        finally:
            prof.update(self._prof_summary(self._prof, (time.perf_counter() - t0) * 1000))
            self._prof = None

    def _render(self, t):
        self._frame_no += 1
        self.used_draft = False  # 下描きの絵（Blender の 3D の下描き）を使ったか（blender.layer が立てる。fcache はそのコマをためない）
        if self.frame_time:  # 時刻をコマ番号から（区間に分けた書き出しでも n / fps と同じ小数に）
            t = round(t * self.fps) / self.fps
        cut = self.cut_at(t)
        label = str(cut['label'])
        ts = max(self.source_time(t), cut['start']) if t < self.song_end else t
        ctx = Ctx(self, t, ts, label)
        ctx.cam = self.camera(ctx)
        self._tick()
        if self.has_scene:  # 場面の絵（'scene' 段のエフェクト込み）
            img = self._scene(ctx, label, ts)
        else:
            # 映像：そのカットの映像クリップのうち、ts を含むもの（いちばん手前）
            c = self._pick_clip(ts, label)
            img = self._timed('video', self._clip_frame, c, ts - c['start'], ctx.cam) if c is not None else np.zeros((self.H, self.W, 3), np.uint8)
        f = img
        if t < self.song_end:
            f = img.astype(np.float32)
            for c in self.effect_clips:
                mod = self.effect(c['effect'])
                if getattr(mod, 'STAGE', 'v7') == 'v7' and self.active(c, t, label):
                    self._tick()
                    f = self._timed(('fx', 'v7', c['effect'], c.get('id')), mod.apply, ctx, f, c)
            f = np.clip(f, 0, 255).astype(np.uint8)
        else:
            f = np.clip(f, 0, 255).astype(np.uint8)
        for c in self.effect_clips:
            mod = self.effect(c['effect'])
            if getattr(mod, 'STAGE', 'v7') == 'post' and self.active(c, t, label):
                self._tick()
                f = self._timed(('fx', 'post', c['effect'], c.get('id')), mod.apply, ctx, f, c)
        f = np.ascontiguousarray(f, dtype=np.uint8)
        if self.ass_burn and self.ass_clips:  # 字幕（ASS を ffmpeg の ass で焼く。書き出しはエンコードの ffmpeg でまとめて焼く）
            from . import ass
            f = self._timed('subtitle', ass.burn, self, f, int(round(t * self.fps)))
        return f
