"""動画1本を、🏆 マスター書き出しと同じ高画質にする（同梱の道具。CLI に動画を渡すだけで使える。
オプションは、アップスケールの方法をアニメ・実写・なしから選ぶだけ）。作品（タイムライン）は要らない。
  python -m mittler enhance <入力の動画> [<出力.mp4>] [--upscale anime|real|none]
  tools\\enhance.cmd <入力の動画> [<出力.mp4>] [--upscale anime|real|none]      （Windows の入口。描く python と ffmpeg を探して上を呼ぶ）
オプションはアップスケールの方法だけ（既定 anime＝マスター書き出しで何も選ばないときと同じ）：
  anime＝Real-ESRGAN の realesr-animevideov3・real＝realesrgan-x4plus（master.py の UPSCALE_KINDS）・none＝アップスケールしない（60fps にするだけ）。
出力：無ければ入力の隣に <入力の名前>_enhanced_<方法>.mp4（同じ名前があれば上書き）。
処理はマスター書き出し（master.py）の ①②④ と同じ関数・同じ道具・同じ設定（③ の描く（エフェクト）は無いので飛ばす）：
  anime・real：出力の大きさ＝マスターと同じ（短い辺 1080。縦長の動画は幅が 1080。master_size）、キャンバス＝その 2 倍（短い辺 2160）。
    ① 長辺がキャンバスの長辺より小さければ Real-ESRGAN で上げて（-s は足りる最小、ずれは lanczos。master.upscale）→ ② fps が 60 より小さければ RIFE で 60fps に
    （master.interp_frames。①② は master.tools_pass）→ ④ area で出力の大きさに縮めて、settings.export の既定（libx264・medium・crf 18・yuv420p。__main__.vcodec）でエンコード。
    入力がキャンバスより大きい（4K の動画など）ときは、マスターと同じくアップスケールはしないで、60fps にして縮めるだけ。
  none：アップスケールせず、元の大きさのまま ② で 60fps にしてエンコード（縮めない。幅・高さが奇数なら 1 画素切って偶数に）。Real-ESRGAN は要らない。
  入力がもう 60fps 以上なら補間しない（マスターと同じ判定：fps が 60－0.01 以上）。60 より大きい fps は 60 に間引く（エンジンが素材を読むときと同じ ffmpeg の fps）。
  ④ は、①② のキャッシュ（無ければ入力）を ffmpeg で RGB（rgb24）のコマにして、マスターの区間（__main__.segment）と同じエンコードのコマンド（rgb_encode_cmd）に流す。
    マスター書き出しで、その動画1本だけを置いた作品（同じ大きさ）を書き出したときと同じ絵になる（区間を 1 つにしたマスターとは映像のストリームまで同じ。偽の道具で確かめた）。
  音：入力の最初の音をそのまま（aac・mp3・ac3・eac3・alac はコピー、ほかの形か、コピーで書けなければマスターと同じ AAC 256k）。音の無い動画はそのまま音なし。
  回転の印（スマホの縦の動画）があれば、回したあとの向きで大きさを決める（ffmpeg はコマを回して読む）。
キャッシュ：作品の work/master の代わりに、出力のフォルダに _enhance_<番号>/ を作って、終わったら（失敗・止めたときも）消す。同じ動画を何度も変えるときに
  残したければ --work <フォルダ>（隠しの引数）：そこにマスターと同じ形のキャッシュ（upscale・interp・hashes.json）を残して、次は道具を呼ばずに使う（上限は --cache-gb）。
止まるとき（終わりの番号 4）：入力が無い・動画として読めない・道具（exe）が無い・モデルのファイルが無い・道具が失敗した。MASTER_STOP <JSON> の行と、人が読む文（マスターと同じ）。
進み具合：PHASE check／PHASE upscale i n／PHASE interp i n／PHASE render の行、④ のあいだは PROGRESS <コマ> <全部> <秒>、終わりに MASTER_DONE <JSON> と「できた：…」。
  止めるのは <出力>.cancel を作る（CANCELLED・終わりの番号 3）か Ctrl+C。
道具の場所・並列・キャッシュの形などはマスターの既定（master.py の DEFAULTS）。道具の場所は環境変数 MITTLER_ESRGAN・MITTLER_RIFE（古い名前 CC_ESRGAN・CC_RIFE も読む）か、隠しの引数 --esrgan・--rife でも変えられる
  （ほかの隠しの引数：--rife-model・--master-scale・--master-fps・--master-out・--down・--cache-fmt・--esrgan-j・--rife-j・--work・--cache-gb。どれもマスターと同じ意味）。
"""
import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import master as M
from .__main__ import master_size, rgb_encode_cmd, vcodec, with_vf
from .names import env

KINDS = list(M.UPSCALE_KINDS) + [M.UPSCALE_NONE]
COPY_AUDIO = ('aac', 'mp3', 'ac3', 'eac3', 'alac')   # MP4 にそのまま入れる音の形（ほかは AAC にする）
LABEL = {'anime': 'アニメ', 'real': '実写', 'none': 'なし（60fps だけ）'}


def probe_input(path):
    """入力の動画：({w, h（回転の印があれば回したあと）, rate, fps, frames（コマの数の見込み）, audio（最初の音の形。無ければ None）}, None)。
    読めなければ (None, 理由)"""
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames:stream_disposition=attached_pic'
                        ':stream_side_data=rotation:stream_tags=rotate:format=duration', '-of', 'json', str(path)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        return None, (r.stderr.strip() or f'ffprobe が失敗（{r.returncode}）')[-600:]
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return None, 'ffprobe の出力が読めない'
    ss = d.get('streams') or []
    vs = [s for s in ss if s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic')]
    if not vs or not vs[0].get('width'):
        return None, '映像が入っていない'
    v = vs[0]
    try:
        n, dn = v['r_frame_rate'].split('/')
        fps = float(n) / float(dn)
    except (KeyError, ValueError, ZeroDivisionError):
        fps = 0
    if fps <= 0:
        return None, f'fps が分からない（r_frame_rate {v.get("r_frame_rate")}）'
    w, h = int(v['width']), int(v['height'])
    rot = (v.get('tags') or {}).get('rotate')
    for sd in v.get('side_data_list') or []:
        if 'rotation' in sd:
            rot = sd['rotation']
    try:
        if abs(int(float(rot or 0))) % 180 == 90:
            w, h = h, w
    except ValueError:
        pass
    dur = float((d.get('format') or {}).get('duration') or 0)
    frames = int(v['nb_frames']) if str(v.get('nb_frames') or '').isdigit() else int(round(dur * fps))
    au = next((s.get('codec_name') or '?' for s in ss if s.get('codec_type') == 'audio'), None)
    return {'w': w, 'h': h, 'rate': v['r_frame_rate'], 'fps': fps, 'frames': frames, 'audio': au}, None


def parse(argv):
    ap = argparse.ArgumentParser(prog='python -m mittler enhance',
                                 description='動画1本を、🏆 マスター書き出しと同じ高画質（60fps。anime・real は 4K に上げてから短い辺 1080 に縮める）の MP4 にする')
    ap.add_argument('src', help='入力の動画')
    ap.add_argument('out', nargs='?', help='出力の MP4（無ければ入力の隣に <入力の名前>_enhanced_<方法>.mp4）')
    ap.add_argument('--upscale', choices=KINDS, default='anime',
                    help='アップスケールの方法：anime＝アニメ（既定）・real＝実写・none＝なし（アップスケールせず 60fps にするだけ）')
    hide = argparse.SUPPRESS  # 隠しの引数（マスターと同じ意味。ふだんは使わない）
    for k in ('--esrgan', '--rife', '--rife-model', '--down', '--cache-fmt', '--esrgan-j', '--rife-j', '--work'):
        ap.add_argument(k, help=hide)
    ap.add_argument('--master-scale', type=float, help=hide)
    ap.add_argument('--master-fps', type=float, help=hide)
    ap.add_argument('--master-out', type=int, help=hide)
    ap.add_argument('--cache-gb', type=float, help=hide)
    a = ap.parse_args(argv)
    a.esrgan = a.esrgan or env('ESRGAN') or None  # MITTLER_ESRGAN（古い名前 CC_ESRGAN も。names.py）
    a.rife = a.rife or env('RIFE') or None
    for k in M.DEFAULTS:  # 付けなかったものはマスターの既定
        if getattr(a, k, None) is None:
            setattr(a, k, M.DEFAULTS[k])
    a.master_scale, a.master_fps, a.master_out = M.num(a.master_scale), M.num(a.master_fps), int(a.master_out)
    if a.cache_fmt not in M.CACHE_FMTS:
        ap.error(f'--cache-fmt は {"・".join(M.CACHE_FMTS)} のどれか（{a.cache_fmt}）')
    if a.down not in ('area', 'lanczos'):
        ap.error(f'--down は area か lanczos（{a.down}）')
    if a.master_out <= 0 or a.master_scale <= 0 or a.master_fps <= 0:
        ap.error('--master-out・--master-scale・--master-fps は 0 より大きく')
    return a


def main_enhance(argv):
    a = parse(argv)
    t_start = time.time()
    kind, fps = a.upscale, a.master_fps
    src = Path(a.src).resolve()
    print('PHASE check', flush=True)
    if not src.is_file():
        M.stop('input', f'高画質にできません。入力の動画が無い：{src}')
    info, why = probe_input(src)
    if info is None:
        M.stop('input', f'高画質にできません。動画として読めない：{src}\n  {why}')
    out = Path(a.out).resolve() if a.out else src.with_name(f'{src.stem}_enhanced_{kind}.mp4')
    if out == src:
        M.stop('output', f'高画質にできません。出力が入力と同じファイル：{out}')
    no_up = kind == M.UPSCALE_NONE
    if no_up:  # アップスケールなし：元の大きさのまま（偶数に）
        ow, oh = info['w'] - info['w'] % 2, info['h'] - info['h'] % 2
        W, H, target, model = ow, oh, None, None
    else:  # 出力はマスターと同じ大きさ（短い辺 master_out）、キャンバスはその master_scale 倍（マスターの作品の大きさ W0×H0 にあたるのが出力の大きさ）
        ow, oh = master_size(info['w'], info['h'], a.master_out)
        W, H = int(round(ow * a.master_scale)), int(round(oh * a.master_scale))
        target, model = max(W, H), M.UPSCALE_KINDS[kind]
    rel = str(src)  # master の「素材のパス」にあたる鍵
    up = not no_up and max(info['w'], info['h']) < target
    ip = info['fps'] < fps - 0.01
    k = (rel, model if up else None)
    need_up, need_ip = ([k] if up else []), ([k] if ip else [])
    s = M.esrgan_scale(model, info, target) if up else None
    print(f'enhance 入力 {info["w"]}x{info["h"]}・{info["fps"]:.3f}fps → 出力 {ow}x{oh}・{fps}fps（アップスケール {LABEL[kind]}'
          + (f'：{model} ×{s} でキャンバス {W}x{H} へ' if up else '：しない' + ('（入力がキャンバスより小さくない）' if not no_up else ''))
          + (f'・補間 {info["fps"]:.3f}→{fps}fps' if ip else '・補間しない（もう 60fps 以上）')
          + ('' if no_up else f'・{a.down} で縮める') + '）', flush=True)
    miss = M.missing_tools(a, need_up, need_ip, {rel: info}, target, fps)
    if miss:
        M.stop('tools', '高画質にできません。道具が無い：\n' + ''.join(f"  {m['text']}\n" for m in miss) +
               '場所は環境変数 MITTLER_ESRGAN・MITTLER_RIFE か --esrgan・--rife で決める（入れ方は docs/インストールガイド.md の 12）', tools=miss)
    out.parent.mkdir(parents=True, exist_ok=True)
    cancel = Path(str(out) + '.cancel')
    cancel.unlink(missing_ok=True)  # 前に止めたときの印
    keep = bool(a.work)  # キャッシュを残す（--work）か、一時のフォルダ（終わったら消す）か
    mdir = Path(a.work).resolve() if keep else out.parent / f'_enhance_{os.getpid()}'
    tmp = mdir / 'tmp' / f'run_{os.getpid()}'
    tmp.mkdir(parents=True, exist_ok=True)
    book_f = mdir / 'hashes.json'
    book = {}
    if keep:
        try:
            book = json.loads(book_f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            book = {}
    files, used, report = {}, set(), {}
    fmt = a.cache_fmt
    try:
        hashes = {rel: M.file_hash(src, book)} if (up or ip) else {}
        if keep:
            book_f.write_text(json.dumps(book, indent=1), encoding='utf-8')
        # キャッシュの名前はマスターと同じ形（master.run の ip_dst・tools_pass の upscale）
        ip_dst = {(r, m): mdir / 'interp' / (f'{hashes[r]}_{m}_{fps}_{fmt}.mkv' if m else f'{hashes[r]}_{fps}_{fmt}.mkv') for r, m in need_ip}
        # ①② アプスケと補間（マスターと同じ master.tools_pass。素材は1本）
        M.tools_pass(a, {rel: src}, {rel: info}, need_up, need_ip, ip_dst, hashes, target, mdir, tmp, cancel, files, used, report, lambda kk: kk[0])
        vsrc = Path(files.get(k, src))
        # ④ 縮めてエンコード（マスターの区間と同じコマンド）・音
        print('PHASE render', flush=True)
        vtmp = tmp / 'video.mp4'
        n = render(a, vsrc, ow, oh, no_up, vtmp, cancel, tmp / 'render.log', t_start)
        print('MUXING', flush=True)
        how = mux(vtmp, src, out, info['audio'], tmp / 'mux.log')
    except (M.Cancelled, KeyboardInterrupt):  # <出力>.cancel か Ctrl+C（道具・ffmpeg は run_step・render が子ごと止める。Ctrl+C はコンソールの子にも届く）
        print('CANCELLED', flush=True)
        cancel.unlink(missing_ok=True)
        raise SystemExit(3)
    finally:
        shutil.rmtree(tmp if keep else mdir, ignore_errors=True)  # 中間（コマの PNG）を消す。--work でなければキャッシュも
    if keep:
        total, gone = M.trim_cache(mdir, a.cache_gb, used)
        print(f'cache {total / 1e9:.2f} GB（上限 {a.cache_gb} GB）' + (f'・古いもの {len(gone)} 本を消した' if gone else ''), flush=True)
    sec = time.time() - t_start
    print('MASTER_DONE ' + json.dumps({'out': str(out), 'size': f'{ow}x{oh}', 'fps': fps, 'canvas': f'{W}x{H}', 'upscale': model or M.UPSCALE_NONE,
                                       'sources': report, 'frames': n, 'audio': how, 'seconds': round(sec, 1)}, ensure_ascii=False), flush=True)
    print(f'できた：{out}（{ow}x{oh}・{fps}fps・{n} コマ・音 {how or "なし"}・{sec:.0f} 秒）', flush=True)


def render(a, vsrc, ow, oh, no_up, dst, cancel, log, t_start):
    """④ vsrc（①② のキャッシュか入力）を RGB のコマにして、出力の大きさ ow×oh に（anime・real は a.down で縮める）エンコードする（音なし）。→ コマの数"""
    info, why = probe_input(vsrc)
    if info is None:
        M.stop('tool_failed', f'高画質にできません：{vsrc} が読めない\n  {why}')
    fps = a.master_fps
    sw, sh = info['w'], info['h']
    vin = []
    if info['fps'] > fps + 0.01:  # 60fps より速い入力（補間しない）：エンジンが素材を読むときと同じ fps のフィルタで間引く
        vin.append(f'fps={fps}')
    pre = []
    if no_up and (sw, sh) != (ow, oh):  # なし：奇数の幅・高さは 1 画素切って偶数に
        vin.append(f'crop={ow}:{oh}:0:0')
        sw, sh = ow, oh
    elif (sw, sh) != (ow, oh):  # マスターの区間と同じ縮め方（__main__.segment：scale=<幅>:<高さ>:flags=area）
        pre.append(f'scale={ow}:{oh}:flags={a.down}')
    total = max(1, int(round(info['frames'] * (fps / info['fps'] if info['fps'] > fps + 0.01 else 1))))
    fb = sw * sh * 3
    with open(log, 'a', encoding='utf-8', errors='replace') as lf:
        dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', str(vsrc), '-map', '0:v:0'] + (['-vf', ','.join(vin)] if vin else []) +
                               ['-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE, stderr=lf)
        enc = subprocess.Popen(rgb_encode_cmd(sw, sh, str(fps), with_vf(vcodec('libx264', {}), pre), dst), stdin=subprocess.PIPE, stderr=lf)
        n, last = 0, 0.0
        try:
            while True:
                buf = dec.stdout.read(fb)
                if len(buf) < fb:
                    break
                try:
                    enc.stdin.write(buf)
                except OSError:  # エンコードの ffmpeg が先に終わった（失敗。下でログの終わりを出して止める）
                    break
                n += 1
                if cancel.exists():
                    raise M.Cancelled()
                if time.time() - last >= 2:
                    last = time.time()
                    print(f'PROGRESS {n} {max(n, total)} {last - t_start:.0f}', flush=True)
            try:
                enc.stdin.close()
            except OSError:
                pass
            enc.wait()
            if dec.poll() is None:  # エンコードが先に終わったとき、読むほうも止める
                M.kill_tree(dec)
            dec.wait()
        except BaseException:
            for p in (dec, enc):
                if p.poll() is None:
                    M.kill_tree(p)
            raise
    if dec.returncode or enc.returncode or n == 0:
        tail = Path(log).read_text(encoding='utf-8', errors='replace')[-1200:]
        M.stop('tool_failed', f'高画質にできません：縮めてエンコードが失敗（読む {dec.returncode}・書く {enc.returncode}・{n} コマ）\n{tail}')
    print(f'PROGRESS {n} {n} {time.time() - t_start:.0f}', flush=True)
    return n


def mux(vtmp, src, out, audio, log):
    """映像（vtmp）に入力の最初の音をのせて out に（書き終えてから名前を付ける）。→ 'copy'・'aac'・None（音なし）"""
    part = out.with_name(out.stem + '.part' + out.suffix)
    tries = ([('copy', ['-c:a', 'copy'])] if audio in COPY_AUDIO else []) + [('aac', ['-c:a', 'aac', '-b:a', '256k'])] if audio else [(None, [])]
    for how, ac in tries:
        with open(log, 'a', encoding='utf-8', errors='replace') as lf:
            r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(vtmp), '-i', str(src), '-map', '0:v', '-map', '1:a:0?', '-c:v', 'copy'] + ac +
                               ['-movflags', '+faststart', str(part)], stdout=lf, stderr=lf)
        if r.returncode == 0:
            os.replace(part, out)
            return how
    tail = Path(log).read_text(encoding='utf-8', errors='replace')[-1200:]
    M.stop('tool_failed', f'高画質にできません：音をのせるのが失敗\n{tail}')
