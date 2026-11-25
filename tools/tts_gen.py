"""TTS を1本生成する（編集画面の「生成」ボタンから、Mittler のサーバーが呼ぶ）。標準ライブラリだけ。
  python tts_gen.py < 依頼.json   → 標準出力に {"ok": true, "out": …, "dur": 秒}
依頼：{engine: "gemini" | "voicevox", text, out（保存先の絶対パス .wav）,
       gemini: {model, voice, style},                 … このリポジトリの中の tools/gen/gemini_tts.py を動かす（鍵は環境変数 GEMINI_API_KEY か資格情報マネージャーの ps:GEMINI_API_KEY）
       voicevox: {speaker, speedScale, pitchScale, intonationScale, volumeScale, prePhonemeLength, postPhonemeLength, url},
       voicevox_url（サーバーが渡す PC の設定 mittler.voicevox.url）}
Gemini TTS は文字（とスタイル）を Google に送る。VOICEVOX はこのPCのエンジン（既定 http://127.0.0.1:50021。PC の設定で変えられる）だけ。
"""
import json
import subprocess
import sys
import urllib.parse
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pyengine'))
from mittler.i18n import t  # noqa: E402（失敗の理由の言葉。環境変数 MITTLER_LANG。標準ライブラリだけ）

GEMINI_TTS = Path(__file__).resolve().parent / 'gen' / 'gemini_tts.py'  # このリポジトリに写したもの（どのPCでも同じ。鍵は資格情報マネージャーの ps:GEMINI_API_KEY）


def dur_of(p):
    with wave.open(str(p), 'rb') as w:
        return w.getnframes() / w.getframerate()


def gemini(req, out):
    g = req.get('gemini') or {}
    cmd = [sys.executable, '-X', 'utf8', str(GEMINI_TTS), '--text', req['text'], '--style', g.get('style', ''), '--voice', g.get('voice', 'Kore'),
           '--out', str(out), '--overwrite']
    if g.get('model'):
        cmd += ['--model', g['model']]
    if req.get('dictionary'):
        cmd += ['--dictionary', req['dictionary']]  # 作品の読み辞書（pronunciation.json）
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
    if r.returncode or not out.exists():
        raise RuntimeError(t('py.tts.geminiFail', err=(r.stderr or r.stdout)[-800:]))


def voicevox(req, out):
    v = req.get('voicevox') or {}
    # エンジンの場所：クリップの voicevox.url → サーバーが渡す PC の設定（mittler.voicevox.url。無ければ server/defaults.js の既定）→ このPCの既定
    base = (v.get('url') or req.get('voicevox_url') or 'http://127.0.0.1:50021').rstrip('/')
    if v.get('speaker') is None:
        raise RuntimeError(t('py.tts.noSpeaker'))
    spk = int(v['speaker'])
    q = urllib.request.Request(f"{base}/audio_query?{urllib.parse.urlencode({'text': req['text'], 'speaker': spk})}", method='POST')
    with urllib.request.urlopen(q, timeout=60) as r:
        query = json.loads(r.read().decode('utf-8'))
    for k in ('speedScale', 'pitchScale', 'intonationScale', 'volumeScale', 'prePhonemeLength', 'postPhonemeLength'):
        if v.get(k) is not None:
            query[k] = float(v[k])
    s = urllib.request.Request(f'{base}/synthesis?speaker={spk}', data=json.dumps(query).encode('utf-8'),
                               headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(s, timeout=120) as r:
        data = r.read()
    out.write_bytes(data)


def tempo(req, p):
    """生成のあとの速さ（依頼の tempo。0.5〜2、1 なら何もしない）：ffmpeg の atempo（高さは変えない）で同じファイルに。
    クリップの tempo・キャラ設定の tts.tempo（editor/ops.js の ttsTempo。2026-11-14 使ってみた知らせ：「生成したあと atempo=1.15」）"""
    v = float(req.get('tempo') or 1)
    if abs(v - 1) < 1e-6:
        return
    v = max(0.5, min(2.0, v))
    tmp2 = p.with_name(p.stem + '.tempo.wav')
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(p), '-filter:a', f'atempo={v:.6f}', '-c:a', 'pcm_s16le', str(tmp2)], check=True, capture_output=True, timeout=300)
        tmp2.replace(p)
    finally:
        if tmp2.exists():
            tmp2.unlink()


def main():
    req = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    out = Path(req['out'])
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.tmp.wav')
    try:
        if not (req.get('text') or '').strip():
            raise RuntimeError(t('py.tts.empty'))
        (gemini if req.get('engine', 'gemini') == 'gemini' else voicevox)(req, tmp)
        tempo(req, tmp)
        tmp.replace(out)
        print(json.dumps({'ok': True, 'out': str(out), 'dur': round(dur_of(out), 6)}, ensure_ascii=False))
    except Exception as e:  # 失敗は理由を返す（編集画面に出す）
        if tmp.exists():
            tmp.unlink()
        print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
