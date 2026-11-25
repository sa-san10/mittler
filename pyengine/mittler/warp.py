"""映像クリップの時間の付け替え（音ハメ・速さの変化）。
映像クリップの warp は2通り：
- 文字列：表の JSON ファイル（root からの相対。{"table": [[クリップの頭からの秒, 動画の秒], …]}）。表の外は端の値（np.interp）。動画の秒に in を足す（偽マリアMV の取り込み）。
- {"points": [[クリップの頭からの秒, 動画の秒], …], "smooth": 秒, "auto": {…}, "accents": […]}：編集画面で作る・直す。
  点のあいだは直線、点の外は端の傾きでのばす。smooth（既定 0）は幅 smooth の箱で9点の平均（速さの段差をやわらげる。Attention の beatwarp.TimeMap と同じ）。
  動画の秒そのもの（in は足さない）。
編集画面とサーバー（editor/calc.js の warpMap）と同じ計算にしておく（同じことは tools/smoke_same.py が確かめる）。
"""
import json

import numpy as np


class Points:
    def __init__(self, points, smooth=0.0):
        a = sorted((float(t), float(s)) for t, s in points)
        if len(a) == 1:
            a.append((a[0][0] + 1.0, a[0][1] + 1.0))
        self.t = np.array([p[0] for p in a])
        self.s = np.array([p[1] for p in a])
        self.smooth = float(smooth or 0.0)

    def lin(self, t):
        T, S = self.t, self.s
        if t <= T[0]:
            return float(S[0] + (S[1] - S[0]) / (T[1] - T[0]) * (t - T[0]))
        if t >= T[-1]:
            return float(S[-1] + (S[-1] - S[-2]) / (T[-1] - T[-2]) * (t - T[-1]))
        return float(np.interp(t, T, S))

    def __call__(self, t):
        if self.smooth <= 0:
            return self.lin(t)
        hs = self.smooth / 2
        return float(np.mean([self.lin(t + u) for u in np.linspace(-hs, hs, 9)]))


def load(clip, root):
    """-> (f(t) → 動画の秒, in を足すか)。warp が無ければ None"""
    w = clip.get('warp')
    if not w:
        return None
    if isinstance(w, str):
        tab = np.asarray(json.loads((root / w).read_text(encoding='utf-8'))['table'], dtype=np.float64)
        x, y = tab[:, 0], tab[:, 1]
        return (lambda t: float(np.interp(t, x, y))), True
    return Points(w['points'], w.get('smooth', 0.0)), False
