"""Mittler の Python エンジンのコマンド（前の名前 `python -m ccpy …` でも同じものが動く：隣の pyengine/ccpy/ が受け口）。
  python -m mittler stills <timeline.cut.json> --at 5.0,15.5 --out <フォルダ>     時刻ごとの PNG（still_<時刻>.png。時刻はコマにそろえる）
  python -m mittler segment <timeline.cut.json> <出力.mp4> --from S --to E [--encoder libx264|h264_nvenc]   区間を音なしで書き出す
  python -m mittler video <timeline.cut.json> <出力.mp4> [--jobs 20] [--from S --to E] [--encoder ...]   区間に分けて並列に書き、つないで音をのせる
      [--draft --step 2 --scale 0.5]  ドラフト：コマを間引く（step 2＝2コマに1コマだけ描く＝24fps なら 12fps。描く時間がほぼ 1/step）、
                                      描いた絵を縮める（scale。時間は変わらない、ファイルが小さくなる）、速い設定（veryfast・crf 23・AAC 128k）。音は全部入る。音量そろえはしない
                                      --draft はエンジンにも渡る（ctx.draft＝True。対応したエフェクトだけが軽く描く。機能追加案01）。stills に --draft を付けたときも同じ
  python -m mittler serve <timeline.cut.json> [--port 47901] [--ahead コマ数]     描画サーバー（編集画面のプレビュー用。serve.py。--ahead 0 で先読みなし）
  python -m mittler mix <timeline.cut.json> <出力.wav> [--from S --to E]   音のトラックだけ混ぜる（mix.py。numpy なしでも動く）
  python -m mittler master <timeline.cut.json> <出力.mp4> [--check] [--force] [--fresh] [--jobs 4] [--from S --to E] [--upscale anime|real|none] …   🏆 マスター書き出し（master.py。機能追加案03 v2）
  python -m mittler enhance <入力の動画> [<出力.mp4>] [--upscale anime|real|none]   動画1本を、マスター書き出しと同じ高画質に（enhance.py。作品は要らない）
  --blender <blender.exe>（どれでも）：Blender の 3D（effects_lib/common/blender3d.py）で使う Blender（環境変数 MITTLER_BLENDER と同じ。blender.py）
  3D のエフェクト（gl_*・blender3d）を使う作品だけ、moderngl・Blender が要る（使わない作品は今までどおり。docs/インストールガイド.md の 14）
  --hwaccel cuda（stills・segment・video・serve）：映像クリップを GPU で読む（タイムラインの settings.decode.hwaccel より優先。none で CPU。絵は同じ）
  --master-scale 2 --master-fps 60 [--src-map 表.json]（stills・segment）：マスター書き出しの描き方（機能追加案03 v2。キャンバス s 倍・ctx.scale、
      コマを 60fps で刻む、映像の素材の差し替え）。付けなければ今までどおり
（ffmpeg が PATH にあること。無ければ set PATH=<ffmpeg の bin>;%PATH%）
書き出しの分け方・エンコードの設定は、偽マリアMV の make_animatic.py（render_parallel）と同じ（同じ絵なら同じ MP4 になる）。
作品ごとに変えるときはタイムラインの settings.export（無ければ今までどおり）：
  video: {preset, crf, profile, colors: "bt709"（RGB→YUV を BT.709 の式で変換して、色の印も付ける。無ければ ffmpeg の既定）,
         threads（x264 のスレッド数）, x264_params（例 "asm=…"：x264 が使う CPU の機能。AVX512 の有り無しで MP4 が変わる）}
  audio: {bitrate: "320k"（既定 256k）, sample_rate}
  loudnorm: {I, TP, LRA}（書き出しの最後に音を正規化する。loudnorm.py。<名前>_premaster.mp4 も残す）
字幕が ASS（settings.subtitle.renderer = "ass"、ass.py）なら、区間のエンコードの ffmpeg の -vf で焼く（元の dialogue-video と同じ）。
（作者のダンス動画（Attention）は slow・crf 16・high・bt709・320k、作者の紙芝居の作品は medium・crf 18・threads 24・asm・192k・loudnorm。それぞれの元の書き出しと同じ）
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

from .engine import Engine  # noqa: E402（mix だけなら numpy は要らないが、ここでは読む）
from .procs import kill_tree  # noqa: E402


def vcodec(encoder, ex=None):
    """映像のエンコードの指定。ex＝settings.export.video（preset・crf・profile・colors）"""
    ex = ex or {}
    if encoder == 'h264_nvenc':
        return ['-c:v', 'h264_nvenc', '-preset', 'p5', '-cq', '19', '-b:v', '0', '-pix_fmt', 'yuv420p']
    out = ['-c:v', 'libx264', '-preset', str(ex.get('preset', 'medium')), '-crf', str(ex.get('crf', 18))]
    if ex.get('profile'):
        out += ['-profile:v', str(ex['profile'])]
    if ex.get('threads'):  # x264 のスレッド数（同じ数なら同じ MP4。作者の紙芝居の作品の元は 16 論理コアの PC の自動＝24）
        out += ['-threads', str(int(ex['threads']))]
    if ex.get('x264_params'):  # x264 の細かい設定。asm＝使う CPU の機能（AVX512 のある PC と無い PC では、同じ絵でも MP4 が変わる）
        out += ['-x264-params', str(ex['x264_params'])]
    if ex.get('colors') == 'bt709':  # RGB → YUV を BT.709 の式で（Attention の assemble.py と同じ）。色の印も付ける
        out = ['-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv'] + out
        out += ['-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv']
    else:
        out += ['-pix_fmt', 'yuv420p']
    return out


def audio_args(song, t0, t1, end):
    """[t0, t1) の音の入力と出力の指定。曲（end まで）のあとは無音で埋める（apad）。曲より後ろだけの区間・曲の無い作品は無音の入力
    （曲も音のトラックも無い作品で、'None' という名前のファイルを読もうとして書き出しの最後で落ちていた。2026-11-14 作者の PC で見つかった）"""
    if song is not None and t0 < end - 1e-6:
        inp = ['-ss', f'{t0:.3f}', '-t', f'{min(t1, end) - t0:.3f}', '-i', str(song)]
    else:
        inp = ['-f', 'lavfi', '-t', f'{t1 - t0:.3f}', '-i', 'anullsrc=r=48000:cl=stereo']
    return inp, ['-af', 'apad', '-t', f'{t1 - t0:.3f}']


def draft_video(ex):
    """ドラフトの映像の設定：速く・小さく（色の変換だけは本番と同じ）"""
    ex = ex or {}
    return {'preset': 'veryfast', 'crf': 23, **({'colors': ex['colors']} if ex.get('colors') else {})}


def master_size(W0, H0, out_h):
    """マスター書き出しの書き出しの大きさ（偶数）。out_h（--master-out・設定の outHeight）は短い辺：横長の作品は高さ、縦長の作品は幅
    （2026-10-31、作者の縦長のダンス動画 1080×1920 で 608×1080 になっていたので。横長の作品は今までと同じ）"""
    out_h = int(out_h)
    if W0 < H0:
        return out_h, 2 * round(H0 * out_h / W0 / 2)
    return 2 * round(W0 * out_h / H0 / 2), out_h


def with_vf(vc, pre):
    """エンコードの指定 vc（vcodec）の前に、-vf のフィルタ pre（字幕を焼く・縮める…の順の一覧）をかける（vc に -vf があれば、その頭に足す）"""
    vc = list(vc)
    if pre:
        if '-vf' in vc:
            i = vc.index('-vf')
            vc[i + 1] = ','.join(pre) + ',' + vc[i + 1]
        else:
            vc = ['-vf', ','.join(pre)] + vc
    return vc


def rgb_encode_cmd(W, H, rate, vc, out):
    """標準入力の RGB のコマ（rawvideo rgb24・W×H・rate fps）を vc でエンコードする ffmpeg のコマンド（segment と、動画1本を高画質にする道具 enhance.py）"""
    return ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', rate, '-i', '-'] + vc + [str(out)]


def segment(eng, out, t0, t1, encoder, scale=1.0, draft=False, step=1, out_h=None, down=None, no_cache=False):
    """区間を音なしで書き出す。out_h（マスター書き出し：s 倍のキャンバスで描いた絵を、エンコードの前にこの高さへ down（既定 area）で縮める。
    0・None なら縮めない）"""
    n0, n1 = int(round(t0 * eng.fps)), int(round(t1 * eng.fps))
    step = max(1, int(step or 1))
    out = Path(out).resolve()
    exv = (eng.tl.get('settings', {}).get('export') or {}).get('video')
    vc = vcodec(encoder, draft_video(exv) if draft else exv)
    cwd = None
    pre = []  # エンコードの前にかける -vf（字幕を焼く → 縮める → 色の変換 の順）
    if eng.ass_mode and eng.ass_clips:  # 字幕（ASS）はエンコードの ffmpeg でまとめて焼く（元の build_video と同じ。root を作業フォルダに）
        from . import ass
        eng.ass_burn = False
        pre.append(ass.vf(eng, n0, step))
        cwd = str(eng.root)
    if out_h and eng.W0 < eng.H0:  # マスター書き出し（縦長の作品、2026-10-31）：out_h は短い辺（幅）。1080×1920 の作品なら 1080×1920 に
        ow, oh = master_size(eng.W0, eng.H0, out_h)
        if (ow, oh) != (eng.W, eng.H):
            pre.append(f'scale={ow}:{oh}:flags={down or "area"}')
    elif out_h and out_h != eng.H:  # マスター書き出し：4K のキャンバスの絵を書き出しの大きさへ（字幕を焼いたあと・色の変換の前）
        ow = 2 * round(eng.W0 * out_h / eng.H0 / 2)
        pre.append(f'scale={ow}:{int(out_h)}:flags={down or "area"}')
    if scale and scale < 1:  # ドラフト：絵は本番の大きさで描いて、ここで縮める（エフェクトは画素の大きさを前提にしているため）。偶数にそろえる
        pre.append(f'scale=trunc(iw*{scale}/2)*2:trunc(ih*{scale}/2)*2:flags=area')
    rate = str(eng.fps) if step == 1 else f'{eng.fps}/{step}'  # 間引くと 1 コマが step コマぶんの長さ
    p = subprocess.Popen(rgb_encode_cmd(eng.W, eng.H, rate, with_vf(vc, pre), out), stdin=subprocess.PIPE, cwd=cwd)
    prog = Path(str(out) + '.progress')  # 進み具合（描いたコマ数）。書き出しの親が読む
    # ためた絵（fcache）：差分書き出し。同じ鍵の劣化なしの絵があれば描かずに使い
    # （描いた絵とビット単位で同じ。ドラフトの書き出しも、ためた本番の絵を使う）、描いたコマは本番の品質ならためる。
    # 使わない：字幕（ASS）をあとで焼く区間（ためた絵は字幕を焼いたもの）・マスター（縮める前の絵が違う）・no_cache（「ためた絵を使わずに全部描く」）
    from . import fcache
    use = not no_cache and fcache.enabled(eng, draft_ok=True) and not out_h and eng.ass_burn
    keep = use and fcache.enabled(eng) and step == 1
    hits = 0
    k = 0
    broken = False
    for n in range(n0, n1, step):
        # コマの時刻は、通しのコマ番号から n / fps（プレビュー・静止画・並列 1 と同じ小数）。前は「区間の頭の秒 ＋ (n − n0) / fps」で、
        # 最後の桁が n / fps と違うことがあり、クリップの頭がちょうどコマの時刻だと、並列の数（区間の切り方）で境目のコマの絵が変わった（2026-11-12）
        frame = fcache.get(eng, n / eng.fps, draft_ok=True)[0] if use else None
        if frame is None:
            frame = eng.render(n / eng.fps)
            if keep:
                fcache.put(eng, n / eng.fps, frame)
        else:
            hits += 1
        img = frame.tobytes()
        try:
            p.stdin.write(img)
        except OSError:  # エンコードの ffmpeg が先に止まった（前は「OSError: [Errno 22] Invalid argument」とだけ出て、理由が分からなかった）
            broken = True
            break
        k += 1
        if k % 12 == 0:
            prog.write_text(str(k), encoding='utf-8')
    try:
        p.stdin.close()
    except OSError:
        broken = True
    rc = p.wait()
    if broken or rc:
        raise SystemExit(f'エンコードの ffmpeg が失敗した（終了コード {rc}・{k} コマ書いたところ）。理由は、この上の ffmpeg のエラーの行（{eng.W}×{eng.H}。幅・高さが奇数だと H.264 にできない）')
    prog.write_text(str(k), encoding='utf-8')
    Path(str(out) + '.cached').write_text(str(hits), encoding='utf-8')  # ためた絵を使ったコマの数（書き出しの親が足して知らせる）
    return k


class _Stopped(Exception):
    pass


def prepare(eng, f0, f1, step, cancel):
    """書き出しの前の下ごしらえ（2026-11-13、3D 強化）：prepare(eng, clip, n0, n1, step, check, progress) を持つエフェクト（Blender の 3D＝
    effects_lib/common/blender3d.py）のクリップに、範囲のコマ [f0, f1) をまとめて描いてもらう。そういうエフェクトが無い作品は何もしない（今までどおり）。
    進み具合は `PHASE blender できた数 全部`、終わったら `PHASE render`。<出力>.cancel ができたら止める（CANCELLED・終わりの番号 3）"""
    preps = []
    for c in eng.effect_clips:
        try:
            mod = eng.effect(c['effect'])
        except Exception:  # 読めないエフェクトは、描くときに理由を出す
            continue
        if hasattr(mod, 'prepare'):
            preps.append((c, mod))
    if not preps:
        return

    def check():
        if cancel.exists():
            raise _Stopped()
    last = [None]

    def progress(d, n):
        if last[0] != (d, n):
            last[0] = (d, n)
            print(f'PHASE blender {d} {n}', flush=True)
    try:
        for c, mod in preps:
            mod.prepare(eng, c, f0, f1, step, check, progress)
    except _Stopped:
        cancel.unlink(missing_ok=True)
        print('CANCELLED', flush=True)
        raise SystemExit(3)
    print('PHASE render', flush=True)


def video(a, eng):
    """区間に分けて並列に書き、つないで音をのせる。失敗しても止めても、区間の一時フォルダ（<出力のフォルダ>/_tmp/mittler_*）を残さない（2026-11-12。
    前は、区間・音を混ぜる・mux の失敗で区間の MP4 とログが残り、失敗のたびに増えた。うまくいったときも空の _tmp が残った）"""
    try:
        return _video(a, eng)
    finally:
        tmp = getattr(a, 'tmp_dir', None)
        if tmp is not None:
            for lf in getattr(a, 'tmp_logs', []):  # 開いたままのログがあると Windows では消せない
                try:
                    lf.close()
                except Exception:
                    pass
            for _ in range(6):
                shutil.rmtree(tmp, ignore_errors=True)
                if not tmp.exists():
                    break
                time.sleep(0.5)
            try:
                tmp.parent.rmdir()  # 空になった _tmp も消す（ほかの書き出しの一時フォルダがあれば残る）
            except OSError:
                pass


def _video(a, eng):
    if eng.W0 % 2 or eng.H0 % 2:  # 描き始める前に止める（H.264 の yuv420p は幅・高さが偶数でないとエンコードできない）
        raise SystemExit(f'書き出せない：動画の大きさ {eng.W0}×{eng.H0} の幅か高さが奇数。タイムラインの width・height を偶数にする（編集画面の上のバーの大きさのボタン）')
    t1 = a.t1 if a.t1 is not None else eng.duration
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    f0, f1 = int(round(a.t0 * eng.fps)), int(round(t1 * eng.fps))
    step = max(1, a.step)
    count = -(-(f1 - f0) // step)  # 描くコマの数（間引くなら f0 から step おき）
    a.jobs = max(1, min(a.jobs, count))
    # 区間の数：並列の数より多くして、a.jobs 本ずつ順に流す（重い区間・軽い区間があっても、最後に1本だけ待つ時間が短くなる）。
    # マスター書き出し（master.py）は chunks を渡す（区間の切り方は並列の数によらない）。
    # CPU をもっと使えるように：ふつうの書き出しも、並列が 2 本以上なら区間を細かく（master.render_chunks。並列の数より少なくはしない）。
    # 前は区間＝並列の数で、重い区間が残ると最後は数本だけが動いて CPU が空いていた（マスターで測った：区間を細かくすると速くなった分が多い）。並列 1 は今までどおり 1 区間
    want = getattr(a, 'chunks', None)
    if not want and a.jobs > 1:
        from .master import render_chunks
        want = max(a.jobs, render_chunks(count))
    nseg = max(1, min(int(want or a.jobs), count))
    a.jobs = min(a.jobs, nseg)
    # 区間の境目は、描くコマ（f0 + step の倍数）にそろえる。最後は f1
    edges = [f0 + step * (count * i // nseg) for i in range(nseg)] + [f1]
    (out.parent / '_tmp').mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='mittler_', dir=out.parent / '_tmp'))  # 区間の一時フォルダ（終わったら・止めたら片付ける）
    a.tmp_dir = tmp
    segs = [tmp / f'seg{i:02d}.mp4' for i in range(nseg)]
    tl = str(Path(a.timeline).resolve())
    here = Path(__file__).resolve().parent.parent

    # 区間ごとに別のプロセス。2秒ごとに進み具合（PROGRESS 描いたコマ 全部）を出す。<出力>.cancel ができたら止める（編集画面の「止める」）
    cancel = Path(str(out) + '.cancel')
    cancel.unlink(missing_ok=True)  # 前に止めたときの印が残っていたら外す
    prepare(eng, f0, f1, step, cancel)  # Blender の 3D：区間に分ける前に、範囲のコマをまとめて描いてためる（区間は読むだけ）
    procs, logs = [], []
    a.tmp_logs = logs
    t_start = time.time()

    def launch(i):
        cmd = [sys.executable, '-X', 'utf8', '-m', 'mittler', 'segment', tl, str(segs[i]), '--from', repr(edges[i] / eng.fps),
               '--to', repr(edges[i + 1] / eng.fps), '--encoder', a.encoder, '--scale', repr(a.scale), '--step', str(step)] + (['--draft'] if a.draft else []) +               (['--no-cache'] if getattr(a, 'no_cache', False) else []) + \
              (['--hwaccel', a.hwaccel] if a.hwaccel else []) + list(getattr(a, 'seg_extra', None) or [])  # マスター書き出し（master.py）の描き方
        lf = open(tmp / f'seg{i:02d}.log', 'w', encoding='utf-8')
        logs.append(lf)
        procs.append(subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=str(here)))

    def fill():  # 動いている区間が a.jobs 本より少なければ、次の区間を始める（失敗した区間があれば、もう始めない）
        while len(procs) < nseg and sum(p.poll() is None for p in procs) < a.jobs and not any(p.returncode for p in procs):
            launch(len(procs))

    total = count
    while True:
        fill()
        if not any(p.poll() is None for p in procs):
            break
        if cancel.exists():
            for p in procs:  # 区間のプロセスと、その子の ffmpeg もまとめて止める（ffmpeg が残ると一時ファイルを消せない）
                kill_tree(p)
            for p in procs:
                p.wait()
            for lf in logs:
                lf.close()
            cancel.unlink(missing_ok=True)
            for _ in range(10):
                shutil.rmtree(tmp, ignore_errors=True)
                if not tmp.exists():
                    break
                time.sleep(0.5)
            print('CANCELLED', flush=True)
            raise SystemExit(3)
        done = 0
        for sg in segs:
            try:
                done += int(Path(str(sg) + '.progress').read_text(encoding='utf-8') or 0)
            except (OSError, ValueError):
                pass
        print(f'PROGRESS {done} {total} {time.time() - t_start:.0f}', flush=True)
        for _ in range(8):  # 2 秒待つ（区間が並列の数より多いときは、1本終わったらすぐ次を始める）
            time.sleep(0.25)
            if len(procs) < nseg and sum(p.poll() is None for p in procs) < a.jobs:
                break
    for lf in logs:
        lf.close()
    for i, p in enumerate(procs):
        if p.returncode:
            raise SystemExit(f'区間 {i} が失敗: ' + (tmp / f'seg{i:02d}.log').read_text(encoding='utf-8', errors='replace')[-2000:])
    print(f'PROGRESS {total} {total} {time.time() - t_start:.0f}', flush=True)
    a.cached_frames = 0  # ためた絵（fcache）を使ったコマの数（区間の <区間>.cached の合計）
    for sg in segs:
        try:
            a.cached_frames += int(Path(str(sg) + '.cached').read_text(encoding='utf-8') or 0)
        except (OSError, ValueError):
            pass
    print(f'CACHED {a.cached_frames} {total}', flush=True)
    print('MUXING', flush=True)
    (tmp / 'list.txt').write_text(''.join(f"file '{p.as_posix()}'\n" for p in segs), encoding='utf-8')
    if any(tr.get('kind') in ('tts', 'audio') for tr in eng.tl.get('tracks', [])):  # 音のトラックがあれば混ぜたもの（mix.py）
        from .mix import mix
        mixed = tmp / 'mix.wav'
        print('mix', mix(a.timeline, mixed, a.t0, t1), flush=True)
        ain, aout = ['-i', str(mixed)], ['-t', f'{t1 - a.t0:.3f}']
    else:
        song = (eng.dir / eng.tl['audio']) if eng.tl.get('audio') else None
        ain, aout = audio_args(song, a.t0, t1, eng.song_end)
    ex = eng.tl.get('settings', {}).get('export') or {}
    ea = ex.get('audio') or {}
    acodec = ['-c:a', 'aac', '-b:a', str(ea.get('bitrate', '256k'))] + (['-ar', str(ea['sample_rate'])] if ea.get('sample_rate') else [])
    if a.draft:  # ドラフト：音は小さく、音量そろえはしない
        acodec = ['-c:a', 'aac', '-b:a', '128k']
    ln = None if a.draft else ex.get('loudnorm')
    pre = out.with_name(out.stem + '_premaster' + out.suffix) if ln else out  # 正規化するときは、まず正規化前（premaster）を書く
    # 区間が1つ（--jobs 1）なら、つながずにそのまま載せる（concat を通すと、頭のパケットに SPS・PPS が入って映像のストリームが元と変わる）
    vin = ['-i', str(segs[0])] if len(segs) == 1 else ['-f', 'concat', '-safe', '0', '-i', str(tmp / 'list.txt')]
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error'] + vin + ain +
                   ['-map', '0:v', '-map', '1:a', '-c:v', 'copy'] + aout + acodec + ['-movflags', '+faststart', str(pre)],
                   check=True)
    try:
        _loudnorm(ln, tmp, out, pre, ea)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # 失敗しても作業のフォルダ（_tmp）を残さない
    print('wrote', out, f'{count} frames in {a.jobs} jobs, {time.time() - t_start:.0f}s' + (f'（{step} コマに 1 コマ）' if step > 1 else '') +
          (f'（区間 {nseg}）' if nseg != a.jobs else '') + (f'（ためた絵 {a.cached_frames} コマ）' if getattr(a, 'cached_frames', 0) else ''))


def _loudnorm(ln, tmp, out, pre, ea):
    """書き出しの最後の音の正規化（settings.export.loudnorm があるとき。loudnorm.py）"""
    if ln:
        from .loudnorm import normalize
        mixed = tmp / 'mix.wav'
        keep = out.with_name(out.stem + '_premaster.wav')  # 正規化前の音（元の render/mix.wav に当たる）
        if mixed.exists():
            shutil.copyfile(mixed, keep)
        else:
            subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(pre), '-map', '0:a:0', '-c:a', 'pcm_s16le', str(keep)], check=True)
        print('LOUDNORM', flush=True)
        rep = normalize(keep, pre, out, ln, str(ea.get('bitrate', '256k')), ln.get('ffmpeg') or 'ffmpeg')
        print('loudnorm', rep['normalization_type'], rep['after_wav']['input_i'], rep['after_wav']['input_tp'], flush=True)


def main():
    if sys.argv[1:2] == ['enhance']:  # 動画1本を高画質に（enhance.py。引数はそちらで読む：オプションはアップスケールの方法だけ）
        from .enhance import main_enhance
        return main_enhance(sys.argv[2:])
    ap = argparse.ArgumentParser(prog='mittler')
    ap.add_argument('mode', choices=['stills', 'segment', 'video', 'serve', 'mix', 'master', 'bake', 'bake-part'])
    ap.add_argument('timeline')
    ap.add_argument('out', nargs='?')
    ap.add_argument('--at', default='')
    ap.add_argument('--out', dest='outdir')
    ap.add_argument('--from', dest='t0', type=float, default=0.0)
    ap.add_argument('--to', dest='t1', type=float)
    ap.add_argument('--jobs', type=int)                     # 区間の並列の数（既定 1。master は auto＝CPU の数と空いているメモリから。master.py の render_jobs）
    ap.add_argument('--encoder', default='libx264')
    ap.add_argument('--scale', type=float, default=1.0)   # ドラフト：縮める割合（0.25＝1/4）
    ap.add_argument('--draft', action='store_true')        # ドラフト：速い設定・音量そろえなし・ctx.draft（対応したエフェクトが軽く描く）
    ap.add_argument('--step', type=int, default=1)         # ドラフト：コマを間引く（2＝2コマに1コマ）
    ap.add_argument('--port', type=int, default=47901)
    ap.add_argument('--hwaccel')                            # 映像を GPU で読む（cuda など。none で CPU）。無ければタイムラインの settings.decode.hwaccel
    ap.add_argument('--ahead', type=int)                    # serve：先読みするコマ数（既定 1 秒ぶん。0 で先読みしない）
    # マスター書き出し（機能追加案03 v2）の描き方。stills・segment でも使える（確かめ用）。付けなければ今までどおり
    ap.add_argument('--master-scale', type=float)                # キャンバスの倍率（ctx.scale。2＝4K。無ければ 1）
    ap.add_argument('--master-fps', type=float)                  # コマを刻む fps（タイムラインの fps の代わり。60）
    ap.add_argument('--src-map')                                 # 映像の素材の差し替え表（JSON：{素材のパス: ファイル, "@clips": {クリップの id: {素材のパス: ファイル}}}。'@clips' は無くてよい）
    # master（pyengine/mittler/master.py）だけが使うもの。既定は master.py の DEFAULTS
    ap.add_argument('--check', action='store_true')              # 書き出し前チェックだけ
    ap.add_argument('--force', action='store_true')              # scale 未対応のエフェクトがあっても承知で書き出す
    ap.add_argument('--master-out', type=int)                    # 書き出しの高さ（1080。0 なら縮めない）
    ap.add_argument('--esrgan')                                  # アプスケの exe
    ap.add_argument('--esrgan-model')                            # アプスケのモデルの名前（作品・クリップが upscale を書いていないとき）
    ap.add_argument('--upscale')                                 # アプスケを名前で：anime（realesr-animevideov3）・real（realesrgan-x4plus）・none（アップスケールなし：1 倍のキャンバスで 60fps だけ）。作品の settings.master.upscale の代わり（master.py の UPSCALE_KINDS・UPSCALE_NONE）
    ap.add_argument('--rife')                                    # 補間の exe
    ap.add_argument('--rife-model')
    ap.add_argument('--cache-gb', type=float)                    # キャッシュの上限
    ap.add_argument('--down')                                    # 縮小のフィルタ（lanczos・area）
    ap.add_argument('--fresh', action='store_true')              # この作品のキャッシュ（work/master の upscale・interp）を全部捨ててから作る
    ap.add_argument('--cache-fmt')                               # 残すキャッシュの形（master.py の CACHE_FMTS）
    ap.add_argument('--esrgan-j')                                # Real-ESRGAN の -j load:proc:save（auto＝CPU の数から。master.py の tool_threads）
    ap.add_argument('--rife-j')                                  # RIFE の -j（同じ）
    ap.add_argument('--chunks', type=int)                        # master：③ の区間の数（0・無し＝auto。master.py の render_chunks）
    ap.add_argument('--threads', type=int)                     # segment：OpenCV のスレッドの数（master が区間に渡す。付けなければ OpenCV の既定）
    ap.add_argument('--blender')                                 # Blender の 3D：blender.exe の場所（環境変数 MITTLER_BLENDER の代わり。区間のプロセスにも渡る）
    ap.add_argument('--no-cache', action='store_true')           # video・segment：ためた絵（fcache）を使わずに全部描く（描いた絵はためる）
    ap.add_argument('--stop')                                    # bake・bake-part：このファイルができたら止める（bake.py）
    ap.add_argument('--chunk', type=int)                         # bake：区間のコマ数（既定 bake.CHUNK）
    ap.add_argument('--first', type=int)                         # bake-part：描く最初と最後のコマ（どちらも入れる）
    ap.add_argument('--last', type=int)
    a = ap.parse_args()
    if a.blender:
        os.environ['MITTLER_BLENDER'] = a.blender
    if a.mode == 'master':
        from .master import main_master
        return main_master(a)
    if a.mode in ('bake', 'bake-part'):  # 裏で先に描いてためる（bake.py）
        from . import bake as B
        if a.mode == 'bake':
            B.bake(a.timeline, a.t0, a.jobs, a.chunk or B.CHUNK, a.stop)
        else:
            B.bake_part(a.timeline, a.first, a.last, a.stop)
        return
    if a.jobs is None:
        a.jobs = 1
    if a.mode == 'mix':
        import json as _json
        from .mix import mix
        print(_json.dumps(mix(a.timeline, a.out, a.t0, a.t1), ensure_ascii=False))
        return
    if a.mode == 'serve':
        from .serve import serve
        return serve(a.timeline, a.port, hwaccel=a.hwaccel, ahead=a.ahead)
    src_map = None
    if a.src_map:
        import json as _json
        src_map = _json.loads(Path(a.src_map).read_text(encoding='utf-8'))
    # --draft：ctx.draft（対応したエフェクトが軽く描く）。stills は --draft を付けなければ今までどおり
    # --master-scale・--master-fps・--src-map：マスター書き出しの描き方（付けなければ scale 1・タイムラインの fps・差し替えなし＝今までどおり）
    eng = Engine(a.timeline, hwaccel=a.hwaccel, draft=a.draft, scale=a.master_scale or 1, fps=a.master_fps, src_map=src_map)
    if a.mode == 'segment':  # 書き出しの区間は前へ進むだけ（同じマスクをあとで読み直さない）。並列のプロセスごとに 512 MB は持たない
        from . import helpers
        helpers.set_mask_cache_mb(min(64, (eng.settings.get('cache') or {}).get('mask_mb', 512)))
        if a.threads:  # マスター書き出しの区間：OpenCV のスレッドを絞る（区間のプロセスが多いとき、ぶつからないように。絵は変わらない）
            import cv2
            cv2.setNumThreads(int(a.threads))
    try:
        if a.mode == 'stills':
            out = Path(a.outdir or a.out)
            out.mkdir(parents=True, exist_ok=True)
            for s in a.at.split(','):
                if not s:
                    continue
                T = float(s)
                t0 = time.time()
                img = eng.render(round(T * eng.fps) / eng.fps)  # コマにそろえる（動画にあるのはコマの時刻だけ。元の --stills と同じ）
                Image.fromarray(img).save(out / f'still_{T:07.3f}.png')
                print(f'still {T} {time.time() - t0:.2f}s', flush=True)
        elif a.mode == 'segment':
            t1 = a.t1 if a.t1 is not None else eng.duration
            n = segment(eng, a.out, a.t0, t1, a.encoder, a.scale, a.draft, a.step, a.master_out, a.down, a.no_cache)
            print('wrote', a.out, n, 'frames')
        else:
            video(a, eng)
    finally:
        eng.close()


if __name__ == '__main__':
    sys.exit(main())
