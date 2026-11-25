# Mittler：OpenAI の Image API（GPT Image）で絵を 1 枚作る（2026-11-15。Codex とは別口・
# モデルを選べる・API キーは資格情報マネージャー）。🎬 の開始・終了の絵で、アダプタ tools/openai_image_jobs.py が呼ぶ。
"""Generate one image with the OpenAI Image API and save it as PNG.

No refs  -> POST /v1/images/generations (JSON)
With refs -> POST /v1/images/edits (multipart, image[] repeated; up to 16)

The API key is read from the environment variable OPENAI_API_KEY, else from Windows Credential Manager
(generic credential "ps:OPENAI_API_KEY", the PowerShell SecretManagement CredMan vault; tools/gen/credman_secret.py).
The key is never printed or written anywhere.

Writes <out> (PNG) and <out>.openai.json (model, size, quality, refs, usage; no key), and prints one JSON line at the end:
  {"ok": true, "width": W, "height": H, "model": ..., "size": ..., "quality": ..., "usage": {...}}

  python tools/gen/openai_image.py --prompt-file p.txt --out out.png [--ref a.png ...] [--model gpt-image-2.5-sunburst]
                                   [--size 2048x1152] [--quality high] [--background auto]
"""
import argparse
import base64
import json
import mimetypes
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

API = os.environ.get('MITTLER_OPENAI_BASE') or 'https://api.openai.com/v1'  # 確かめ用に偽のサーバーへ向けられる（tools/smoke_openai_image.py）
DEFAULT_MODEL = 'gpt-image-2.5-sunburst'
KEY_NAME = 'OPENAI_API_KEY'
MAX_REFS = 16
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
    if v is not None and not v.strip():  # 名前だけあって中身が空（cmdkey の /pass で貼り付けが通らなかったとき。2026-11-15 mittler-mv の報告）
        raise Fail(f'"ps:{KEY_NAME}" exists in Windows Credential Manager but is empty. Copy the key and run: '
                   f'python <mittler>/tools/gen/credman_secret.py --set-from-clipboard {KEY_NAME}')
    return v.strip() if v else None


def multipart(fields, files):
    """fields: [(name, str)], files: [(name, path)] → (body, content_type)"""
    b = '----mittler' + uuid.uuid4().hex
    out = []
    for k, v in fields:
        out += [f'--{b}\r\n'.encode(), f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode(), str(v).encode('utf-8'), b'\r\n']
    for k, p in files:
        p = Path(p)
        ct = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        out += [f'--{b}\r\n'.encode(), f'Content-Disposition: form-data; name="{k}"; filename="{p.name}"\r\n'.encode(),
                f'Content-Type: {ct}\r\n\r\n'.encode(), p.read_bytes(), b'\r\n']
    out.append(f'--{b}--\r\n'.encode())
    return b''.join(out), f'multipart/form-data; boundary={b}'


def post(url, body, ctype, key):
    """やり直すのは 429・5xx・つながらないときだけ（3 回まで）。鍵・内容の間違いはすぐ止める"""
    last = None
    for i in range(3):
        if i:
            time.sleep(10 * i)
        req = urllib.request.Request(url, data=body, method='POST', headers={'Authorization': f'Bearer {key}', 'Content-Type': ctype})
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prompt-file', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--ref', action='append', default=[])
    ap.add_argument('--model', default='')
    ap.add_argument('--size', default='auto')
    ap.add_argument('--quality', default='auto')
    ap.add_argument('--background', default='auto')
    a = ap.parse_args()
    key = api_key()
    if not key:
        raise Fail(f'{KEY_NAME} is missing (Windows Credential Manager "ps:{KEY_NAME}" or the environment variable {KEY_NAME}). '
                   f'Copy the key and run: python <mittler>/tools/gen/credman_secret.py --set-from-clipboard {KEY_NAME}')
    if len(a.ref) > MAX_REFS:
        raise Fail(f'too many reference images ({len(a.ref)} > {MAX_REFS})')
    prompt = Path(a.prompt_file).read_text(encoding='utf-8')
    model = a.model or DEFAULT_MODEL
    params = {'model': model, 'prompt': prompt, 'n': 1, 'size': a.size, 'quality': a.quality, 'output_format': 'png', 'background': a.background}
    t0 = time.time()
    if a.ref:
        body, ctype = multipart([(k, v) for k, v in params.items()], [('image[]', r) for r in a.ref])
        res = post(API + '/images/edits', body, ctype, key)
    else:
        res = post(API + '/images/generations', json.dumps(params).encode('utf-8'), 'application/json', key)
    d = (res.get('data') or [{}])[0]
    if not d.get('b64_json'):
        raise Fail('no image in the response')
    png = base64.b64decode(d['b64_json'])
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + '.part')
    tmp.write_bytes(png)
    os.replace(tmp, out)
    w, h = png_size(png)
    info = {'ok': True, 'width': w, 'height': h, 'model': model, 'size': res.get('size') or a.size, 'quality': res.get('quality') or a.quality,
            'usage': res.get('usage'), 'seconds': round(time.time() - t0, 1)}
    rec = dict(info, endpoint='edits' if a.ref else 'generations', refs=[str(r) for r in a.ref], background=a.background,
               created=datetime.now().isoformat(timespec='seconds'), prompt=prompt)
    Path(str(out) + '.openai.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(info, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Fail as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
