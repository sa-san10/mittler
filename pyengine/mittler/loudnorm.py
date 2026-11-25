"""書き出しの最後の音の正規化（settings.export.loudnorm。2026-10-21、作者の紙芝居の作品の完全再現で足した）。
dialogue-video の src/normalize_audio.py（`run.ps1 normalize`、納品前の最終工程）と同じ手順・同じ判定：
  1. 正規化前の音（premaster の WAV）を loudnorm で測る（I・TP・LRA を目標に print_format=json）
  2. 測った値を入れて linear=true でもう一度（ピークで linear にできなければ ffmpeg が dynamic にする）→ 同じサンプルレートの s16 の WAV
  3. 映像は premaster の MP4 から copy、音は正規化した WAV を AAC にして載せる（-movflags +faststart）
  4. 正規化した WAV と MP4 の音をもう一度測り、目標（±1 LU）・TP の上限・サンプル数が変わっていないか・映像が同じか を確かめる
settings.export.loudnorm：{I: -16, TP: -2, LRA: 11}（dialogue-video の既定。数字は書いたまま ffmpeg に渡す）、ffmpeg（任意。正規化と AAC に使う ffmpeg。無ければ PATH の ffmpeg）
出すもの（書き出しの <名前>.mp4 の隣）：<名前>_premaster.mp4（正規化前）・<名前>_premaster.wav（正規化前の音）・<名前>_loudnorm.wav（正規化した音）・
<名前>.mp4（正規化したもの）・<名前>_loudnorm.json（測った値と確かめた結果。normalization_review.json と同じ形）
※元の書き出し（作者の紙芝居の作品）は imageio_ffmpeg の ffmpeg 7.1 で正規化していた。正規化した PCM は ffmpeg 9.0.2 でも同じ（WAV の頭の印だけ違う）。
  AAC は ffmpeg の版で変わる（7.1 と 9.0.2 で別のビット列。どちらも元の WAV に対して 27 dB ほどの差の、ふつうの AAC）。
  元の final/movie.mp4 とファイルごと同じにするには、ffmpeg に 7.1 を指定する（2026-10-21 に作者のノート PC で確かめた）。
"""
import hashlib
import json
import math
import re
import subprocess
import wave
from array import array
from pathlib import Path

try:  # 注意・失敗の文の言葉（環境変数 MITTLER_LANG）。報告の JSON（*_loudnorm.json）の中身は変えない
    from .i18n import t
except ImportError:
    from i18n import t


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def normalize(wav, movie, out, cfg, bitrate='192k', ffmpeg='ffmpeg'):
    wav, movie, out = Path(wav), Path(movie), Path(out)
    I, TP, LRA = cfg.get('I', -16), cfg.get('TP', -2), cfg.get('LRA', 11)
    commands = []

    def run(args):
        cmd = [ffmpeg, '-hide_banner', '-nostdin', *map(str, args)]
        commands.append(cmd)
        return subprocess.run(cmd, capture_output=True, check=True)

    def measure(path, tp):
        r = run(['-i', path, '-map', '0:a:0', '-af', f'loudnorm=I={I}:TP={tp}:LRA={LRA}:print_format=json', '-f', 'null', '-'])
        data = json.loads(re.findall(r'\{\s*"input_i".*?\}', r.stderr.decode('utf-8', errors='replace'), re.S)[-1])
        if not math.isfinite(float(data['input_i'])):
            raise ValueError(t('py.ln.silent'))
        return data

    def pcm_info(path):
        with wave.open(str(path), 'rb') as st:
            data = st.readframes(st.getnframes())
            if st.getsampwidth() != 2:
                raise ValueError(t('py.ln.need16'))
            v = array('h', data)
            return {'frames': st.getnframes(), 'rate': st.getframerate(), 'channels': st.getnchannels(),
                    'duration': st.getnframes() / st.getframerate(), 'clipped_samples': sum(x >= 32767 or x <= -32768 for x in v)}

    original = pcm_info(wav)
    norm = out.with_name(out.stem + '_loudnorm.wav')
    old_v = None
    # ピーク（TP の上限 -1）だけが超えたら、目標の TP を 0.5 dB ずつ下げてやり直す（2 回まで。2026-10-24 作者のアニメの作品：
    # 音の大きい作品で、そろえた音が -0.97・AAC が -0.40 になり、書き出しごと止まっていた）。超えなければ今までと同じ1回だけ（作者の紙芝居の作品の再現は変わらない）
    tries = []
    for tp in (TP, round(float(TP) - 0.5, 2), round(float(TP) - 1.0, 2)):
        first = measure(wav, tp)
        flt = (f'loudnorm=I={I}:TP={tp}:LRA={LRA}:measured_I={first["input_i"]}'
               f':measured_TP={first["input_tp"]}:measured_LRA={first["input_lra"]}'
               f':measured_thresh={first["input_thresh"]}:offset={first["target_offset"]}:linear=true:print_format=json')
        proc = run(['-y', '-i', wav, '-af', flt, '-ar', original['rate'], '-c:a', 'pcm_s16le', norm])
        processing = json.loads(re.findall(r'\{\s*"input_i".*?\}', proc.stderr.decode('utf-8', errors='replace'), re.S)[-1])
        final_pcm = pcm_info(norm)
        after = measure(norm, tp)
        run(['-y', '-i', movie, '-i', norm, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', bitrate, '-movflags', '+faststart', out])
        aac = measure(out, tp)
        if old_v is None:
            old_v = run(['-v', 'error', '-i', movie, '-map', '0:v:0', '-c:v', 'copy', '-f', 'hash', '-hash', 'sha256', '-']).stdout
        new_v = run(['-v', 'error', '-i', out, '-map', '0:v:0', '-c:v', 'copy', '-f', 'hash', '-hash', 'sha256', '-']).stdout
        checks = {'pcm_duration_identical': all(original[k] == final_pcm[k] for k in ('frames', 'rate', 'channels')),
                  'wav_no_sample_clipping': final_pcm['clipped_samples'] == 0,
                  'wav_true_peak_ceiling': float(after['input_tp']) <= -1,
                  'wav_loudness_target': abs(float(after['input_i']) - float(I)) <= 1,
                  'video_stream_copy_identical': old_v == new_v,
                  'aac_true_peak_ceiling': float(aac['input_tp']) <= -1,
                  'aac_loudness_target': abs(float(aac['input_i']) - float(I)) <= 1}
        peak_only = all(v for k, v in checks.items() if 'true_peak' not in k)
        tries.append({'tp_target': tp, 'wav_tp': after['input_tp'], 'aac_tp': aac['input_tp'], 'checks': checks})
        if all(checks.values()) or not peak_only:
            break
    # ピークだけが最後まで少し超えた：書き出しは止めない（warning。編集画面に注意を出す）。ほかの確かめが落ちたら止める
    status = 'passed' if all(checks.values()) else 'warning' if peak_only else 'failed'
    report = {'status': status, 'tp_tries': tries,
              'inputs': {'wav': {'path': str(wav), 'sha256': _sha(wav)}, 'mp4': {'path': str(movie), 'sha256': _sha(movie)}},
              'settings': {'target_lufs': I, 'true_peak': TP, 'lra': LRA},
              'method': 'FFmpeg loudnorm two-pass, linear requested; dynamic fallback if peak prevents linear gain（dialogue-video の normalize_audio.py と同じ）',
              'linear_gain_possible': float(first['input_tp']) + float(I) - float(first['input_i']) <= float(TP),
              'normalization_type': processing['normalization_type'], 'before_wav': first, 'processing': processing,
              'after_wav': after, 'after_mp4_aac': aac, 'original_pcm': original, 'normalized_pcm': final_pcm,
              'outputs': {'wav': {'path': str(norm), 'sha256': _sha(norm)}, 'mp4': {'path': str(out), 'sha256': _sha(out)}},
              'checks': checks, 'commands': commands}
    out.with_name(out.stem + '_loudnorm.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if report['status'] == 'failed':
        raise SystemExit(t('py.ln.failed', f=f'{out.stem}_loudnorm.json'))
    if report['status'] == 'warning':
        print('LOUDNORM_WARN ' + t('py.ln.peak', wav=after["input_tp"], aac=aac["input_tp"], tp=tries[-1]["tp_target"], f=f'{out.stem}_loudnorm.json'), flush=True)
    return report
