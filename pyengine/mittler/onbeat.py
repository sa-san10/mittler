"""音ハメ（拍に合わせた時間の付け替え）を、映像クリップ1本ぶん作る。編集画面の「🎵 音ハメ」（描画サーバーの /warp）から呼ぶ。
中身は Attention ダンスMV の beatwarp.py（動きの止まり・切り返し＝アクセントを見つけ、拍と順番に組にして、速さの上限・下限の中で
速さの変化がいちばん小さくなる付け替えを選ぶ）。

q（JSON）：
  src     素材（root からの相対。1本だけ）
  in      クリップの頭で映す動画の秒（ここから slip 秒のあいだで始めてよい）
  dur     クリップの長さ（秒）
  until   音ハメを閉じる、クリップの頭からの秒（既定 dur。そのあとは最後の速さのまま。曲の終わりのあとにフェードの分だけクリップが長いときなど）
  speed   ふだんの速さ（既定 1）
  beats   [[クリップの頭からの秒, 重み], …]（重み 1＝拍、0.5＝裏拍。編集画面がタイムラインのビートから作る）
  min, max  速さの下限・上限（既定 0.5・2.0）
  lam     速さを変えることの重さ（大きいほど、ふだんの速さから離れない。既定 2.5）
  jerk    となりの区間との速さの差の重さ（大きいほど、なめらか。既定 1.5）
  slip    頭を何秒まで後ろにずらしてよいか（既定 0.2）
  end     true なら、クリップの終わりを素材の終わりにそろえる
  thr, gap  アクセントの強さのしきい値（既定 0.30）・アクセントどうしの最小の間（既定 0.22 秒）
  smooth  速さの段差をやわらげる幅（既定 0.08 秒）
  in_rng  [lo, hi]：クリップの頭で映してよい動画の秒の範囲（あれば in・slip より優先）
  out_rng [lo, hi]：クリップの終わりで映してよい動画の秒の範囲
  fit     true（か speed: "fit"）なら、ふだんの速さ＝in_rng と out_rng のまんなかどうしを結ぶ速さ
  pins    [[動画の秒, クリップの頭からの秒], …]：必ず通る固定点（ポーズの解析で決めたキメなど）。最初の固定点までを自動で合わせ、あとは固定点を通る
  grid_extra [クリップの頭からの秒, …]：拍のほかに合わせたい時刻（重み 1）
  （Attention の assemble.py の EDL の in_rng・out_rng・speed "fit"・pins・grid_extra と同じ。ramp（解析的な加速）は無い）
返す：points（[[クリップの頭からの秒, 動画の秒], …]）・smooth・accents（[[動画の秒, 強さ 0..1, 'stop'|'rev'], …]）・
  pairs（[[動画の秒, クリップの頭からの秒], …]＝拍に合わせたアクセント）・energy（[[動画の秒, 動きの量], …]）・src_dur・fps・method（flow／framediff）。
動きの解析はプロジェクトの work/beatwarp/ に CSV でとっておく（素材が変わらなければ2回目からは速い）。
"""
import hashlib
import json
import re
import subprocess

from . import beatwarp


def _probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,r_frame_rate',
                          '-of', 'json', str(path)], capture_output=True, text=True).stdout
    st = json.loads(out)['streams'][0]
    a, b = st['r_frame_rate'].split('/')
    return {'w': int(st['width']), 'h': int(st['height']), 'fps': float(a) / float(b or 1)}


def auto(project_dir, root, q):
    src = q['src'][0] if isinstance(q['src'], list) else q['src']
    path = (root / src).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'素材がない：{src}')
    tag = re.sub(r'[^\w.-]+', '_', path.stem)[:40] + '_' + hashlib.sha1(str(src).encode('utf-8')).hexdigest()[:8]
    m = beatwarp.motion(path, project_dir / 'work' / 'beatwarp', tag, _probe)
    acc, curves = beatwarp.detect_accents(m, min_gap=float(q.get('gap', 0.22)), thr=float(q.get('thr', 0.30)))
    fps, n = m['fps'], m['n']
    d_end = (n - 0.5) / fps
    dur = float(q['until']) if q.get('until') else float(q['dur'])  # 合わせるのはここまで（あとは端の傾きでのばす）
    cin = float(q.get('in', 0.0) or 0.0)
    base = float(q.get('speed', 1.0) or 1.0)
    vmin, vmax = float(q.get('min', 0.5)), float(q.get('max', 2.0))
    slip = float(q.get('slip', 0.2))
    grid = sorted((float(t), float(w)) for t, w in (q.get('beats') or []))
    grid = sorted(grid + [(float(g), 1.0) for g in (q.get('grid_extra') or [])])  # 拍のほかに合わせる時刻（裏拍の掛け声など）
    in_rng = tuple(float(x) for x in q['in_rng']) if q.get('in_rng') else None
    out_rng = tuple(min(float(x), d_end) for x in q['out_rng']) if q.get('out_rng') else None
    if q.get('fit') or q.get('speed') == 'fit':  # ふだんの速さ＝頭と終わりの範囲のまんなかどうしを結ぶ速さ（assemble.py の speed "fit"）
        lo = sum(in_rng) / 2 if in_rng else cin
        base = (sum(out_rng) / 2 - lo) / dur if out_rng else 1.0
    lam, jerk = float(q.get('lam', 2.5)), float(q.get('jerk', 1.5))
    srng = in_rng or (cin, min(cin + slip, d_end))
    erng = out_rng or ((d_end, d_end) if q.get('end') else (0.0, d_end))
    if q.get('end') and not in_rng:
        srng = (0.0, d_end)
    pins = sorted((float(t), float(c)) for c, t in (q.get('pins') or []))  # [[動画の秒, クリップの頭からの秒], …]：その時刻にその動画の秒を必ず映す
    if pins and dur - pins[0][0] > 0:  # 固定点まで自動、そのあとは固定点を通る（assemble.py の cut_timemap の pins と同じ）
        p_t, p_c = pins[0]
        base0 = (p_c - sum(srng) / 2) / max(1e-6, p_t)
        anchors, pairs, cost = beatwarp.solve_warp(0.0, p_t, acc, grid, srng, (p_c, p_c), base0, vmin, vmax, lam, 1.0, jerk)
        anchors = list(anchors) + pins[1:]
        lo, hi = out_rng if out_rng else (0.0, d_end)
        t_l, c_l = anchors[-1]
        anchors.append((dur, min(max(c_l + base * (dur - t_l), lo), hi)))
    else:
        anchors, pairs, cost = beatwarp.solve_warp(0.0, dur, acc, grid, srng, erng, base, vmin, vmax, lam, 1.0, jerk)
    E = curves['E']
    step = max(1, len(E) // 400)
    return {
        'points': [[round(t, 4), round(c, 4)] for t, c in anchors],
        'smooth': float(q.get('smooth', 0.08)),
        'accents': [[round(t, 4), round(s, 3), kind] for t, s, kind, k in acc],
        'pairs': [[round(a[0], 4), round(bt, 4)] for a, bt in pairs],
        'energy': [[round((k + 0.5) / fps, 4), round(float(E[k]), 3)] for k in range(0, len(E), step)],
        'src_dur': round(d_end, 4), 'fps': fps, 'method': m['method'], 'cost': round(float(cost), 4),
    }
