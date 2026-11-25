"""ビートのカメラ（dutch・寄り・顔追従・横揺れ・色ずれ）：できた絵を、拍ごとの横揺れ・ダッチロール（揺れに比例して傾く）・縦のバウンスと脈動ズーム・
区間ごとの寄り（zoom_keys）・顔へのゆるい追従で動かし、最後に色ずれ（R と B を逆向きに。強いヒットは強く）をかける。
画面のふちが見えないように、回転・ずれに見合うだけ寄り（安全ズーム）、それでも顔へ寄せた分で端が空くコマは、顔への寄せを弱める。
params：
  px・bar_px・hit_px（横揺れ 14・19・24）, decay（0.18）, curve（2.0）, alternate（左右交互）, overscan（いつも寄る倍率。null＝いちばん大きい揺れ＋1px から自動）
  ca（色ずれ）, ca_px・ca_bar_px・ca_hit_px（6・9・12）, ca_hit_boost・ca_boost（強いヒット 1.35・ふつう 1.05 倍）
  dutch_deg（揺れがいちばん大きいときの傾き 2.2 度）, bounce（拍の脈動ズーム 0.022）, bounce_px（縦のバウンス 9 px、0.5 秒ごとに上下）
  follow（顔への追従 {x: [画面の真ん中の重み 0.72, 顔の重み 0.28], y: [0.65, 0.35], face_y: 顔の箱の縦の位置 0.85}。顔の表は settings.beatfx.faces。null で追従しない）
  zoom_keys：[{t0, t1, kind, amt, …}]（最初に入った区間だけ。kind：ease_in（dur 秒で ease_out）・decay（dur 秒で 1→0）・sine（dur 秒で山なり）・
    steps（steps の時刻を過ぎるごとに amt ずつ、until まで）・hits（hits の各時刻から dur 秒、(1 − τ/dur)²）・push（区間で u^p）・punch（dur 秒で (1 − τ/dur)^p））
  hold_after_main（settings.beatfx.main_end から後ろ＝暗転は、本編の最後のコマのカメラのまま）
横揺れ・色ずれは Attention の attn_sway の代わり（同じ式。作品に attn_sway があれば apply: false にして値だけ残す）。床の字の粒の場所（Attention の ctx.attn_layers.cover）も
同じカメラで動かす。打点の時計は settings.beatfx（_lib/beatfx.py）。
マスター書き出し（ctx.scale・60fps）：揺れ・バウンス・顔の位置の px を s 倍、顔の表はタイムラインの fps のコマ。動きは 60fps の時刻で。
元：作者のダンス動画（Attention）の OVERDRIVE 版（2026-10-14）のカメラの関数（顔追従・ダッチ・寄り。上端の鏡写しと暗転の跳びは
直した版）と、render_frame の色ずれ（ヒットで倍増）、lyrics_fx の sway_dx・ca_dx。演出語彙 dutch。"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np

_LIB = str(Path(__file__).resolve().parent / '_lib')
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
import beatfx  # noqa: E402

STAGE = 'v7'
META = {'label': 'ビートのカメラ（ダッチ・寄り・色ずれ）', 'label_en': 'Beat camera (Dutch tilt, push-in, color split)','window': {'clip': True}, 'scale_aware': True,
        'params': {'px': {'type': 'number', 'min': 0, 'max': 100, 'step': 1}, 'bar_px': {'type': 'number', 'min': 0, 'max': 100, 'step': 1},
                   'hit_px': {'type': 'number', 'min': 0, 'max': 100, 'step': 1}, 'decay': {'type': 'number', 'min': 0.02, 'max': 1, 'step': 0.01},
                   'curve': {'type': 'number', 'min': 0.5, 'max': 5, 'step': 0.1}, 'alternate': {'type': 'bool'},
                   'ca': {'type': 'bool'}, 'ca_px': {'type': 'number', 'min': 0, 'max': 50, 'step': 0.5},
                   'ca_bar_px': {'type': 'number', 'min': 0, 'max': 50, 'step': 0.5}, 'ca_hit_px': {'type': 'number', 'min': 0, 'max': 50, 'step': 0.5},
                   'ca_hit_boost': {'type': 'number', 'min': 0, 'max': 3, 'step': 0.05}, 'ca_boost': {'type': 'number', 'min': 0, 'max': 3, 'step': 0.05},
                   'dutch_deg': {'type': 'number', 'min': 0, 'max': 15, 'step': 0.1}, 'bounce': {'type': 'number', 'min': 0, 'max': 0.2, 'step': 0.001},
                   'bounce_px': {'type': 'number', 'min': 0, 'max': 60, 'step': 1}, 'follow': {'type': 'json'}, 'zoom_keys': {'type': 'json'},
                   'overscan': {'type': 'number', 'min': 1, 'max': 2, 'step': 0.001}}}


def zoom_key(keys, t, B):
    """区間ごとの寄り（元のカメラの関数の区間別の if/elif）"""
    for z in keys:
        if not (z['t0'] <= t < z['t1']):
            continue
        kd, a = z.get('kind'), z.get('amt', 0.0)
        if kd == 'ease_in':
            return a * B.ease_out(min(1.0, (t - z['t0']) / z['dur']))
        if kd == 'decay':
            return a * max(0.0, 1.0 - (t - z['t0']) / z['dur'])
        if kd == 'sine':
            return a * math.sin(min(1.0, (t - z['t0']) / z['dur']) * math.pi)
        if kd == 'steps':
            step = sum(1 if t >= x else 0 for x in z['steps'])
            return a * step if t < z.get('until', z['t1']) else 0.0
        if kd == 'hits':
            v = 0.0
            for ht in z['hits']:
                if 0.0 <= t - ht < z['dur']:
                    v += a * (1.0 - (t - ht) / z['dur']) ** 2
            return v
        if kd == 'push':
            return a * (((t - z['t0']) / (z['t1'] - z['t0'])) ** z.get('p', 1.5))
        if kd == 'punch':
            return a * (max(0.0, 1.0 - (t - z['t0']) / z['dur']) ** z.get('p', 2))
        return 0.0
    return 0.0


def camera_M(C, p, t, k, env, W, H, s, B):
    """元のカメラの関数（直した版）。W・H はキャンバス（s 倍）の大きさ、t・k はそのコマの曲の秒・タイムラインのコマ"""
    dx = B.sway_dx(C, p, t, k) * s
    dy = 0.0
    z_extra = 1.0
    focus_x, focus_y = W / 2.0, H / 2.0
    fc = C.face(k)
    fo = p.get('follow', {'x': [0.72, 0.28], 'y': [0.65, 0.35], 'face_y': 0.85})
    if fc is not None and fo:
        fx, fy, fw, fh = (v * s for v in fc)
        focus_x = fo['x'][0] * (W / 2.0) + fo['x'][1] * (fx + fw / 2.0)
        focus_y = fo['y'][0] * (H / 2.0) + fo['y'][1] * (fy + fh * fo.get('face_y', 0.85))
    if C.main(k):
        z_extra += p.get('bounce', 0.022) * min(1.2, env)
        dy += p.get('bounce_px', 9.0) * s * min(1.0, env) * (1 if int(t * 2) % 2 == 0 else -1)
        z_extra += zoom_key(p.get('zoom_keys', []), t, B)
    rot_deg = 0.0
    mx = B.sway_max(C, p)
    if abs(dx) > 0.4 * s:
        rot_deg = (dx / max(1.0 * s, mx * s)) * p.get('dutch_deg', 2.2)
    th = math.radians(rot_deg)
    c, sn = math.cos(th), math.sin(th)
    zoom = p.get('overscan') or (1 + 2 * (mx + 1) / (W / s))
    z_total = zoom * z_extra
    z_safe = max(z_total, abs(c) + (H / W) * abs(sn) + 2.0 * abs(dx) / W + 2.0 * abs(dy) / H + 0.01)

    def _M(fx_, fy_):
        return np.array([
            [z_safe * c, -z_safe * sn, (W / 2.0) + dx - (z_safe * c * fx_ - z_safe * sn * fy_)],
            [z_safe * sn,  z_safe * c, (H / 2.0) + dy - (z_safe * sn * fx_ + z_safe * c * fy_)]
        ], np.float64)

    def _covers(Mx):
        inv = cv2.invertAffineTransform(Mx)
        pts = np.array([[0, 0, 1], [W, 0, 1], [0, H, 1], [W, H, 1]], np.float64)
        src = pts @ inv.T
        return bool((src[:, 0] >= -0.5).all() and (src[:, 0] <= W + 0.5).all()
                    and (src[:, 1] >= -0.5).all() and (src[:, 1] <= H + 0.5).all())

    M = _M(focus_x, focus_y)
    if not _covers(M):   # fix 版：端が空くコマは、顔への寄せの強さを端が空かない最大まで下げる（二分探索）
        lo, hi = 0.0, 1.0
        for _ in range(20):
            mid = (lo + hi) / 2
            if _covers(_M(W / 2.0 + mid * (focus_x - W / 2.0), H / 2.0 + mid * (focus_y - H / 2.0))):
                lo = mid
            else:
                hi = mid
        M = _M(W / 2.0 + lo * (focus_x - W / 2.0), H / 2.0 + lo * (focus_y - H / 2.0))
    return M.astype(np.float32)


def apply(ctx, f, clip):
    B = beatfx.lib()
    p = clip.get('params', {})
    C = B.clock(ctx)
    s = B.scale(ctx)
    t, k = B.song_t(ctx), B.frame(ctx)
    env, is_hit, _ = C.env(t, k)
    H, W = f.shape[:2]
    if C.main(k):
        M = camera_M(C, p, t, k, env, W, H, s, B)
    else:   # fix 版：暗転のあいだは本編の最後のコマのカメラを保つ
        kl = C.n_main - 1
        tl = C.t0 + kl / C.fps0
        e_l = C.env(tl, kl)[0]
        M = camera_M(C, p, tl, kl, e_l, W, H, s, B)
    out = cv2.warpAffine(B.pic(ctx, f), M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    L = B.text_layer(ctx)
    if L is not None and getattr(L, 'cover', None) is not None and L.cover.max() > 0:
        L.cover = cv2.warpAffine(L.cover, M, (W, H), flags=cv2.INTER_LINEAR)
    ca = B.ca_dx(C, p, t, k) * s
    if abs(ca) > 0.05 * s:
        cb = ca * (p.get('ca_hit_boost', 1.35) if is_hit else p.get('ca_boost', 1.05))
        for ch, d in ((0, cb), (2, -cb)):
            Mc = np.float32([[1, 0, d], [0, 1, 0]])
            out[..., ch] = cv2.warpAffine(np.ascontiguousarray(out[..., ch]), Mc, (W, H), flags=cv2.INTER_LINEAR,
                                          borderMode=cv2.BORDER_REFLECT)
    return B.unpic(ctx, out)
