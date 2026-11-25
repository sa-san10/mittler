# -*- coding: utf-8 -*-
"""ビート演出（beatfx）の部品：拍の時計（打点の包絡 env・横揺れ・色ずれ）と、絵の受け渡し・字の層・★ の絵の共通の道具。
bfx_* のエフェクトが使う（作品の effects/_lib/ に写して、エフェクトの頭で sys.path に足して読む）。

元：作者のダンス動画（Attention）の OVERDRIVE 版（2026-10-14。再現セットのスクリプトの、
上端の鏡写しと暗転のカメラの跳びを直した版）の beat_envelope・sway_dx・ca_dx・get_star_sprite と、
lyrics_fx の _outline_img・Sprite・blit・over（計算はそのまま）。語彙は references/演出語彙_ビート演出（rim・radial・anamorph・vignette・dutch・shockwave・env）。

拍の時計（タイムラインの settings.beatfx。無ければタイムラインの拍のメタデータ）：
  song_t0   画面の 0 秒の曲の秒（あれば時刻はぜんぶ曲の秒＝song_t0 + コマ番号 / fps。params の時刻も曲の秒）
  beats     拍の表（root からの JSON {"beats": [曲の秒…]}）, beat_shift（拍をずらす秒）
  hits      強いヒット（曲の秒。いちばん近い拍）, extra（[[曲の秒, "hit"|"bar"|"beat"]]：拍から外れた1発。拍の並びに足す）
  bar_phase 小節の頭（拍の番号 % 4 == bar_phase）, main_end（曲の秒。ここから後ろは打点なし）, mute（[[曲の秒, 曲の秒]]：打点なし）
  decay（0.20 秒）, hit_boost（1.65）, bar_boost（1.28）, faces（root からの顔の表 {コマ: {"faces": [[x, y, w, h, …]]}}。コマはタイムラインの fps）
  env：拍から decay 秒で (1 − τ/decay)² で減る。強いヒットは hit_boost 倍、小節の頭は bar_boost 倍。
マスター書き出し（ctx.scale・60fps）：px は S 倍（各エフェクト）。拍の番号・乱数は時刻から、顔の表・マットはタイムラインの fps のコマ（frame）で読む。
"""
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

_VERSION = object()


def lib():
    """エフェクトから呼ぶ入口：このファイルを直していたら読み直して、このモジュールを返す"""
    import importlib
    import sys
    st = sys.modules.setdefault('_beatfx_lib_state', type(sys)('_beatfx_lib_state'))
    mt = Path(__file__).stat().st_mtime_ns
    old = getattr(st, 'mt', None)
    st.mt = mt
    if old is not None and old != mt:
        importlib.reload(sys.modules[__name__])
    return sys.modules[__name__]


# ====================================================================== 時刻・コマ ==
def cfg(ctx):
    return ctx.settings.get('beatfx') or {}


def scale(ctx):
    return getattr(ctx, 'scale', 1)


def tl_fps(ctx):
    return getattr(ctx.eng, 'tl_fps', ctx.fps)


def song_t(ctx):
    """曲の秒（settings.beatfx.song_t0 があれば song_t0 + コマ番号 / fps＝元の t0 + k / FPS と同じ式。無ければ画面の秒）"""
    c = cfg(ctx)
    if 'song_t0' in c:
        return c['song_t0'] + ctx.fi / ctx.fps
    return ctx.t


def frame(ctx):
    """タイムラインの fps のコマ番号（いつもは ctx.fi。60fps のときはその時刻に映っている 30fps のコマ＝切り捨て）"""
    f0 = tl_fps(ctx)
    if f0 == ctx.fps:
        return ctx.fi
    return int(math.floor(ctx.fi * f0 / ctx.fps + 1e-6))


def pic(ctx, f):
    """エンジンの絵（0〜255）→ 0〜1。前のエフェクトが 0〜1 の絵を ctx.attn_carry で渡していれば（Attention の attn_*・bfx_*）、その小数の絵
    （切っていない・丸めていない）をそのまま使う（元の OVERDRIVE は 0〜1 の小数のまま全部の段を通していたので、間で 0〜255 に戻すと丸め・切りがずれる）"""
    c = getattr(ctx, 'attn_carry', None)
    if c is not None and c[0] is f and np.array_equal(f, c[2]):
        return c[1]
    return f / 255.0


def unpic(ctx, out):
    """0〜1 の絵 → エンジンへ返す絵（+0.5 してある＝エンジンの切り捨てで四捨五入。Attention の pic_out と同じ）。0〜1 の絵は ctx.attn_carry に残す"""
    f = out * 255.0 + 0.5
    ctx.attn_carry = (f, out, f.copy())
    return f


# ====================================================================== 拍の時計 ==
class Clock:
    """拍・強さ（0＝ふつう・1＝小節の頭・2＝強いヒット）・打点の包絡。元の lyrics_fx.Ctx の sway_beats・sway_amp と beat_envelope の写し"""
    def __init__(self, ctx):
        c = cfg(ctx)
        self.t0 = c.get('song_t0', 0.0)
        self.fps0 = tl_fps(ctx)
        if c.get('beats'):
            b = np.asarray(json.loads((ctx.root / c['beats']).read_text(encoding='utf-8'))['beats'])
            beats = b + c.get('beat_shift', 0.0)
            bar_phase = c.get('bar_phase', 0)
            hits = {int(np.argmin(np.abs(beats - h))) for h in c.get('hits', [])}
            lv = np.array([2 if i in hits else 1 if i % 4 == bar_phase else 0 for i in range(len(beats))], np.int32)
        else:   # タイムラインの拍のメタデータ（画面の秒、[秒, 小節の頭, 強さ]。強さ 1.5 以上を強いヒットに）
            items = list(ctx.beats.b) if hasattr(ctx.beats, 'b') else [[x, 0, 1.0] for x in ctx.beats.t]
            beats = np.asarray([float(x[0]) for x in items], np.float64)
            lv = np.array([2 if (len(x) > 2 and x[2] >= 1.5) else 1 if (len(x) > 1 and x[1]) else 0 for x in items], np.int32)
            hits = {int(np.argmin(np.abs(beats - h))) for h in c.get('hits', [])} if len(beats) else set()
            for i in hits:
                lv[i] = 2
        if c.get('extra'):   # 拍から外れた1発（元の sway_extra。拍の並びに足して、番号もそのあとの並びで数える）
            KIND = {'hit': 2, 'bar': 1, 'beat': 0}
            tb = np.concatenate([beats, [float(e[0]) for e in c['extra']]])
            tl = np.concatenate([lv, [KIND.get(e[1], 2) if isinstance(e[1], str) else 2 for e in c['extra']]]).astype(np.int32)
            o = np.argsort(tb, kind='stable')
            beats, lv = tb[o], tl[o]
        self.beats, self.level = beats, lv
        me = c.get('main_end')
        self.n_main = int(round((me - self.t0) * self.fps0)) if me is not None else None
        self.mute = [tuple(m) for m in c.get('mute', [])]
        self.decay = c.get('decay', 0.20)
        self.hit_boost, self.bar_boost = c.get('hit_boost', 1.65), c.get('bar_boost', 1.28)
        fp = c.get('faces')
        self.faces = {int(k): v for k, v in json.loads((ctx.root / fp).read_text(encoding='utf-8')).items()} if fp and (ctx.root / fp).exists() else {}

    def main(self, k):
        return self.n_main is None or k < self.n_main

    def index(self, t):
        return int(np.searchsorted(self.beats, t + 1e-6)) - 1

    def env(self, t, k):
        """(env, 強いヒットか, 拍の番号)。元の beat_envelope と同じ（打点なしの区間は (0, False, 0)）"""
        if not self.main(k):
            return 0.0, False, 0
        if any(a <= t < b for a, b in self.mute):
            return 0.0, False, 0
        i = self.index(t)
        if i < 0:
            return 0.0, False, 0
        tau = t - self.beats[i]
        if tau >= self.decay:
            return 0.0, False, i
        env = float((1.0 - tau / self.decay) ** 2.0)
        is_hit = bool(self.level[i] == 2)
        is_bar = bool(self.level[i] >= 1)
        boost = self.hit_boost if is_hit else (self.bar_boost if is_bar else 1.0)
        return env * boost, is_hit, i

    def face(self, k):
        """コマ k の最初の顔 [x, y, w, h]（タイムラインの大きさの px）か None"""
        fs = self.faces.get(k, {}).get('faces', [])
        return fs[0][:4] if fs else None


def clock(ctx):
    key = ('bfx_clock', json.dumps(cfg(ctx), sort_keys=True, default=str), tl_fps(ctx))
    c = ctx.cache.get(key)
    if c is None or getattr(c, 'version', None) is not _VERSION:
        c = ctx.cache[key] = Clock(ctx)
        c.version = _VERSION
    return c


def sway_amps(p):
    """横揺れの強さ（px、強さ 0/1/2 の順）と色ずれの強さ（px）"""
    return ((p.get('px', 14), p.get('bar_px', 19), p.get('hit_px', 24)),
            (p.get('ca_px', 6.0), p.get('ca_bar_px', 9.0), p.get('ca_hit_px', 12.0)))


def sway_dx(C, p, t, k):
    """横揺れの px（タイムラインの大きさ。元の Ctx.sway_dx：拍ごとに左右交互、decay 秒で (1 − τ/decay)^curve で戻る）"""
    if not C.main(k):
        return 0.0
    i = C.index(t)
    if i < 0:
        return 0.0
    tau = t - C.beats[i]
    dec = p.get('decay', 0.18)
    if tau >= dec:
        return 0.0
    sgn = (1 if i % 2 == 0 else -1) if p.get('alternate', True) else 1
    return float(sgn * np.float32(sway_amps(p)[0][C.level[i]]) * (1 - tau / dec) ** p.get('curve', 2.0))


def ca_dx(C, p, t, k):
    """色ずれの px（元の Ctx.ca_dx。R を +dx、B を −dx）"""
    if not p.get('ca', True) or not C.main(k):
        return 0.0
    i = C.index(t)
    if i < 0:
        return 0.0
    tau = t - C.beats[i]
    dec = p.get('ca_decay', p.get('decay', 0.18))
    if tau >= dec:
        return 0.0
    amp = float(np.float32(sway_amps(p)[1][C.level[i]]))
    sgn = (1 if i % 2 == 0 else -1) if p.get('alternate', True) else 1
    return float(sgn * amp * (1 - tau / dec) ** p.get('ca_curve', p.get('curve', 2.0)))


def sway_max(C, p):
    """いちばん大きい横揺れ（px、タイムラインの大きさ）"""
    a = sway_amps(p)[0]
    return float(max(np.float32(a[v]) for v in set(C.level.tolist()))) if len(C.level) else 0.0


# ====================================================================== 字の層（Attention の字の層があれば） ==
def text_layer(ctx, create=False):
    """そのコマの前の字の層（Attention の ctx.attn_layers）か None。★ と文字のショックウェーブはここに描く。
    create＝True：まだ無ければ、作品に Attention の部品（attention_fx）があれば層を作る（字の合成・粒・ショックウェーブといっしょになる）"""
    L = getattr(ctx, 'attn_layers', None)
    if L is None and create:
        import sys
        af = sys.modules.get('attention_fx')
        if af is not None:
            L = af.lib().layers(ctx)
    return L


def text_flash(ctx):
    L = text_layer(ctx)
    return float(getattr(L, 'flash', 0.0)) if L is not None else 0.0


def rows3(n, s, phase=1):
    """走査線の行（元は [phase::3]）。s 倍のキャンバスは s 行ずつ（3s 行に s 行）"""
    if s == 1:
        return slice(phase, None, 3)
    r = np.arange(n)
    return r[(r // s) % 3 == phase]


# ====================================================================== 絵の道具（lyrics_fx の写し） ==
def over(dst, src, x0=0, y0=0):
    """premultiplied src over dst (in place) at integer offset, clipped."""
    h, w = src.shape[:2]
    X0, Y0 = max(0, x0), max(0, y0)
    X1, Y1 = min(dst.shape[1], x0 + w), min(dst.shape[0], y0 + h)
    if X1 <= X0 or Y1 <= Y0:
        return
    s = src[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    d = dst[Y0:Y1, X0:X1]
    d *= (1 - s[..., 3:4])
    d += s


def pm(img):
    a = np.asarray(img.convert("RGBA"), np.float32) / 255.0
    a[..., :3] *= a[..., 3:4]
    return a


class Sprite:
    def __init__(self, img, cx, cy):
        self.p = pm(img) if isinstance(img, Image.Image) else img
        self.cx, self.cy = cx, cy
        self.w, self.h = self.p.shape[1], self.p.shape[0]


def blit(canvas, spr, x, y, scale=1.0, rot=0.0, alpha=1.0, sx=1.0, sy=1.0):
    """Place sprite anchor (cx, cy) at (x, y), scaled/rotated (deg, ccw) about the anchor."""
    if alpha <= 0.003 or scale <= 0.01 or abs(sx) <= 0.01 or abs(sy) <= 0.01:
        return
    CH, CW = canvas.shape[:2]
    th = math.radians(rot)
    c, s = math.cos(th), math.sin(th)
    M = np.zeros((2, 3))
    M[:, :2] = np.array([[c, s], [-s, c]]) @ np.diag([scale * sx, scale * sy])
    M[:, 2] = np.array([x, y]) - M[:, :2] @ np.array([spr.cx, spr.cy])
    pts = M @ np.array([[0, 0, 1], [spr.w, 0, 1], [spr.w, spr.h, 1], [0, spr.h, 1]], np.float64).T
    x0, y0 = int(math.floor(pts[0].min())) - 1, int(math.floor(pts[1].min())) - 1
    x1, y1 = int(math.ceil(pts[0].max())) + 1, int(math.ceil(pts[1].max())) + 1
    x0c, y0c, x1c, y1c = max(0, x0), max(0, y0), min(CW, x1), min(CH, y1)
    if x1c <= x0c or y1c <= y0c:
        return
    M2 = M.copy()
    M2[:, 2] -= [x0c, y0c]
    if (abs(scale - 1) < 1e-4 and abs(rot) < 1e-4 and sx == 1.0 and sy == 1.0 and float(M[0, 2]).is_integer()
            and float(M[1, 2]).is_integer()):
        out = np.zeros((y1c - y0c, x1c - x0c, 4), np.float32)
        over(out, spr.p, int(M2[0, 2]), int(M2[1, 2]))
    else:
        out = cv2.warpAffine(spr.p, M2, (x1c - x0c, y1c - y0c), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    if alpha < 1:
        out = out * alpha
    over(canvas, out, x0c, y0c)
    return (x0c, y0c, x1c, y1c)


OUTLINE_SHADOW = (5, 7, 5, 170)   # dx, dy, blur, alpha（lyrics_fx の HUD_SHADOW）


def outline_img(im, stroke_col, stroke=6, glow=None, s=1):
    """透明つきの絵（ふちなし）→ 暗いふち（アルファを広げる）＋やわらかい発光（任意）＋落ち影（lyrics_fx._outline_img の写し。s 倍で影・ぼかしも s 倍）"""
    a = np.asarray(im, np.float32) / 255
    core = a[..., 3]
    if core.max() <= 0:
        return im
    sil = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * stroke + 1, 2 * stroke + 1)))
    sil = cv2.GaussianBlur(sil, (0, 0), 0.7 * s)
    out = np.zeros(a.shape, np.float32)
    sx, sy, sb, sa = OUTLINE_SHADOW
    sx, sy, sb = sx * s, sy * s, sb * s
    sh = np.roll(np.roll(cv2.GaussianBlur(sil, (0, 0), sb), sy, 0), sx, 1) * (sa / 255)
    out[..., 3] = sh
    if glow is not None:
        g = np.clip(cv2.GaussianBlur(sil, (0, 0), 9 * s) * 1.4, 0, 1) * 0.55
        gl = np.zeros_like(out); gl[..., 3] = g; gl[..., :3] = g[..., None] * (np.array(glow, np.float32) / 255)
        over(out, gl)
    st = np.zeros_like(out); st[..., 3] = sil; st[..., :3] = sil[..., None] * (np.array(stroke_col, np.float32) / 255)
    over(out, st)
    fi = np.zeros_like(out); fi[..., 3] = core; fi[..., :3] = a[..., :3] * core[..., None]
    over(out, fi)
    al = out[..., 3:4]
    rgb = np.where(al > 1e-4, out[..., :3] / np.maximum(al, 1e-4), 0)
    return Image.fromarray(np.clip(np.concatenate([rgb, al], -1) * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")


def ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3
