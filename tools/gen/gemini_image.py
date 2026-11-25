# Mittler：Gemini の画像生成（Nano Banana）で絵を 1 枚作る（2026-11-19。モデルを選べる・既定はいちばんよいモデルと品質・
# 解像度の既定は 2K・API キーは Gemini TTS と共用（資格情報マネージャー）・参照画像も渡せる）。
# 🎬 の開始・終了の絵（アダプタ tools/gemini_image_jobs.py）と、素材の絵（tools/mittler_api.py の gen-image）が呼ぶ。
"""Generate one image with the Gemini API (Nano Banana models) and save it as PNG.

POST {base}/models/{model}:generateContent  (header x-goog-api-key)
  contents: text + reference images (inline_data, up to 14)
  generationConfig: responseModalities ["IMAGE"], imageConfig {aspectRatio, imageSize "1K"/"2K"/"4K"}

The API key is the same as Gemini TTS: the environment variable GEMINI_API_KEY, else Windows Credential Manager
(generic credential "ps:GEMINI_API_KEY", the PowerShell SecretManagement CredMan vault; tools/gen/credman_secret.py).
The key is never printed or written anywhere.

Writes <out> (PNG) and <out>.gemini.json (model, aspect ratio, image size, refs, usage; no key), and prints one JSON line at the end:
  {"ok": true, "width": W, "height": H, "model": ..., "aspect_ratio": ..., "image_size": ..., "usage": {...}}

  python tools/gen/gemini_image.py --prompt-file p.txt --out out.png [--ref a.png ...] [--model gemini-3-pro-image]
                                   [--aspect 16:9] [--image-size 2K]
"""
import argparse
import base64
import io
import json
import mimetypes
import os
import struct
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

API = os.environ.get('MITTLER_GEMINI_BASE') or 'https://generativelanguage.googleapis.com/v1beta'  # 確かめ用に偽のサーバーへ向けられる（tools/smoke_gemini_image.py）
DEFAULT_MODEL = 'gemini-3-pro-image'  # Nano Banana Pro（Google の説明で最上位：スタジオ品質・4K まで）
DEFAULT_SIZE = '2K'
SIZES = ('1K', '2K', '4K')
ASPECTS = ('1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9')
KEY_NAME = 'GEMINI_API_KEY'
MAX_REFS = 14
RETRY_STATUS = {429, 500, 502, 503, 504}
TIMEOUT = 900


class Fail(Exception):
    pass


def api_key():
    v = os.environ.get(KEY_NAME, '').strip()
    if v:
        return v
    if os.name != 'nt':
        return None
    from credman_secret import _read_credman
    v = _read_credman(f'ps:{KEY_NAME}')
    if v is not None and not v.strip():
        raise Fail(f'"ps:{KEY_NAME}" exists in Windows Credential Manager but is empty. Copy the key and run: '
                   f'python <mittler>/tools/gen/credman_secret.py --set-from-clipboard {KEY_NAME}')
    return v.strip() if v else None


def pick_aspect(w, h):
    """動画の縦横 → いちばん近い縦横の比（Nano Banana が受けるもの）"""
    a = w / h
    return min(ASPECTS, key=lambda s: abs(int(s.split(':')[0]) / int(s.split(':')[1]) - a))


def post(url, body, key):
    """やり直すのは 429・5xx・つながらないときだけ（3 回まで）。鍵・内容の間違いはすぐ止める"""
    last = None
    for i in range(3):
        if i:
            time.sleep(10 * i)
        req = urllib.request.Request(url, data=body, method='POST', headers={'x-goog-api-key': key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            try:
                msg = (json.loads(e.read().decode('utf-8', 'replace')).get('error') or {}).get('message') or ''
            except Exception:
                msg = ''
            last = Fail(f'HTTP {e.code}: {msg}'.strip())
            if e.code not in RETRY_STATUS:
                raise last
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = Fail(f'network: {e}')
        print(f'retry {i + 1}: {last}', file=sys.stderr)
    raise last


def png_size(data):
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return struct.unpack('>II', data[16:24])
    return None, None


def render_python():
    """Pillow の入っている python：環境変数 MITTLER_RENDER_PYTHON → 作品（いまのフォルダ）の .mittler/env.json の render_python"""
    p = os.environ.get('MITTLER_RENDER_PYTHON', '').strip()
    if p and os.path.isfile(p):
        return p
    for d in ('.mittler', '.claude-cut'):
        try:
            p = (json.loads(Path(d, 'env.json').read_text(encoding='utf-8')).get('render_python') or '').strip()
        except (OSError, ValueError):
            p = ''
        if p and os.path.isfile(p):
            return p
    return ''


def to_png(data, mime):
    """返ってきた絵を PNG に。Gemini の generateContent は JPEG で返し、PNG を頼む欄が無い（2026-11-19 に確かめた）。
    この python に Pillow が無ければ、描く python（Pillow が必ず入っている）に写してもらう"""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return data
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).save(buf, 'PNG')
        return buf.getvalue()
    except ImportError:
        pass
    py = render_python()
    if not py:
        raise Fail(f'the image came back as {mime}; Pillow (or the render python in .mittler/env.json / MITTLER_RENDER_PYTHON) is needed to save it as PNG')
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td, 'in.img'), Path(td, 'out.png')
        src.write_bytes(data)
        r = subprocess.run([py, '-c', 'import sys\nfrom PIL import Image\nImage.open(sys.argv[1]).save(sys.argv[2], "PNG")', str(src), str(dst)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode or not dst.is_file():
            raise Fail(f'could not convert the {mime} image to PNG with {py}: {(r.stderr or "").strip()[-300:]}')
        return dst.read_bytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prompt-file', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--ref', action='append', default=[])
    ap.add_argument('--model', default='')
    ap.add_argument('--aspect', default='16:9')
    ap.add_argument('--image-size', default=DEFAULT_SIZE)
    a = ap.parse_args()
    key = api_key()
    if not key:
        raise Fail(f'{KEY_NAME} is missing (Windows Credential Manager "ps:{KEY_NAME}" or the environment variable {KEY_NAME}; the same key as Gemini TTS). '
                   f'Copy the key and run: python <mittler>/tools/gen/credman_secret.py --set-from-clipboard {KEY_NAME}')
    if len(a.ref) > MAX_REFS:
        raise Fail(f'too many reference images ({len(a.ref)} > {MAX_REFS})')
    size = a.image_size.upper()
    if size not in SIZES:
        raise Fail(f'image size must be one of {", ".join(SIZES)} (got {a.image_size})')
    if a.aspect not in ASPECTS:
        raise Fail(f'aspect ratio must be one of {", ".join(ASPECTS)} (got {a.aspect})')
    prompt = Path(a.prompt_file).read_text(encoding='utf-8')
    model = a.model or DEFAULT_MODEL
    parts = [{'text': prompt}]
    for r in a.ref:
        p = Path(r)
        parts.append({'inline_data': {'mime_type': mimetypes.guess_type(p.name)[0] or 'image/png', 'data': base64.b64encode(p.read_bytes()).decode('ascii')}})
    body = {'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'responseModalities': ['IMAGE'], 'imageConfig': {'aspectRatio': a.aspect, 'imageSize': size}}}
    if model.startswith('gemini-2.5'):  # 初代 Nano Banana は解像度を選べない（1K 相当だけ）
        del body['generationConfig']['imageConfig']['imageSize']
    t0 = time.time()
    res = post(f'{API}/models/{model}:generateContent', json.dumps(body).encode('utf-8'), key)
    img, mime, texts = None, '', []
    for c in res.get('candidates') or []:
        for part in ((c.get('content') or {}).get('parts') or []):
            d = part.get('inlineData') or part.get('inline_data')
            if d and d.get('data') and not part.get('thought'):  # 考えている途中の絵（thought）は使わない
                img, mime = base64.b64decode(d['data']), d.get('mimeType') or d.get('mime_type') or ''
            elif part.get('text'):
                texts.append(part['text'])
    if img is None:
        why = (res.get('promptFeedback') or {}).get('blockReason') or ((res.get('candidates') or [{}])[0].get('finishReason')) or ''
        raise Fail('no image in the response' + (f' ({why})' if why else '') + (f': {" ".join(texts)[:300]}' if texts else ''))
    png = to_png(img, mime)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + '.part')
    tmp.write_bytes(png)
    os.replace(tmp, out)
    w, h = png_size(png)
    info = {'ok': True, 'width': w, 'height': h, 'model': model, 'aspect_ratio': a.aspect, 'image_size': size,
            'usage': res.get('usageMetadata'), 'seconds': round(time.time() - t0, 1)}
    rec = dict(info, refs=[str(r) for r in a.ref], returned_mime=mime, created=datetime.now().isoformat(timespec='seconds'), prompt=prompt,
               text=' '.join(texts)[:2000] if texts else '')
    Path(str(out) + '.gemini.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(info, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Fail as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
