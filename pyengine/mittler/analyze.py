"""クリップの解析（編集画面の右クリック・tools/mittler_api.py の analyze から。サーバーが同じ PC の解析用の python（PC の設定 mittler.analysis.python・タイムラインの settings.analysis_python）で動かす）。
  python -m mittler.analyze <kind> <入力のファイル> <出力のフォルダ> [--from 秒] [--to 秒]
kind（素材の --from〜--to の区間だけ。時刻はすべて区間の頭からの秒）：
  beats       拍（librosa）                      → data.beats [[秒, 小節の頭か]]・data.tempo
  transcribe  文字起こし（faster-whisper large-v3、単語の時刻つき） → data.segments [{start, end, text, words:[{start, end, word}]}]
  stems       ボーカルと伴奏に分ける（demucs htdemucs）      → vocals.wav・no_vocals.wav
  pose        人のポーズ（YOLO11 pose。動画はコマごと）    → pose.json [{t, people:[{box, conf, kps:[[x, y, 信頼度]…17]}]}]（座標は 0〜1）
  mask        人のマスク（YOLO11 seg）             → 動画は mask.mp4（白＝人）、絵は mask.png
  cutout      人の切り抜き（rembg u2net_human_seg。絵だけ）   → cutout.png（透明つき）
出すもの：出力のフォルダに result.json {kind, ok, files:{名前: ファイル}, data, summary, from, to} と、上のファイル。
モデルの置き場は AV_AI_MODELS（無ければ、作者の PC の既定（server/defaults.author.json の analysisModels）→ ~/.cache/mittler/av_ai_models。tools/av_ai_check.py と同じ）。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .defaults import author
from .i18n import t  # 要約・理由の文の言葉（環境変数 MITTLER_LANG。サーバーが渡す）

MODELS = Path(os.environ.get('AV_AI_MODELS', author('analysisModels') or Path.home() / '.cache' / 'mittler' / 'av_ai_models'))
os.environ.setdefault('HF_HOME', str(MODELS / 'hf'))
os.environ.setdefault('TORCH_HOME', str(MODELS / 'torch'))
os.environ.setdefault('U2NET_HOME', str(MODELS / 'rembg'))
os.environ.setdefault('YOLO_CONFIG_DIR', str(MODELS / 'ultralytics'))
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
U2NET = 'u2net_human_seg'


def u2net_home(name=U2NET):
    """rembg のモデル（<name>.onnx）のあるフォルダを U2NET_HOME に（2026-11-16）。rembg は U2NET_HOME の直下の <name>.onnx だけを見て、無ければ
    黙ってインターネット（GitHub）から取ってくる。ほかの道具で取ったモデルは rembg/models/<name>/<name>.onnx のように深い所にあることがあるので、
    直下に無ければ U2NET_HOME の下を探して、見つかったフォルダにする。見つからなければ False（取りに行くことを知らせる）。tools/av_ai_check.py と同じ"""
    home = Path(os.environ['U2NET_HOME'])
    if (home / f'{name}.onnx').is_file():
        return True
    try:
        hit = next((p for p in home.rglob(f'{name}.onnx') if p.is_file()), None) if home.is_dir() else None
    except OSError:
        hit = None
    if hit is not None:
        os.environ['U2NET_HOME'] = str(hit.parent)
        return True
    return False


def seg_args(a):
    out = []
    if a.t0 is not None:
        out += ['-ss', f'{a.t0:.4f}']
    if a.t1 is not None:
        out += ['-t', f'{max(0.05, a.t1 - (a.t0 or 0)):.4f}']
    return out


def audio_wav(a, tmp, sr, ch):
    """入力の区間の音を WAV に（ffmpeg）"""
    p = Path(tmp) / f'seg_{sr}_{ch}.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *seg_args(a), '-i', a.input, '-vn', '-ac', str(ch), '-ar', str(sr), '-c:a', 'pcm_s16le', str(p)], check=True)
    return p


def video_seg(a, tmp):
    """入力の区間の動画（コマを正しく切るため作り直す）"""
    if a.t0 is None and a.t1 is None:
        return a.input
    p = Path(tmp) / 'seg.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *seg_args(a), '-i', a.input, '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '12', str(p)], check=True)
    return str(p)


def fps_of(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=avg_frame_rate', '-of', 'csv=p=0', path], capture_output=True, text=True).stdout.strip()
    n, _, d = r.partition('/')
    return float(n) / float(d or 1) if n else 30.0


def yolo(name):
    from ultralytics import YOLO
    w = MODELS / 'ultralytics'
    w.mkdir(parents=True, exist_ok=True)
    cwd = os.getcwd(); os.chdir(w)  # 重みは <モデルの置き場>\ultralytics に（名前だけ渡すと今のフォルダに落ちる）
    try:
        return YOLO(name)
    finally:
        os.chdir(cwd)


def k_beats(a, out, tmp):
    import librosa
    import numpy as np
    y, sr = librosa.load(str(audio_wav(a, tmp, 22050, 1)), sr=22050, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units='time')
    on = librosa.onset.onset_strength(y=y, sr=sr)
    tm = librosa.times_like(on, sr=sr)
    strength = [float(np.interp(t, tm, on)) for t in beats]
    # 小節の頭：4拍ごとの並びのうち、拍の強さの合計がいちばん大きい位置から（ざっくり）
    ph = max(range(4), key=lambda k: sum(strength[k::4])) if len(beats) >= 4 else 0
    rows = [[round(float(t), 4), (i - ph) % 4 == 0] for i, t in enumerate(beats)]
    tempo = float(tempo[0] if hasattr(tempo, '__len__') else tempo)
    (out / 'beats.json').write_text(json.dumps({'tempo': tempo, 'beats': rows}, ensure_ascii=False), encoding='utf-8')
    return {'files': {'beats': 'beats.json'}, 'data': {'tempo': tempo, 'beats': rows}, 'summary': t('py.an.beats', tempo=f'{tempo:.1f}', n=len(rows))}


def k_transcribe(a, out, tmp):
    from faster_whisper import WhisperModel
    m = WhisperModel('large-v3', device='cuda', compute_type='float16', download_root=str(MODELS / 'whisper'))
    segs, info = m.transcribe(str(audio_wav(a, tmp, 16000, 1)), language=a.lang or None, word_timestamps=True, vad_filter=False)
    rows = [{'start': round(s.start, 3), 'end': round(s.end, 3), 'text': s.text.strip(),
             'words': [{'start': round(w.start, 3), 'end': round(w.end, 3), 'word': w.word} for w in (s.words or [])]} for s in segs]
    (out / 'transcript.json').write_text(json.dumps({'language': info.language, 'segments': rows}, ensure_ascii=False, indent=1), encoding='utf-8')
    txt = ' '.join(r['text'] for r in rows)
    return {'files': {'transcript': 'transcript.json'}, 'data': {'language': info.language, 'segments': rows},
            'summary': t('py.an.words', n=len(rows), txt=txt[:40] + ('…' if len(txt) > 40 else ''))}


def k_stems(a, out, tmp):
    import shutil
    wav = audio_wav(a, tmp, 44100, 2)
    r = subprocess.run([sys.executable, '-m', 'demucs', '-n', 'htdemucs', '--two-stems', 'vocals', '-o', str(Path(tmp) / 'demucs'), str(wav)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError(t('py.an.demucsFail', err=r.stderr[-800:]))
    d = next((Path(tmp) / 'demucs').rglob('vocals.wav')).parent
    for n in ('vocals.wav', 'no_vocals.wav'):
        shutil.copyfile(d / n, out / n)
    return {'files': {'vocals': 'vocals.wav', 'no_vocals': 'no_vocals.wav'}, 'data': {}, 'summary': t('py.an.stems')}


def k_pose(a, out, tmp):
    m = yolo('yolo11x-pose.pt')
    img = Path(a.input).suffix.lower() in IMAGE_EXT
    src = a.input if img else video_seg(a, tmp)
    fps = 0 if img else fps_of(src)
    frames = []
    for i, r in enumerate(m.predict(src, device=0, stream=True, verbose=False)):
        h, w = r.orig_shape
        people = []
        if r.boxes is not None and r.keypoints is not None:
            for b, k, c in zip(r.boxes.xyxy.tolist(), r.keypoints.data.tolist(), r.boxes.conf.tolist()):
                people.append({'box': [round(b[0] / w, 4), round(b[1] / h, 4), round(b[2] / w, 4), round(b[3] / h, 4)], 'conf': round(c, 3),
                               'kps': [[round(p[0] / w, 4), round(p[1] / h, 4), round(p[2], 3)] for p in k]})
        frames.append({'t': round(i / fps, 4) if fps else 0, 'people': people})
    (out / 'pose.json').write_text(json.dumps({'fps': fps, 'frames': frames}, ensure_ascii=False), encoding='utf-8')
    n = max((len(f['people']) for f in frames), default=0)
    return {'files': {'pose': 'pose.json'}, 'data': {'frames': len(frames), 'max_people': n}, 'summary': t('py.an.pose', frames=len(frames), n=n)}


def k_mask(a, out, tmp):
    import numpy as np
    import cv2
    m = yolo('yolo11x-seg.pt')
    img = Path(a.input).suffix.lower() in IMAGE_EXT
    src = a.input if img else video_seg(a, tmp)
    fps = 0 if img else fps_of(src)
    writer, n, hit = None, 0, 0
    try:
        for r in m.predict(src, device=0, stream=True, verbose=False, classes=[0], retina_masks=True):
            h, w = r.orig_shape
            mk = np.zeros((h, w), np.uint8)
            if r.masks is not None and len(r.masks):
                mk = (r.masks.data.cpu().numpy().max(0) > 0.5).astype(np.uint8) * 255
                if mk.shape != (h, w):
                    mk = cv2.resize(mk, (w, h), interpolation=cv2.INTER_LINEAR)
                hit += 1
            if img:
                cv2.imwrite(str(out / 'mask.png'), mk)
            else:
                if writer is None:
                    writer = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', f'{w}x{h}', '-r', f'{fps:.6f}', '-i', '-',
                                               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '14', str(out / 'mask.mp4')], stdin=subprocess.PIPE)
                writer.stdin.write(mk.tobytes())
            n += 1
    finally:
        if writer:
            writer.stdin.close(); writer.wait()
    f = 'mask.png' if img else 'mask.mp4'
    return {'files': {'mask': f}, 'data': {'frames': n, 'with_person': hit}, 'summary': t('py.an.mask', n=n, hit=hit)}


def k_cutout(a, out, tmp):
    from PIL import Image
    from rembg import new_session, remove
    if Path(a.input).suffix.lower() not in IMAGE_EXT:
        raise ValueError(t('py.an.cutoutImageOnly'))
    if not u2net_home():
        print(t('py.an.u2netDownload', name=U2NET, home=os.environ['U2NET_HOME']), file=sys.stderr, flush=True)
    im = remove(Image.open(a.input), session=new_session(U2NET))
    im.save(out / 'cutout.png')
    return {'files': {'cutout': 'cutout.png'}, 'data': {'size': list(im.size)}, 'summary': t('py.an.cutout', w=im.size[0], h=im.size[1])}


# 解析のしかた。種類の一覧（クリップの種類ごと・メニューの名前）は analyze_kinds.json の1か所。名前がそこと同じことは tools/smoke_same.py が確かめる
KINDS = {'beats': k_beats, 'transcribe': k_transcribe, 'stems': k_stems, 'pose': k_pose, 'mask': k_mask, 'cutout': k_cutout}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('kind', choices=sorted(KINDS))
    ap.add_argument('input')
    ap.add_argument('outdir')
    ap.add_argument('--from', dest='t0', type=float)
    ap.add_argument('--to', dest='t1', type=float)
    ap.add_argument('--lang', default='ja')
    a = ap.parse_args()
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    res = {'kind': a.kind, 'ok': False, 'input': a.input, 'from': a.t0, 'to': a.t1}
    try:
        with tempfile.TemporaryDirectory(dir=str(out)) as tmp:
            res.update(KINDS[a.kind](a, out, tmp))
        res['ok'] = True
    except Exception as e:  # noqa: BLE001
        res['error'] = f'{type(e).__name__}: {e}'[-1500:]
        if '4551' in res['error'] or 'アプリケーション制御' in res['error']:
            res['error'] += t('py.an.sac')
    res['sec'] = round(time.time() - t0, 1)
    (out / 'result.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print('RESULT', json.dumps({k: res.get(k) for k in ('kind', 'ok', 'summary', 'error', 'sec')}, ensure_ascii=False), flush=True)
    sys.exit(0 if res['ok'] else 1)


if __name__ == '__main__':
    main()
