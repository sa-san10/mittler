"""動画・音声の解析の AI（解析の python。setup/requirements-av-ai.txt を入れたもの）が動くかを、1つずつ実際に推定して確かめる。
  <解析の python> -X utf8 tools\\av_ai_check.py --image <人の写った絵> --song <歌の音> --speech <日本語のセリフの音> --out <出力フォルダ> [--only yolo,whisper,…]
確かめるもの：torch（GPU）・YOLO11 の pose と seg・demucs（ボーカルを取り出す）・faster-whisper large-v3（単語の時刻つき）・
  torchaudio の MMS_FA（強制アラインメント）・librosa（拍）・rembg（人物の切り抜き）。
モデルは環境変数 AV_AI_MODELS のフォルダ（無ければ作者の PC の既定（server/defaults.author.json）→ ~/.cache/mittler/av_ai_models。pyengine/mittler/analyze.py と同じ）の下に
ためる（HF_HOME・TORCH_HOME・ultralytics・rembg）。初めての実行はダウンロードする（インターネットに出る）。
Windows のスマート アプリ コントロールが DLL を止めたら「止められた」と出す（WinError 4551）。
"""
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path


def _author_models():
    try:
        return json.loads((Path(__file__).resolve().parent.parent / 'server' / 'defaults.author.json').read_text(encoding='utf-8')).get('analysisModels') or None
    except (OSError, ValueError):
        return None


MODELS = Path(os.environ.get('AV_AI_MODELS', _author_models() or Path.home() / '.cache' / 'mittler' / 'av_ai_models'))
os.environ.setdefault('HF_HOME', str(MODELS / 'hf'))
os.environ.setdefault('TORCH_HOME', str(MODELS / 'torch'))
os.environ.setdefault('U2NET_HOME', str(MODELS / 'rembg'))
os.environ.setdefault('YOLO_CONFIG_DIR', str(MODELS / 'ultralytics'))
results = []


def step(name):
    def deco(fn):
        def run(a):
            t0 = time.time()
            try:
                msg = fn(a) or ''
                results.append((name, 'OK', f'{msg}（{time.time() - t0:.1f}秒）'))
            except Exception as e:  # noqa: BLE001
                txt = ''.join(traceback.format_exception_only(type(e), e)).strip()
                why = '止められた（スマート アプリ コントロール）' if ('4551' in txt or 'アプリケーション制御' in txt) else '失敗'
                results.append((name, why, txt[-400:]))
            print(f'{results[-1][1]:<6} {name}: {results[-1][2]}', flush=True)
        run.name = name
        return run
    return deco


@step('torch')
def t_torch(a):
    import torch
    ok = torch.cuda.is_available()
    x = (torch.randn(1024, 1024, device='cuda' if ok else 'cpu') @ torch.randn(1024, 1024, device='cuda' if ok else 'cpu')).sum().item()
    return f'torch {torch.__version__}・CUDA {torch.version.cuda}・GPU {torch.cuda.get_device_name(0) if ok else "なし"}・計算 {x:.1f}'


@step('yolo')
def t_yolo(a):
    from ultralytics import YOLO
    w = MODELS / 'ultralytics'
    w.mkdir(parents=True, exist_ok=True)
    out = []
    for name in ('yolo11x-pose.pt', 'yolo11x-seg.pt'):
        cwd = os.getcwd(); os.chdir(w)  # 重みは <モデルの置き場>\ultralytics にダウンロードさせる（名前だけ渡すと今のフォルダに落ちる）
        try:
            m = YOLO(name)
        finally:
            os.chdir(cwd)
        r = m.predict(a.image, device=0, verbose=False)[0]
        n = 0 if r.boxes is None else len(r.boxes)
        out.append(f"{name.split('-')[1].split('.')[0]} 人 {n}")
    return '・'.join(out)


@step('demucs')
def t_demucs(a):
    import subprocess
    o = Path(a.out) / 'demucs'
    r = subprocess.run([sys.executable, '-m', 'demucs', '-n', 'htdemucs', '--two-stems', 'vocals', '-o', str(o), a.song], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError(r.stderr[-600:])
    v = list(o.rglob('vocals.wav'))
    if not v:
        raise RuntimeError('vocals.wav が無い')
    return f'ボーカル {v[0]}'


@step('whisper')
def t_whisper(a):
    from faster_whisper import WhisperModel
    m = WhisperModel('large-v3', device='cuda', compute_type='float16', download_root=str(MODELS / 'whisper'))
    segs, info = m.transcribe(a.speech, language='ja', word_timestamps=True)
    words = [w for s in segs for w in (s.words or [])]
    text = ''.join(w.word for w in words)
    return f'{len(words)} 語「{text[:40]}」 最初の語 {words[0].start:.2f}秒' if words else '語なし'


@step('mms_fa')
def t_mms(a):
    import torch
    import torchaudio
    b = torchaudio.pipelines.MMS_FA
    model = b.get_model().to('cuda')
    import soundfile as sf
    x, sr = sf.read(a.speech, dtype='float32', always_2d=True)  # torchaudio.load は torchaudio 2.9 から torchcodec が要るので、音は soundfile で読む
    wav = torchaudio.functional.resample(torch.from_numpy(x.mean(1)).unsqueeze(0), sr, b.sample_rate)
    with torch.inference_mode():
        em, _ = model(wav.to('cuda'))
    return f'MMS_FA 読めた・出力 {tuple(em.shape)}（ローマ字の文があれば単語ごとの時刻が出せる）'


@step('librosa')
def t_librosa(a):
    import librosa
    y, sr = librosa.load(a.song, sr=22050, mono=True, duration=60)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units='time')
    return f'テンポ {float(tempo[0] if hasattr(tempo, "__len__") else tempo):.1f}・拍 {len(beats)}'


@step('rembg')
def t_rembg(a):
    from PIL import Image
    from rembg import new_session, remove
    home = Path(os.environ['U2NET_HOME'])  # モデルが深い所（rembg/models/<名前>/）にあっても使う（pyengine/mittler/analyze.py の u2net_home と同じ）
    if not (home / 'u2net_human_seg.onnx').is_file() and home.is_dir():
        hit = next((p for p in home.rglob('u2net_human_seg.onnx') if p.is_file()), None)
        if hit is not None:
            os.environ['U2NET_HOME'] = str(hit.parent)
    s = new_session('u2net_human_seg')
    im = remove(Image.open(a.image), session=s)
    p = Path(a.out) / 'rembg.png'
    im.save(p)
    return f'切り抜き {p}'


ALL = [t_torch, t_yolo, t_demucs, t_whisper, t_mms, t_librosa, t_rembg]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', required=True)
    ap.add_argument('--song', required=True)
    ap.add_argument('--speech', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    for k in ('image', 'song', 'speech', 'out'):
        setattr(a, k, str(Path(getattr(a, k)).resolve()))
    Path(a.out).mkdir(parents=True, exist_ok=True)
    only = set(x for x in a.only.split(',') if x)
    for f in ALL:
        if not only or f.name in only:
            f(a)
    bad = [r for r in results if r[1] != 'OK']
    print('---', f'{len(results) - len(bad)}/{len(results)} OK')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
