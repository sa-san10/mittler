"""光とトーンマップ（偽マリアのエフェクト集）：下の絵をリニアに戻して明るい所を伸ばす → 光を足す（キラ・ラメ・はじけるラメ）→ ブルーム →
トーンマップ（Hable）→ sRGB → 全体の彩度。映画のような光の伸びと、明るい所のキラキラ。
params：exposure（露出）, sat（全体の彩度）, k（明るい所の伸ばし方）, mode（hable / aces / clip）, sparkle（後乗せのキラキラを出すか）, stage（ステージ用の多めのキラキラ）,
light（{glints, glint_size, glint_amt, glitter, glitter_amt, light_gain, bloom}）, bursts（[{t, x, y, n, amt}]：その時刻に (x, y) でラメがはじける）。
params に無いものは、タイムラインの settings.tonemap（mode, exposure, k, sat）と settings.sparkle を見る。
元は偽マリアMV（effects_lib/maria/light.py）。部品にするときに、作品の顔の検出の結果（work/fx/survey）を読む所を外し（キラは顔もよけずに置く）、
ラメの乱数の種をプロセスによらない決まった値（カットの名前の CRC32）にし、露出・彩度などを params でも決められるようにした。
ドラフト品質（ctx.draft）：リニアへの変換を 256 段の表で、ブルームのガウシアン 2 回を 1/4 の大きさで、光を何も足さないときは 0 を足す変換を省く。
マスター書き出し（ctx.scale）：ブルームのぼかし（σ 14・40 px）に ctx.scale を掛ける。後乗せのキラキラは、4K のキャンバスではタイムラインの大きさで描いて s 倍に広げて足す。"""
import zlib

import cv2
import numpy as np

from mittler.lib import look

STAGE = 'v7'
DOC_EN = """Light and tone map (False Maria effects): converts the picture below to linear light and expands the highlights -> adds light (glints, glitter,
glitter bursts) -> bloom -> tone map (Hable) -> sRGB -> overall saturation. A filmic glow with sparkles on the bright spots.
params: exposure, sat (overall saturation), k (how much highlights are expanded), mode (hable / aces / clip), sparkle (add the sparkles), stage (more sparkles, for stage shots),
light ({glints, glint_size, glint_amt, glitter, glitter_amt, light_gain, bloom}), bursts ([{t, x, y, n, amt}]: glitter bursting at (x, y) at time t).
Anything not in params falls back to the timeline's settings.tonemap (mode, exposure, k, sat) and settings.sparkle.
From the False Maria MV."""
META = {'label': '光とトーンマップ（偽マリア）', 'label_en': 'Light and tone map (False Maria)', 'draft': True, 'scale_aware': True,
        'params': {'exposure': {'type': 'number', 'min': 0.5, 'max': 5, 'step': 0.05}, 'sat': {'type': 'number', 'min': 0, 'max': 2, 'step': 0.01},
                   'mode': {'type': 'choice', 'choices': ['hable', 'aces', 'clip']}, 'sparkle': {'type': 'bool'}, 'stage': {'type': 'bool'}},
        'defaults': {'exposure': 2.2, 'sat': 1.12, 'mode': 'hable', 'sparkle': True, 'stage': False}, 'dur': 3}


def apply(ctx, f, clip):
    conf = clip.get('params', {})
    t, fi, cut = ctx.t, ctx.sfi, ctx.cut
    lv = ctx.level()
    tm = dict(ctx.settings.get('tonemap', {'mode': 'hable', 'exposure': 2.2, 'k': 0.75}))
    for k_ in ('mode', 'exposure', 'k', 'sat'):  # params があればそちら（無ければタイムラインの settings.tonemap）
        if conf.get(k_) is not None:
            tm[k_] = conf[k_]
    dr = getattr(ctx, 'draft', False)
    if dr:  # ドラフト：リニアへの変換を 256 段の表で（入力を 8 ビットに丸める。べき乗の計算を全画素でしない）
        tab = ctx.cache.setdefault('fm_light_draft_lut', {})
        k = tm.get('k', 0.75)
        if k not in tab:
            tab[k] = look.expand(look.srgb_to_lin(np.arange(256, dtype=np.float32) / 255), k).astype(np.float32)
        lin = cv2.LUT(np.clip(f + 0.5, 0, 255).astype(np.uint8), tab[k])
    else:
        lin = look.expand(look.srgb_to_lin(f / 255), tm.get('k', 0.75))
    s = getattr(ctx, 'scale', 1)  # マスター書き出しの倍率（いつもは 1）
    # 後乗せのキラキラを描く絵と大きさ（いつもは f と画面そのもの。4K のキャンバスではタイムラインの大きさに縮めた絵で描いて、あとで s 倍に広げる）
    fs, Ws, Hs = f, ctx.W, ctx.H
    sp = conf.get('sparkle', ctx.settings.get('sparkle', True))  # 後乗せのキラキラ（光の点・ラメ・はじけるラメ）。false で全部やめる
    if s != 1 and sp:
        Ws, Hs = ctx.eng.W0, ctx.eng.H0
        fs = cv2.resize(np.ascontiguousarray(f, np.float32), (Ws, Hs), interpolation=cv2.INTER_AREA)
    add = np.zeros_like(fs)
    L = conf.get('light') or {}
    stage = conf.get('stage', False)
    beat = ctx.beats.pulse(t, 0.18) * lv
    n = int(L.get('glints', 30 if stage else 8) * (0.4 + 0.6 * lv)) if sp else 0
    if n > 0:
        pts = look.find_highlights(fs, n=n, thr=0.86 if stage else 0.92, min_dist=36 if stage else 70)
        add = look.glints(add, fi, t, pts, size=L.get('glint_size', 30 if stage else 22) * (0.8 + 0.4 * lv),
                          amt=L.get('glint_amt', 1.0 if stage else 0.6), beat=beat)
    ng = int(L.get('glitter', 160 if stage else 60) * (0.35 + 0.65 * lv)) if sp else 0
    if ng > 0:
        glit = ctx.cache.setdefault('fm_light_glitter', {})
        key = (cut, ng, Ws, Hs, stage)
        if key not in glit:  # 種はカットの名前から決まる値（hash() はプロセスごとに変わるので使わない）
            glit[key] = look.Glitter(Ws, Hs, n=ng, seed=zlib.crc32(str(cut).encode('utf-8')) & 0xffff, size=(3, 8) if stage else (2, 6))
        add = glit[key].draw(add, t, amt=L.get('glitter_amt', 1.0 if stage else 0.55), beat=beat * 0.6)
    for b in ((conf.get('bursts') or []) if sp else []):  # 強い拍でラメがはじける
        add = look.burst(add, t, b['t'], b['x'], b['y'], n=b.get('n', 70), seed=int(b['t'] * 100), amt=b.get('amt', 1.0))
    if fs is not f:  # 4K：タイムラインの大きさで描いた光を s 倍に広げる
        add = cv2.resize(add, (ctx.W, ctx.H), interpolation=cv2.INTER_LINEAR)
    damp0 = float(np.clip(1.0 - (float(f.mean()) / 255 - 0.45) * 2.0, 0.35, 1.0))
    drew = n > 0 or ng > 0 or (bool(conf.get('bursts')) and sp)  # 光を足したか（足していなければ add は 0 のまま）
    if not (dr and not drew):  # ドラフトで何も足していなければ、0 を足すだけの計算（リニアへの変換）を省く（絵は同じ）
        lin = lin + look.srgb_to_lin(np.clip(add, 0, 255) / 255) * L.get('light_gain', 2.2) * damp0
    # ブルーム（リニア）。白っぽい場面ではにじみを弱める
    bright = float(f.mean()) / 255
    damp = float(np.clip(1.0 - (bright - 0.45) * 2.5, 0.2, 1.0))
    bl = L.get('bloom', 0.10 + 0.10 * lv) * damp
    if bl:
        hi = np.clip(lin - 1.0, 0, None)
        if dr:  # ドラフト：1/4 の大きさで σ も 1/4 にしてぼかし、戻す
            h, w = hi.shape[:2]
            sm = cv2.resize(hi, (max(1, w // 4), max(1, h // 4)), interpolation=cv2.INTER_AREA)
            b = cv2.resize(cv2.GaussianBlur(sm, (0, 0), 14 * s / 4) + cv2.GaussianBlur(sm, (0, 0), 40 * s / 4) * 0.7, (w, h), interpolation=cv2.INTER_LINEAR)
        else:
            b = cv2.GaussianBlur(hi, (0, 0), 14 * s) + cv2.GaussianBlur(hi, (0, 0), 40 * s) * 0.7  # σ はタイムラインの px（4K では s 倍）
        lin = lin + b * bl * np.array((1.0, 0.85, 0.95), np.float32)
    mode = tm.get('mode', 'hable')
    if mode == 'hable':
        out = look.tm_hable(lin, exposure=tm.get('exposure', 2.2))
    elif mode == 'aces':
        out = look.tm_aces(lin, exposure=tm.get('exposure', 0.75))
    else:
        out = np.clip(lin, 0, 1)
    out = look.lin_to_srgb(out) * 255
    sat = tm.get('sat', 1.0)
    if sat != 1.0:
        y = out @ np.array([0.299, 0.587, 0.114], np.float32)
        out = np.clip(y[..., None] + (out - y[..., None]) * sat, 0, 255)
    return out
