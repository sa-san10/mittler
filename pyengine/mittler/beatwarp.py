# -*- coding: utf-8 -*-
# Mittler（取り込んだときの名前は claude-cut）に取り込んだ写し（元：作者のダンス動画（Attention）の制作の道具 beatwarp.py の「音ハメ」。2026-10-21）。
# 変えたのは cv2 が無いときに uv で opencv を入れに行くところだけ（フレーム差分に切り替える）。編集画面からの使い方は onbeat.py。
"""Beat-synced time remapping ("音ハメ") helpers for assemble.py.

1. motion analysis per clip  -> work/beatwarp/<id>_motion.csv  (+ <id>_motion.png plot)
   - preferred: OpenCV Farneback optical flow with the camera's global affine motion removed
     (run in a throwaway env:  uv run --with opencv-python-headless --with numpy python beatwarp.py analyze clip.mp4 out.csv)
   - fallback (no uv / no cv2): numpy frame difference (no reversal info)
2. accent detection: frames where motion suddenly stops (hit / landing) or reverses direction
3. warp solver: DP that pairs accents with beats in order inside the cut window, keeping every
   segment's speed within [min_speed, max_speed]; output = (song_t, clip_t) anchors
4. mapping: piecewise linear through the anchors (+ optional ramp-in) with a light symmetric
   smoothing so speed changes don't snap
"""
import csv, json, math, os, pathlib, subprocess, sys
import numpy as np

ANALYZE_W = 192            # analysis width (px); height follows aspect
TOP_FRAC = 0.15            # energy = mean of the top 15% residual-flow magnitudes (= the moving limbs)


# ============================================================== analysis ==
def _read_frames_cv2(path, cv2):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frames = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        h, w = fr.shape[:2]
        g = cv2.cvtColor(cv2.resize(fr, (ANALYZE_W, int(round(h * ANALYZE_W / w))), interpolation=cv2.INTER_AREA),
                         cv2.COLOR_BGR2GRAY)
        frames.append(g)
    cap.release()
    return frames, fps


def _remove_global(flow):
    """Fit flow ~ affine(x, y) (camera pan/zoom/tilt) by 2-pass least squares, return residual."""
    h, w = flow.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    X = np.stack([xs.ravel() / w - 0.5, ys.ravel() / h - 0.5, np.ones(h * w, np.float32)], 1)
    F = flow.reshape(-1, 2)
    m = np.ones(len(F), bool)
    for _ in range(2):
        coef, *_ = np.linalg.lstsq(X[m], F[m], rcond=None)
        res = F - X @ coef
        r = np.linalg.norm(res, axis=1)
        m = r <= np.percentile(r, 60)      # refit on the static-ish 60% (background)
    return res.reshape(h, w, 2), coef


def _topmean(v, frac=TOP_FRAC):
    k = max(1, int(len(v) * frac))
    return float(np.mean(np.partition(v, len(v) - k)[-k:]))


def _cos(a, b, mask):
    num = float(np.sum(a[mask] * b[mask]))
    den = math.sqrt(float(np.sum(a[mask] ** 2)) * float(np.sum(b[mask] ** 2))) + 1e-9
    return num / den


def analyze_cv2(path):
    import cv2
    frames, fps = _read_frames_cv2(path, cv2)
    res, E, G = [], [], []
    for a, b in zip(frames, frames[1:]):
        fl = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 13, 3, 5, 1.2, 0)
        r, coef = _remove_global(fl)
        mag = np.linalg.norm(r, axis=2).ravel()
        res.append(r)
        E.append(_topmean(mag))
        G.append(float(np.linalg.norm(coef[2])))
    n = len(frames)
    # cos2[k]: direction agreement of the motion just before frame k (pairs k-2,k-1) vs just after (k, k+1)
    cos2 = [float("nan")] * n
    for k in range(2, n - 2):
        pre, post = res[k - 2] + res[k - 1], res[k] + res[k + 1]
        mp, mq = np.linalg.norm(pre, axis=2), np.linalg.norm(post, axis=2)
        thr = np.percentile(np.maximum(mp, mq), 100 * (1 - TOP_FRAC))
        cos2[k] = _cos(pre, post, np.maximum(mp, mq) >= thr)
    return dict(fps=fps, n=n, E=E, G=G, cos2=cos2, method="flow")


def analyze_numpy(path, probe_fn):
    """Fallback: frame-difference energy (no direction)."""
    info = probe_fn(path)
    w, h = info["w"], info["h"]
    sw, sh = ANALYZE_W, int(round(h * ANALYZE_W / w))
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={sw}:{sh}:flags=area",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    raw = p.stdout.read()
    p.wait()
    fr = np.frombuffer(raw, np.uint8).reshape(-1, sh, sw).astype(np.float32)
    E = [_topmean(np.abs(b - a).ravel()) / 8.0 for a, b in zip(fr, fr[1:])]
    n = len(fr)
    return dict(fps=info["fps"], n=n, E=E, G=[0.0] * (n - 1), cos2=[float("nan")] * n, method="framediff")


def _sig(path):
    st = os.stat(path)
    return f"{st.st_size}:{int(st.st_mtime)}"


def write_motion_csv(m, out, sig):
    with open(out, "w", newline="") as f:
        f.write(f"# sig={sig} fps={m['fps']} n={m['n']} method={m['method']}\n")
        w = csv.writer(f)
        w.writerow(["frame", "t", "E_pair_k_to_k1", "global_flow", "cos2_at_k"])
        for k in range(m["n"]):
            e = m["E"][k] if k < len(m["E"]) else ""
            g = m["G"][k] if k < len(m["G"]) else ""
            w.writerow([k, f"{k / m['fps']:.4f}", e, g, m["cos2"][k]])


def read_motion_csv(path):
    with open(path) as f:
        head = f.readline()
        meta = dict(kv.split("=", 1) for kv in head[1:].split())
        rows = list(csv.DictReader(f))
    n = int(meta["n"])
    E = [float(r["E_pair_k_to_k1"]) for r in rows if r["E_pair_k_to_k1"] != ""]
    G = [float(r["global_flow"]) for r in rows if r["global_flow"] != ""]
    cos2 = [float(r["cos2_at_k"]) for r in rows]
    return dict(sig=meta["sig"], fps=float(meta["fps"]), n=n, E=E, G=G, cos2=cos2, method=meta["method"])


def motion(path, out_dir, tag, probe_fn):
    """Cached motion curves for one clip."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{tag}_motion.csv"
    sig = _sig(path)
    if csv_path.exists():
        try:
            m = read_motion_csv(csv_path)
            if m["sig"] == sig:
                return m
        except Exception:
            pass
    print(f"  beatwarp: analyzing motion of {path.name} ...", flush=True)
    try:
        import cv2  # noqa: F401
        m = analyze_cv2(path)
        write_motion_csv(m, csv_path, sig)
    except ImportError:  # Mittler：uv で opencv を入れに行かない（パッケージを勝手に足さない）。差分だけで調べる
        print("  beatwarp: no cv2; using frame difference", flush=True)
        m = analyze_numpy(path, probe_fn)
        write_motion_csv(m, csv_path, sig)
    return read_motion_csv(csv_path)


# ============================================================== accents ==
def _smooth(x, sigma):
    if sigma <= 0:
        return np.asarray(x, float)
    r = int(math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    xp = np.pad(np.asarray(x, float), r, mode="edge")
    return np.convolve(xp, k, mode="valid")


def detect_accents(m, min_gap=0.22, thr=0.30, rev_weight=0.8, smooth=0.7, skip_head=0.12, abs_min=0.8):
    """abs_min: px/frame (at ANALYZE_W) the motion must reach before a stop/reversal counts (ignores jitter)."""
    """-> (accents [(clip_t, score, kind, frame)], curves dict). score normalized so max = 1 per clip."""
    fps, n = m["fps"], m["n"]
    E = _smooth(m["E"], smooth)                     # pair k = frames k -> k+1
    eref = max(float(np.percentile(E, 90)), 0.15)   # robust "fast" level; floor so still clips don't explode
    stop = np.zeros(n)
    rev = np.zeros(n)
    for k in range(2, n - 1):
        before = E[max(0, k - 3):k].max()
        after = E[k:min(len(E), k + 2)].mean()
        if before >= abs_min:
            stop[k] = max(0.0, (before - after) / eref)
        c = m["cos2"][k] if k < len(m["cos2"]) else float("nan")
        if not math.isnan(c) and k < len(E) and min(E[k - 1], E[k]) >= 0.7 * abs_min:
            rev[k] = max(0.0, -c) * math.sqrt(max(E[k - 1], 0) * max(E[k], 0)) / eref
    score = np.maximum(stop, rev_weight * rev)
    # non-max suppression
    gap = max(1, int(round(min_gap * fps)))
    acc = []
    order = np.argsort(-score)
    taken = np.zeros(n, bool)
    for k in order:
        if score[k] < thr or k < int(skip_head * fps) or k >= n - 1:
            continue
        if taken[max(0, k - gap):k + gap + 1].any():
            continue
        taken[k] = True
        kind = "rev" if rev_weight * rev[k] > stop[k] else "stop"
        ka = int(k)
        if kind == "stop":   # the hit = where the motion has actually come to rest (local min within 3 frames)
            seg = E[k:min(len(E), k + 4)]
            j = int(np.argmin(seg))
            if j and seg[j] < 0.8 * E[k]:
                ka = int(k + j)
        acc.append((ka / fps, float(score[k]), kind, ka))
    acc.sort()
    smax = max([a[1] for a in acc], default=1.0)
    acc = [(t, s / smax, kind, k) for t, s, kind, k in acc]
    return acc, dict(E=E, stop=stop, rev=rev, score=score, eref=eref)


def plot_motion(path_png, cid, m, curves, accents, aligned=None):
    """Small inspection plot (PIL only). aligned: set of accent frames that got used by the warp."""
    from PIL import Image, ImageDraw, ImageFont
    Wp, Hp, L, R, T, B = 1000, 340, 50, 15, 30, 40
    im = Image.new("RGB", (Wp, Hp), (250, 250, 250))
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 14)
    except OSError:
        f = ImageFont.load_default()
    fps, n = m["fps"], m["n"]
    dur = (n - 1) / fps
    X = lambda t: L + (Wp - L - R) * t / max(dur, 1e-6)
    E = curves["E"]
    ymax = max(float(np.max(E)) * 1.1, 1e-6, float(np.max(curves["score"])) * curves["eref"] * 1.05)
    Y = lambda v: Hp - B - (Hp - T - B) * v / ymax
    for s in np.arange(0, dur + 1e-6, 0.25):
        d.line([(X(s), T), (X(s), Hp - B)], fill=(225, 225, 225))
        d.text((X(s), Hp - B + 4), f"{s:.2f}", font=f, fill=(90, 90, 90), anchor="ma")
    d.line([(L, Hp - B), (Wp - R, Hp - B)], fill=(120, 120, 120))
    pts = [(X((k + 0.5) / fps), Y(e)) for k, e in enumerate(E)]
    d.line(pts, fill=(40, 90, 200), width=2)                                # motion energy
    sc = [(X(k / fps), Y(s * curves["eref"])) for k, s in enumerate(curves["score"])]
    d.line(sc, fill=(230, 140, 30), width=1)                                # accent score (scaled)
    for t, s, kind, k in accents:
        used = aligned is not None and k in aligned
        col = (20, 160, 60) if used else (200, 40, 40)
        d.line([(X(t), T), (X(t), Hp - B)], fill=col, width=2 if used else 1)
        d.text((X(t) + 3, T + 2), f"{t:.2f} {kind} {s:.2f}", font=f, fill=col)
    d.text((L, 6), f"{cid}  [{m['method']}]  blue=motion energy  orange=accent score  "
                   f"red/green=accents (green = aligned to a beat in the current EDL)", font=f, fill=(0, 0, 0))
    im.save(path_png)


def write_accents_csv(path, accents):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["clip_t", "frame", "score", "kind"])
        for t, s, kind, k in accents:
            w.writerow([f"{t:.4f}", k, f"{s:.3f}", kind])


# ============================================================== warp solver ==
def ramp_dist(v0, v1, dur):
    """Clip seconds consumed by a ramp v(τ) = v1 + (v0 - v1)(1 - τ/dur)^2 over dur."""
    return dur * (v1 + (v0 - v1) / 3.0)


def solve_warp(cs, ce, accents, grid, start_rng, end_rng, base, vmin, vmax, lam, reward_scale=1.0,
               jerk=1.5, margin=0.05):
    """Pick accent->beat pairs (both increasing) minimizing
         λ Σ seg_dur·ln(v/base)^2  +  jerk Σ ln(v_k/v_{k-1})^2  -  reward Σ score·beat_weight

    cs, ce      song window of the (post-ramp) warp section
    accents     [(clip_t, score, kind, frame)]
    grid        [(song_t, weight)] candidate beat times (weight 1 = beat, <1 = off-beat)
    start_rng   (lo, hi) allowed clip time at cs;  end_rng (lo, hi) allowed clip time at ce
    jerk        penalty on speed changes between consecutive segments (stops 0.6x/1.4x/0.6x zig-zags)
    -> anchors [(song_t, clip_t)] incl. both ends, pairs [(accent, beat_t)], cost
    """
    INF = float("inf")
    lv = lambda v: lam * math.log(v / base) ** 2

    def slope(t0, t1, c0, c1):
        if t1 - t0 <= 1e-6:
            return None
        v = (c1 - c0) / (t1 - t0)
        if v < vmin - 1e-9 or v > vmax + 1e-9 or v <= 0:
            return None
        return v

    beats = [(b, w) for b, w in grid if cs + margin < b < ce - margin]
    acc = [a for a in accents if start_rng[0] - 1e-9 <= a[0] <= end_rng[1] + 1e-9]
    nodes = [(i, j) for i in range(len(acc)) for j in range(len(beats))]
    T = lambda nd: beats[nd[1]][0]
    C = lambda nd: acc[nd[0]][0]
    R = lambda nd: reward_scale * acc[nd[0]][1] * beats[nd[1]][1]

    # edge states: best[(p, q)] = cost of the best path whose last segment is p -> q  (p = "S" for start)
    best, back, v_of, startc = {}, {}, {}, {}
    for q in nodes:
        c0 = min(max(C(q) - base * (T(q) - cs), start_rng[0]), start_rng[1])
        v = slope(cs, T(q), c0, C(q))
        if v is not None:
            best[("S", q)], back[("S", q)], v_of[("S", q)], startc[q] = (T(q) - cs) * lv(v) - R(q), None, v, c0
    for q in sorted(nodes, key=lambda nd: (nd[1], nd[0])):        # increasing beat order
        incoming = [(e, cst) for e, cst in best.items() if e[1] == q]
        for r in nodes:
            if r[0] <= q[0] or r[1] <= q[1]:
                continue
            v = slope(T(q), T(r), C(q), C(r))
            if v is None:
                continue
            seg = (T(r) - T(q)) * lv(v) - R(r)
            for e, cst in incoming:
                tot = cst + seg + jerk * math.log(v / v_of[e]) ** 2
                if tot < best.get((q, r), INF):
                    best[(q, r)], back[(q, r)], v_of[(q, r)] = tot, e, v

    # empty path: base speed, end pinned -> back-solve start
    c0 = start_rng[0]
    c1 = min(max(c0 + base * (ce - cs), end_rng[0]), end_rng[1])
    if abs((c1 - c0) - base * (ce - cs)) > 1e-6:
        c0 = max(start_rng[0], min(start_rng[1], c1 - base * (ce - cs)))
    v = slope(cs, ce, c0, c1)
    if v is None:   # nothing feasible within the clamp: plain base speed
        c0, c1, v = start_rng[0], start_rng[0] + base * (ce - cs), base
    cands = [((ce - cs) * lv(v), None, (c0, c1))]
    for e, cst in best.items():
        q = e[1]
        c_end = min(max(C(q) + base * (ce - T(q)), end_rng[0]), end_rng[1])
        v = slope(T(q), ce, C(q), c_end)
        if v is None:
            continue
        cands.append((cst + (ce - T(q)) * lv(v) + jerk * math.log(v / v_of[e]) ** 2, e, c_end))
    cost, e, endc = min(cands, key=lambda x: x[0])
    if e is None:
        return [(cs, endc[0]), (ce, endc[1])], [], cost
    chain = []
    while e is not None:
        chain.append(e[1])
        if e[0] == "S":
            first = e[1]
        e = back[e]
    chain.reverse()
    anchors = [(cs, startc[first])] + [(T(q), C(q)) for q in chain] + [(ce, endc)]
    pairs = [(acc[q[0]], T(q)) for q in chain]
    return anchors, pairs, cost


# ============================================================== mapping ==
class TimeMap:
    """song_t -> clip_t. Optional analytic ramp on [cs, cs+rdur], then piecewise linear through anchors,
    linear extrapolation outside, then symmetric box smoothing of width `smooth` (keeps monotonic + bounds)."""

    def __init__(self, anchors, ramp=None, smooth=0.0):
        self.a = sorted(anchors)
        self.ramp = ramp      # (cs, c_start, v0, v1, dur)
        self.smooth = smooth

    def _lin(self, t):
        if self.ramp:
            cs, c, v0, v1, dur = self.ramp
            if t <= cs + dur:
                tau = t - cs
                if tau < 0:
                    return c + v0 * tau
                # ∫ v1 + (v0-v1)(1-u/dur)^2 du
                return c + v1 * tau + (v0 - v1) * dur / 3.0 * (1 - (1 - tau / dur) ** 3)
        a = self.a
        if t <= a[0][0]:
            if self.ramp:
                return a[0][1]
            v = (a[1][1] - a[0][1]) / (a[1][0] - a[0][0])
            return a[0][1] + v * (t - a[0][0])
        for (t0, c0), (t1, c1) in zip(a, a[1:]):
            if t <= t1:
                return c0 + (c1 - c0) * (t - t0) / (t1 - t0)
        (t0, c0), (t1, c1) = a[-2], a[-1]
        return c1 + (c1 - c0) / (t1 - t0) * (t - t1)

    def __call__(self, t):
        if self.smooth <= 0:
            return self._lin(t)
        hs = self.smooth / 2
        us = np.linspace(-hs, hs, 9)
        return float(np.mean([self._lin(t + u) for u in us]))

    def speed(self, t, h=1e-3):
        return (self(t + h) - self(t - h)) / (2 * h)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "analyze":
        src, out = pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
        sig = sys.argv[4] if len(sys.argv) > 4 else _sig(src)
        write_motion_csv(analyze_cv2(src), out, sig)
        print("ok", out)
    else:
        print(__doc__)
