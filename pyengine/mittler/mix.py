"""音のトラックを混ぜる（ffmpeg だけ。numpy は使わない＝numpy の無い python でも動く）。
  python mix.py <timeline.cut.json> <出力.wav> [--from S --to E]

混ぜるもの（トラックの kind）：
- 'tts'   ：TTS のクリップ。選んでいるテイク（activeTake）の音。{start, dur, in, gain（dB）, fade_in, fade_out}
- 'audio' ：効果音・BGM・そのほかの音。{src, start, dur, in, gain（dB）, norm（dB。素材のピークをそろえる分）, fade_in, fade_out, ramp（[始めの dB, 終わりの dB]）}
- どちらも fade_in_curve・fade_out_curve（ffmpeg の afade の curve の名前。既定 "tri"＝直線。"qsin"＝4分の1サイン（Attention の曲の終わり）など）
トラックの muted、クリップの disabled は混ぜない。素材の場所はタイムラインの root（無ければタイムラインのフォルダ）から。
混ぜたあとピークが settings.audio.peak（既定 0.97、null なら下げない）をこえたら、全体をそこまで下げる（作者の紙芝居の作品の build.py と同じ）。
settings.audio.mixer = "numpy"（2026-10-21）：ffmpeg の amix ではなく、作者の紙芝居の作品の build.py と同じ numpy の計算で混ぜる（mix_numpy。numpy が要る）。
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:  # 失敗の文の頭の言葉（環境変数 MITTLER_LANG）。mix.py を単体の道具として動かしたときは同じフォルダの i18n.py
    from .i18n import t
except ImportError:
    from i18n import t

SR = 48000


CURVES = {'tri', 'qsin', 'hsin', 'esin', 'log', 'ipar', 'qua', 'cub', 'squ', 'cbr', 'par', 'exp', 'iqsin', 'ihsin', 'dese', 'desi', 'losi', 'sinc', 'isinc', 'nofade'}


def _curve(v):
    return v if v in CURVES else 'tri'


def clip_inputs(tl, root):
    """(ファイル, クリップの頭の曲の秒, 素材の何秒目から, 長さ, dB, フェード入り, フェード出, ramp) の並び"""
    out = []
    for tr in tl.get('tracks', []):
        if tr.get('kind') not in ('tts', 'audio') or tr.get('muted') or tr.get('hidden'):
            continue
        for c in tr.get('clips', []):
            if c.get('disabled'):
                continue
            if c.get('type') == 'tts':
                tk = next((k for k in c.get('takes', []) if k['id'] == c.get('activeTake')), None)
                if not tk:
                    continue
                src = tk['src']
            else:
                src = c.get('src')
            if not src:
                continue
            db = float(c.get('gain', 0.0)) + float(c.get('norm', 0.0)) + float(tr.get('gain', 0.0))
            out.append(dict(file=str(root / src), start=float(c['start']), inp=float(c.get('in', 0.0)), dur=float(c['dur']), db=db,
                            fi=float(c.get('fade_in', 0.0)), fo=float(c.get('fade_out', 0.0)), ramp=c.get('ramp'), norm=float(c.get('norm', 0.0)),
                            fic=_curve(c.get('fade_in_curve')), foc=_curve(c.get('fade_out_curve'))))
    return out


def build_cmd(items, t0, t1, out, codec, script=None, script_opt='-/filter_complex'):
    """混ぜる ffmpeg のコマンド。script（ファイルのパス）があれば、フィルタをそのファイルに書いて script_opt で渡す（引数が長くなりすぎるとき。_ffmpeg_mix）"""
    cmd = ['ffmpeg', '-v', 'error', '-y']
    fl = []
    labels = []
    for i, it in enumerate(items):
        cmd += ['-i', it['file']]
        f = [f'aformat=sample_fmts=fltp:sample_rates={SR}:channel_layouts=stereo',
             f"atrim=start={it['inp']:.6f}:duration={it['dur']:.6f}", 'asetpts=PTS-STARTPTS']
        if it['ramp']:  # 音量を始めの dB から終わりの dB へ（norm はそのまま足す）
            a, b = float(it['ramp'][0]) + it['norm'], float(it['ramp'][1]) + it['norm']
            f.append(f"volume='pow(10,({a}+({b}-{a})*t/{max(it['dur'], 1e-6):.6f})/20)':eval=frame")
        elif abs(it['db']) > 1e-9:
            f.append(f"volume={it['db']:.4f}dB")
        if it['fi'] > 0:
            f.append(f"afade=t=in:st=0:d={it['fi']:.6f}" + (f":curve={it['fic']}" if it['fic'] != 'tri' else ''))
        if it['fo'] > 0:
            f.append(f"afade=t=out:st={max(it['dur'] - it['fo'], 0):.6f}:d={it['fo']:.6f}" + (f":curve={it['foc']}" if it['foc'] != 'tri' else ''))
        delay = it['start'] - t0
        if delay < 0:  # 区間より前から鳴っている：頭を切る
            f.append(f'atrim=start={-delay:.6f}')
            f.append('asetpts=PTS-STARTPTS')
            delay = 0.0
        if delay > 0:
            f.append(f'adelay={int(round(delay * 1000))}:all=1')
        fl.append(f'[{i}:a]' + ','.join(f) + f'[a{i}]')
        labels.append(f'[a{i}]')
    total = t1 - t0
    # 無音の土台（長さを決める）
    cmd += ['-f', 'lavfi', '-t', f'{total:.6f}', '-i', f'anullsrc=r={SR}:cl=stereo']
    base = len(items)
    fl.append(f'[{base}:a]aformat=sample_fmts=fltp:sample_rates={SR}:channel_layouts=stereo[base]')
    fl.append('[base]' + ''.join(labels) + f'amix=inputs={len(items) + 1}:normalize=0:duration=first[mix]')
    if script is not None:
        Path(script).write_text(';'.join(fl), encoding='utf-8')
        cmd += [script_opt, str(script)]
    else:
        cmd += ['-filter_complex', ';'.join(fl)]
    cmd += ['-map', '[mix]', '-t', f'{total:.6f}', '-ar', str(SR), '-ac', '2', '-c:a', codec, str(out)]
    return cmd


# Windows は、1つのプロセスに渡せる引数の全部の長さが約 32,000 字まで。こえると「[WinError 206] ファイル名または拡張子が長すぎます」で起動できない。
# クリップ 1 個ごとに -i <ファイル> と 200 字ほどのフィルタが要るので、音・セリフのクリップが 100 個前後で書き出しが落ちていた（2026-11-12）
MAXCMD = 30000
# フィルタをファイルで渡す書き方：ffmpeg 7 から -/filter_complex <ファイル>、その前は -filter_complex_script <ファイル>（新しい ffmpeg には無い）。順に試す
SCRIPT_OPTS = ['-/filter_complex', '-filter_complex_script']


def _cmdlen(cmd):
    return len(subprocess.list2cmdline([str(c) for c in cmd]))


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')


def _ffmpeg_mix(items, t0, t1, out, codec, td, tag='a'):
    """items を混ぜて out に書く。→ None（うまくいった）か、失敗の理由の文。'too long'＝引数が長すぎる（呼ぶ側が分けて混ぜる）。
    引数が短ければ今までどおり（フィルタを引数で渡す）。長ければフィルタを td のファイルに書いて渡す。"""
    cmd = build_cmd(items, t0, t1, out, codec)
    if _cmdlen(cmd) <= MAXCMD:
        r = _run(cmd)
        return None if not r.returncode else r.stderr[-1500:]
    script = Path(td) / f'filter_{tag}.txt'
    err = ''
    for opt in SCRIPT_OPTS:
        cmd = build_cmd(items, t0, t1, out, codec, script, opt)
        if _cmdlen(cmd) > MAXCMD:
            return 'too long'
        r = _run(cmd)
        if not r.returncode:
            return None
        err = r.stderr[-1500:]
        if not re.search(r'Unrecognized option|Option not found|Missing argument|Error splitting the argument list', err):
            break  # 書き方のせいではない失敗：もう片方を試さない
    return err


def _mix_raw(items, t0, t1, raw, td):
    """items を混ぜて raw（pcm_f32le）に書く。引数に入りきらない数のクリップは、入るだけの組に分けて下混ぜ（区間の長さの f32 の WAV）してから、
    その下混ぜを混ぜる。組に分けるのは、前は落ちていた数のときだけ（分けないときの音は今までと同じ）。"""
    err = _ffmpeg_mix(items, t0, t1, raw, 'pcm_f32le', td)
    if err is None:
        return
    if err != 'too long':
        raise SystemExit(t('py.mix.fail', err=err))
    groups, cur, n = [], [], 0
    for it in items:  # -i <ファイル> の分だけで長さが決まる（フィルタはファイルで渡す）。余裕を見て MAXCMD の 8 割まで
        k = _cmdlen(['-i', it['file']]) + 1
        if cur and n + k > MAXCMD * 0.8:
            groups.append(cur)
            cur, n = [], 0
        cur.append(it)
        n += k
    groups.append(cur)
    parts = []
    for gi, g in enumerate(groups):
        part = Path(td) / f'part{gi:03d}.wav'
        err = _ffmpeg_mix(g, t0, t1, part, 'pcm_f32le', td, f'p{gi:03d}')
        if err is not None:
            raise SystemExit(t('py.mix.fail', err=err))
        parts.append(dict(file=str(part), start=t0, inp=0.0, dur=t1 - t0, db=0.0, fi=0.0, fo=0.0, ramp=None, norm=0.0, fic='tri', foc='tri'))
    err = _ffmpeg_mix(parts, t0, t1, raw, 'pcm_f32le', td, 'all')
    if err is not None:
        raise SystemExit(t('py.mix.fail', err=err))


def _decode(path):
    """素材を 48 kHz・2ch の float32 に（作者の紙芝居の作品の build.py の decode と同じ ffmpeg の呼び方）"""
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'f32le', '-ac', '2', '-ar', str(SR), '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def mix_numpy(tl, root, out, t0, t1):
    """settings.audio.mixer = "numpy"（2026-10-21、作者の紙芝居の作品の完全再現で足した）：元の build.py の build_audio と同じ計算で混ぜる。
    - 混ぜる順：トラックの並び（上から）、トラックの中はクリップの並び。小数の足し算の順も元と同じにするため（取り込み器が元の順に並べる）。
    - クリップ：素材を 48 kHz・2ch の float32 に → norm_peak なら素材全体のピークで割って 1 に → in から dur（サンプルに丸める）を切る →
      フェード（直線。fade_in・fade_out をサンプルに丸めた長さ）→ ramp（[始めの dB, 終わりの dB]、直線の dB）→ dB（gain＋トラックの gain、
      norm が数ならそれも）→ start（サンプルに丸める）に足す。
    - 全部を足したあとピークが settings.audio.peak（既定 0.97）をこえたら全体を下げる → [-1, 1] に切って ×32767 の s16。
    フェードの形（fade_*_curve）は直線だけ（元と同じ）。"""
    import numpy as np
    dur = float(tl['duration'])
    n = int(round(dur * SR))
    mixbuf = np.zeros((n, 2), np.float32)
    cache, used = {}, 0
    for tr in tl.get('tracks', []):
        if tr.get('kind') not in ('tts', 'audio') or tr.get('muted') or tr.get('hidden'):
            continue
        for c in tr.get('clips', []):
            if c.get('disabled'):
                continue
            if c.get('type') == 'tts':
                tk = next((k for k in c.get('takes', []) if k['id'] == c.get('activeTake')), None)
                src = tk['src'] if tk else None
            else:
                src = c.get('src')
            if not src:
                continue
            if src not in cache:
                cache[src] = _decode(root / src)
            a = cache[src].copy()
            if c.get('norm_peak'):
                a /= max(1e-6, float(np.abs(a).max()))
            i0 = int(round(float(c.get('in', 0.0)) * SR))
            if i0:
                a = a[i0:]
            a = a[:int(round(float(c['dur']) * SR))]
            L = len(a)
            db = float(c.get('gain', 0.0)) + float(tr.get('gain', 0.0)) + (float(c['norm']) if isinstance(c.get('norm'), (int, float)) else 0.0)
            fi, fo, ramp = float(c.get('fade_in', 0.0)), float(c.get('fade_out', 0.0)), c.get('ramp')
            if fi or fo or ramp:
                env = np.ones(L, np.float32)
                fi, fo = int(round(fi * SR)), int(round(fo * SR))
                if fi:
                    env[:fi] *= np.linspace(0, 1, fi)
                if fo:
                    env[-fo:] *= np.linspace(1, 0, fo)
                if ramp:
                    env *= 10 ** (np.linspace(float(ramp[0]), float(ramp[1]), L) / 20) / 10 ** (db / 20)
                a = a * env[:, None] * 10 ** (db / 20)
            elif db:
                a = a * 10 ** (db / 20)
            s = int(round(float(c['start']) * SR))
            if s < 0:
                a, s = a[-s:], 0
            e = min(n, s + len(a))
            if e > s:
                mixbuf[s:e] += a[:e - s]
                used += 1
    pk = (tl.get('settings', {}).get('audio') or {}).get('peak', 0.97)
    peak = float(np.abs(mixbuf).max()) if n else 0.0
    gain = 1.0
    if pk is not None and peak > float(pk):
        gain = float(pk) / peak
        mixbuf *= gain
    a0, a1 = int(round(t0 * SR)), min(n, int(round(t1 * SR)))
    pcm = (np.clip(mixbuf[a0:a1], -1, 1) * 32767).astype('<i2')
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    import wave
    with wave.open(str(out), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return {'mixer': 'numpy', 'clips': used, 'peak': round(peak, 4), 'gain': round(gain, 4), 'out': str(out), 'duration': round(t1 - t0, 3)}


def mix(timeline, out, t0=0.0, t1=None):
    tlf = Path(timeline).resolve()
    tl = json.loads(tlf.read_text(encoding='utf-8'))
    root = (tlf.parent / tl.get('root', '.')).resolve()
    t1 = tl['duration'] if t1 is None else t1
    if (tl.get('settings', {}).get('audio') or {}).get('mixer') == 'numpy':
        return mix_numpy(tl, root, out, t0, t1)
    items = [it for it in clip_inputs(tl, root) if it['start'] < t1 and it['start'] + it['dur'] > t0]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pk = (tl.get('settings', {}).get('audio') or {}).get('peak', 0.97)
    peak_lim = float(pk) if pk is not None else None  # null なら頭打ちしない（曲をそのまま使う作品）
    with tempfile.TemporaryDirectory(prefix='mittlermix_') as td:
        raw = Path(td) / 'raw.wav'
        _mix_raw(items, t0, t1, raw, td)
        # ピーク（小数のまま。1.0 をこえていても測れる astats で。volumedetect は 0 dB で頭打ち）
        vd = subprocess.run(['ffmpeg', '-v', 'info', '-i', str(raw), '-af', 'astats=measure_perchannel=none:measure_overall=Peak_level', '-f', 'null', '-'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
        m = re.findall(r'Peak level dB:\s*(-?[\d.]+|-inf)', vd)
        peak = 10 ** (float(m[-1]) / 20) if m and m[-1] != '-inf' else 0.0
        gain = peak_lim / peak if (peak_lim is not None and peak > peak_lim) else 1.0
        r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(raw), '-af', f'volume={gain:.6f}', '-c:a', 'pcm_s16le', str(out)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode:
            raise SystemExit(t('py.mix.writeFail', err=r.stderr[-1500:]))
    return {'clips': len(items), 'peak': round(peak, 4), 'gain': round(gain, 4), 'out': str(out), 'duration': round(t1 - t0, 3)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('timeline')
    ap.add_argument('out')
    ap.add_argument('--from', dest='t0', type=float, default=0.0)
    ap.add_argument('--to', dest='t1', type=float)
    a = ap.parse_args()
    print(json.dumps(mix(a.timeline, a.out, a.t0, a.t1), ensure_ascii=False))
    sys.exit(0)
