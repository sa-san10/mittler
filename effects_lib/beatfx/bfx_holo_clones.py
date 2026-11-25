"""分身ホログラム：人のマスク（ctx.m）で切り抜いた本人を、色をつけた半透明の分身（走査線・ふちの光つき）にして、本人の後ろに並べる。
1人のダンスを3人にしたり、刻みに合わせて左右に残像を出したり、ヒットで背後に大きなオーラを広げたりする。
params：
  clones：[{t0, t1, dx, dy, scale, tint, alpha, slide, fade_end, fade, grow, grow_dur, rise}]（上から順に重ねる。時刻は settings.beatfx.song_t0 があれば曲の秒）
    dx・dy（px、画面の真ん中からのずれ）, scale（真ん中まわりの大きさ）, tint（[r, g, b] 0〜1）, alpha（濃さ）,
    slide（秒：出るとき dx を 0 から ease_out でのばす）, fade_end（秒：t1 の前のこの秒で消える）, fade（秒：出てから直線で消える）,
    grow・grow_dur（大きさを scale から scale＋grow まで ease_out で）, rise（px：grow_dur の間に dy を 0 からこれまで直線で）
  groups：[[t0, t1], …] の区間は、clones の中のその区間のものだけ（その区間では wings を出さない）。区間の外の clones は描かない
  wings：{thr（0.75）, dx（42）, scale（1.02）, tints（[[左], [右]]）, gain（0.65）, max（0.32）}：区間の外で打点（env）が thr を超えたら左右にうっすら残像
  band（[上, 下] px）：上下の帯のところには描かない
人のマスクのトラックより上に置く（needs matte）。打点の時計は settings.beatfx（_lib/beatfx.py）。
マスター書き出し（ctx.scale）：dx・dy・rise・ふちの太さ・走査線・帯を s 倍。ドラフト（ctx.draft）：ふちの光を省く。
元：作者のダンス動画（Attention）の OVERDRIVE 版（2026-10-14）の分身の関数（THREE OF US で踊る人が3人に・TRANS- の刻みの残像・
ALL YOU NEED のオーラ・強い拍のウィング）。"""
import sys
from pathlib import Path

import cv2
import numpy as np

_LIB = str(Path(__file__).resolve().parent / '_lib')
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
import beatfx  # noqa: E402

STAGE = 'v7'
META = {'label': '分身ホログラム', 'label_en': 'Hologram clones','window': {'clip': True}, 'needs': ['matte'], 'scale_aware': True, 'draft': True,
        'params': {'clones': {'type': 'json'}, 'groups': {'type': 'json'}, 'wings': {'type': 'json'}, 'band': {'type': 'json'}}}


def clone_list(p, t, env, B):
    """そのコマの分身 [(dx, dy, scale, tint, alpha)]（元の分身の関数の if/elif と同じ選び方）"""
    groups = p.get('groups', [])
    g = next((gr for gr in groups if gr[0] <= t < gr[1]), None)
    out = []
    if g is not None:
        for c in p.get('clones', []):
            if not (c['t0'] <= t < c['t1']) or not (g[0] <= c['t0'] < g[1]):
                continue
            tau = t - c['t0']
            dx, dy, sc, al = c.get('dx', 0), c.get('dy', 0), c.get('scale', 1.0), c.get('alpha', 0.5)
            if c.get('slide'):
                u = B.ease_out(min(1.0, tau / c['slide']))
                dx = (1 if dx >= 0 else -1) * int(abs(dx) * u)
            if c.get('fade_end'):
                al = al * min(1.0, (c['t1'] - t) / c['fade_end'])
            if c.get('fade'):
                al = al * (1 - tau / c['fade'])
            if c.get('grow_dur'):
                u = tau / c['grow_dur']
                sc = sc + c.get('grow', 0.0) * B.ease_out(u)
                dy = c.get('rise', 0.0) * u
                al = c.get('alpha', 0.5) * (1.0 - u)
            out.append((dx, dy, sc, np.array(c.get('tint', [1, 1, 1]), np.float32), al))
        return out
    w = p.get('wings')
    if w and env > w.get('thr', 0.75):
        a_w = min(w.get('max', 0.32), (env - w.get('thr', 0.75)) * w.get('gain', 0.65))
        tl, tr = w.get('tints', [[0.0, 0.88, 1.0], [1.0, 0.82, 0.1]])
        out.append((-w.get('dx', 42), 0, w.get('scale', 1.02), np.array(tl, np.float32), a_w))
        out.append((+w.get('dx', 42), 0, w.get('scale', 1.02), np.array(tr, np.float32), a_w))
    return out


def clones(out, m, cl, s, band, draft=False):
    """元の分身の関数の合成（背景に分身、本人のところは薄く）"""
    H, W = m.shape
    person = out * m[..., None]
    bg_comp = out.copy()
    for dx, dy, sc, tint, al in cl:
        if al <= 0.01:
            continue
        dx, dy = dx * s, dy * s
        cx, cy = W / 2.0, H / 2.0
        M = np.float32([[sc, 0, cx + dx - sc * cx], [0, sc, cy + dy - sc * cy]])
        p_w = cv2.warpAffine(person, M, (W, H), flags=cv2.INTER_LINEAR)
        m_w = cv2.warpAffine(m, M, (W, H), flags=cv2.INTER_LINEAR)
        if draft:
            holo = p_w * 0.55 + tint[None, None, :] * 0.45
        else:
            m_edge = cv2.dilate(m_w, np.ones((4 * s + 1, 4 * s + 1), np.uint8)) - cv2.erode(m_w, np.ones((2 * s + 1, 2 * s + 1), np.uint8))
            holo = (p_w * 0.55 + tint[None, None, :] * 0.45) + m_edge[..., None] * tint[None, None, :] * 0.9
        holo[beatfx.rows3(H, s)] *= 0.72
        if band[0]:
            holo[:band[0] * s] = 0
        if band[1]:
            holo[H - band[1] * s:] = 0
        mask_a = np.clip(m_w * al, 0.0, 1.0)[..., None] * (1.0 - m[..., None] * 0.85)
        bg_comp = bg_comp * (1.0 - mask_a * 0.7) + holo * mask_a
    return np.clip(bg_comp, 0.0, 1.0)


def apply(ctx, f, clip):
    B = beatfx.lib()
    p = clip.get('params', {})
    m = ctx.m
    if m is None or m.max() < 0.1:
        return f
    C = B.clock(ctx)
    t, k = B.song_t(ctx), B.frame(ctx)
    if not C.main(k):   # 元は暗転のあいだ人のマスクが無かった（分身は出ない）
        return f
    env = C.env(t, k)[0]
    cl = clone_list(p, t, env, B)
    if not cl:
        return f
    return B.unpic(ctx, clones(B.pic(ctx, f), m, cl, B.scale(ctx), p.get('band', [0, 0]), getattr(ctx, 'draft', False)))
