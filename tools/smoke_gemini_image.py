"""Nano Banana（Gemini の画像生成）の絵のエンジンの確かめ（本物の Gemini には送らない。この PC の偽のサーバーで）。標準だけ。
  python tools/smoke_gemini_image.py
- tools/gen/gemini_image.py：generateContent に文と参照画像（inline_data）・縦横の比と解像度・初代（gemini-2.5）は解像度を送らない・
  考えている途中の絵（thought）は使わない・PNG と記録（鍵は書かない）・JPEG は PNG に（Pillow のある python があれば）・鍵の間違いはやり直さない
- tools/gemini_image_jobs.py：縦横の比・モデルと解像度の決まる順（既定 gemini-3-pro-image・2K）・参照 14 枚まで・使えない解像度は断る
- tools/jobs.py：engine が nanobanana のジョブを流して、done と result.src・model
- tools/mittler_api.py gen-image：作品の settings.image_engine が nanobanana のとき（--size → 比・--quality → 解像度・参照）
"""
import base64
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'pyengine'))
import gemini_image_jobs as NB  # noqa: E402

FAIL = []


def check(ok, msg):
    print(('OK  ' if ok else 'NG  ') + msg)
    if not ok:
        FAIL.append(msg)


def tiny_png(w, h):
    raw = b''.join(b'\x00' + b'\x80\x40\x20' * w for _ in range(h))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


def pil_python():
    """Pillow のある python（JPEG を作る・PNG に直すのを確かめる）。無ければ None"""
    for py in (sys.executable, os.environ.get('MITTLER_RENDER_PYTHON', '')):
        if py and subprocess.run([py, '-c', 'import PIL'], capture_output=True).returncode == 0:
            return py
    return None


SEEN = []
REPLY = {'mime': 'image/png', 'data': tiny_png(32, 18)}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        SEEN.append({'path': self.path, 'key': self.headers.get('x-goog-api-key'), 'body': body})
        if self.headers.get('x-goog-api-key') != 'test-key':
            self.send_response(400); self.end_headers()
            self.wfile.write(json.dumps({'error': {'message': 'API key not valid. Please pass a valid API key.'}}).encode()); return
        parts = [{'text': 'thinking', 'thought': True},
                 {'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(tiny_png(2, 2)).decode()}, 'thought': True},
                 {'inlineData': {'mimeType': REPLY['mime'], 'data': base64.b64encode(REPLY['data']).decode()}}]
        res = {'candidates': [{'content': {'role': 'model', 'parts': parts}, 'finishReason': 'STOP'}],
               'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 20, 'totalTokenCount': 30}}
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
        self.wfile.write(json.dumps(res).encode())


def main():
    srv = HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(os.environ, MITTLER_GEMINI_BASE=f'http://127.0.0.1:{srv.server_port}/v1beta', GEMINI_API_KEY='test-key', MITTLER_LANG='ja')
    gen = [sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'gen' / 'gemini_image.py')]
    with tempfile.TemporaryDirectory(prefix='mittler_nb_') as td:
        td = Path(td)
        (td / 'p.txt').write_text('テストの絵', encoding='utf-8')
        ref = td / 'ref.png'; ref.write_bytes(tiny_png(4, 4))
        # 参照あり・既定のモデルと解像度
        r = subprocess.run(gen + ['--prompt-file', str(td / 'p.txt'), '--out', str(td / 'a.png'), '--ref', str(ref), '--ref', str(ref)],
                           capture_output=True, text=True, encoding='utf-8', env=env, timeout=60)
        info = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {}
        req = json.loads(SEEN[-1]['body']) if SEEN else {}
        parts = ((req.get('contents') or [{}])[0].get('parts') or [])
        ic = (req.get('generationConfig') or {}).get('imageConfig') or {}
        check(r.returncode == 0 and SEEN[-1]['path'] == '/v1beta/models/gemini-3-pro-image:generateContent' and parts[0].get('text') == 'テストの絵'
              and sum(1 for p in parts if 'inline_data' in p) == 2 and parts[1]['inline_data']['mime_type'] == 'image/png'
              and ic == {'aspectRatio': '16:9', 'imageSize': '2K'} and req['generationConfig'].get('responseModalities') == ['IMAGE'],
              f'generateContent に文と参照 2 枚（inline_data）・既定のモデル gemini-3-pro-image・16:9・2K {r.stderr[-300:]}')
        check((td / 'a.png').read_bytes()[:8] == b'\x89PNG\r\n\x1a\n' and info.get('width') == 32 and info.get('height') == 18,
              '考えている途中の絵（thought）は使わず、最後の絵を PNG で書いて幅・高さを出す')
        side = (td / 'a.png.gemini.json').read_text(encoding='utf-8') if (td / 'a.png.gemini.json').is_file() else ''
        check(side and 'test-key' not in side and json.loads(side).get('usage', {}).get('totalTokenCount') == 30, '記録（.gemini.json）に使った量があり、鍵は書かない')
        # 選んだモデル・比・解像度。初代（gemini-2.5）は解像度を送らない
        r = subprocess.run(gen + ['--prompt-file', str(td / 'p.txt'), '--out', str(td / 'b.png'), '--model', 'gemini-nano-banana-2.1', '--aspect', '9:16', '--image-size', '4k'],
                           capture_output=True, text=True, encoding='utf-8', env=env, timeout=60)
        req = json.loads(SEEN[-1]['body'])
        check(r.returncode == 0 and 'gemini-nano-banana-2.1:generateContent' in SEEN[-1]['path'] and req['generationConfig']['imageConfig'] == {'aspectRatio': '9:16', 'imageSize': '4K'},
              '選んだモデル・縦横の比・解像度（小文字の 4k も）')
        r = subprocess.run(gen + ['--prompt-file', str(td / 'p.txt'), '--out', str(td / 'c.png'), '--model', 'gemini-2.5-flash-image'],
                           capture_output=True, text=True, encoding='utf-8', env=env, timeout=60)
        req = json.loads(SEEN[-1]['body'])
        check(r.returncode == 0 and req['generationConfig']['imageConfig'] == {'aspectRatio': '16:9'}, '初代 Nano Banana（gemini-2.5）には解像度を送らない')
        # 使えない比・解像度・参照の数は送る前に止める
        n0 = len(SEEN)
        bad = [subprocess.run(gen + ['--prompt-file', str(td / 'p.txt'), '--out', str(td / 'x.png')] + x, capture_output=True, text=True, encoding='utf-8', env=env, timeout=60)
               for x in (['--aspect', '7:3'], ['--image-size', '8K'], sum([['--ref', str(ref)] for _ in range(15)], []))]
        check(all(b.returncode == 1 for b in bad) and len(SEEN) == n0 and not (td / 'x.png').exists(), '使えない比・解像度・15 枚の参照は送る前に止める')
        # 鍵の間違い：やり直さずに止まる
        n0 = len(SEEN)
        r = subprocess.run(gen + ['--prompt-file', str(td / 'p.txt'), '--out', str(td / 'd.png')], capture_output=True, text=True, encoding='utf-8',
                           env=dict(env, GEMINI_API_KEY='wrong'), timeout=60)
        check(r.returncode == 1 and len(SEEN) - n0 == 1 and 'HTTP 400' in r.stderr and 'wrong' not in r.stderr and not (td / 'd.png').exists(),
              '鍵の間違い（400）：1 回で止まり、理由を出し、鍵は出さない')
        # JPEG で返ってきたら PNG に（本物の Gemini は JPEG で返す）
        py = pil_python()
        if py:
            jp = td / 'j.jpg'
            subprocess.run([py, '-c', 'import sys\nfrom PIL import Image\nImage.new("RGB", (40, 20), (200, 50, 10)).save(sys.argv[1], "JPEG")', str(jp)], check=True)
            REPLY.update(mime='image/jpeg', data=jp.read_bytes())
            r = subprocess.run(gen + ['--prompt-file', str(td / 'p.txt'), '--out', str(td / 'e.png')], capture_output=True, text=True, encoding='utf-8',
                               env=dict(env, MITTLER_RENDER_PYTHON=py), timeout=120)
            info = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {}
            check(r.returncode == 0 and (td / 'e.png').read_bytes()[:8] == b'\x89PNG\r\n\x1a\n' and (info.get('width'), info.get('height')) == (40, 20),
                  f'JPEG で返ってきた絵を PNG にする（Pillow のある python で）{r.stderr[-300:]}')
            REPLY.update(mime='image/png', data=tiny_png(32, 18))
        else:
            print('--  JPEG → PNG は Pillow のある python が無いので確かめない（MITTLER_RENDER_PYTHON に描く python を入れると確かめる）')

        # アダプタ：比・モデルと解像度の決まる順・参照の上限・使えない解像度
        check([NB.pick_aspect(*s) for s in ((1920, 1080), (1080, 1920), (1080, 1080), (2560, 1080), (1080, 1350))] == ['16:9', '9:16', '1:1', '21:9', '4:5'],
              '縦横の比：動画の大きさにいちばん近いもの')
        q = {'engine': 'nanobanana', 'prompt': 'x', 'refs': [], 'width': 1920, 'height': 1080, 'root': str(td), 'project_dir': str(td)}
        b1 = NB.build(dict(q))
        b2 = NB.build(dict(q, default_model='gemini-3.1-flash-image', default_quality='1K'))
        b3 = NB.build(dict(q, model='gemini-nano-banana-2.1', quality='4k', default_model='gemini-3.1-flash-image', default_quality='1K'))
        check((b1['image']['model'], b1['image']['quality'], b1['image']['aspect']) == ('gemini-3-pro-image', '2K', '16:9')
              and (b2['image']['model'], b2['image']['quality']) == ('gemini-3.1-flash-image', '1K')
              and (b3['image']['model'], b3['image']['quality']) == ('gemini-nano-banana-2.1', '4K') and b1['sidecars'] == ['.gemini.json'],
              'モデル・解像度：絵の欄 → PC の設定 → 既定（Nano Banana Pro・2K）')
        try:
            NB.build(dict(q, refs=['r.png'] * 15)); ok = False
        except NB.Refuse:
            ok = True
        check(ok and NB.build(dict(q, refs=['r.png'] * 14))['ok'], '参照は 14 枚まで（15 枚は断る）')
        try:
            NB.build(dict(q, quality='high')); ok = False
        except NB.Refuse:
            ok = True
        check(ok, '使えない解像度（high）は断る')

        # ジョブ係：engine が nanobanana のジョブ
        proj = td / 'proj'; (proj / 'work' / 'jobs').mkdir(parents=True)
        im = NB.build(dict(q, root=str(proj), project_dir=str(proj), refs=['r.png']))['image']
        (proj / 'r.png').write_bytes(tiny_png(4, 4))
        im['out'] = 'assets/frames/p1_start_t1.png'
        (proj / 'work' / 'jobs' / 'job_1.json').write_text(json.dumps({'id': 'job_1', 'kind': 'image', 'clip': 'p1', 'which': 'start_frame', 'state': 'queued', 'image': im}), encoding='utf-8')
        n0 = len(SEEN)
        r = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'jobs.py'), str(proj), '--once'], capture_output=True, text=True, encoding='utf-8', env=env, timeout=120)
        j = json.loads((proj / 'work' / 'jobs' / 'job_1.json').read_text(encoding='utf-8'))
        req = json.loads(SEEN[-1]['body']) if len(SEEN) > n0 else {}
        check(j.get('state') == 'done' and (j.get('result') or {}).get('src') == im['out'] and j['result'].get('model') == 'gemini-3-pro-image'
              and (proj / im['out']).is_file() and sum(1 for p in req['contents'][0]['parts'] if 'inline_data' in p) == 1,
              f"ジョブ係：nanobanana のジョブが done・result の src と model・参照を渡す {j.get('state')} {j.get('error', '')[-300:]}")

        # 素材の絵（api gen-image）：作品の settings.image_engine が nanobanana
        gp = td / 'genproj'; gp.mkdir()
        tlg = {'width': 1080, 'height': 1920, 'fps': 30, 'duration': 1, 'tracks': [], 'settings': {'image_engine': 'nanobanana'}}
        (gp / 'genproj.cut.json').write_text(json.dumps(tlg), encoding='utf-8')
        (gp / 'ref.png').write_bytes(tiny_png(4, 4))
        api = [sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'mittler_api.py'), str(gp), 'gen-image']
        run = lambda *x: subprocess.run(api + list(x) + ['--json'], capture_output=True, text=True, encoding='utf-8', env=env, timeout=120)
        r = run('assets/images/gen/a.png', '--prompt', 'フィルムグレイン', '--ref', 'ref.png')
        req = json.loads(SEEN[-1]['body'])
        res = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
        check(r.returncode == 0 and res.get('ok') and res.get('engine') == 'nanobanana' and (gp / 'assets/images/gen/a.png').is_file()
              and req['generationConfig']['imageConfig'] == {'aspectRatio': '9:16', 'imageSize': '2K'}
              and sum(1 for p in req['contents'][0]['parts'] if 'inline_data' in p) == 1, f'gen-image：Nano Banana で素材を作る（作品の縦横 → 9:16・2K・参照）{r.stderr[-300:]}')
        r = run('assets/images/gen/b.png', '--prompt', 'x', '--size', '1024x1024', '--quality', '1K', '--background', 'transparent', '--model', 'gemini-3.1-flash-image')
        req = json.loads(SEEN[-1]['body'])
        check(r.returncode == 0 and 'gemini-3.1-flash-image:generateContent' in SEEN[-1]['path'] and req['generationConfig']['imageConfig'] == {'aspectRatio': '1:1', 'imageSize': '1K'}
              and '単色' in req['contents'][0]['parts'][0]['text'], 'gen-image：--size → 比・--quality → 解像度・--model・透明は文で')
        r = run('assets/images/gen/c.png', '--prompt', 'x', '--quality', 'high')
        check(r.returncode == 1 and '解像度' in r.stdout + r.stderr, 'gen-image：Nano Banana に使えない --quality は断る')
        tlg['settings'] = {}; (gp / 'genproj.cut.json').write_text(json.dumps(tlg), encoding='utf-8')
        r = run('assets/images/gen/d.png', '--prompt', 'x')
        check(r.returncode == 1 and 'settings.image_engine' in r.stdout + r.stderr, 'gen-image：作品の既定も --engine も無ければ断る')
        tlg['settings'] = {'image_engine': 'codex'}; (gp / 'genproj.cut.json').write_text(json.dumps(tlg), encoding='utf-8')
        n0 = len(SEEN)
        r = run('assets/images/gen/e.png', '--prompt', '直す所だけ', '--engine', 'nanobanana', '--ref', 'ref.png')
        check(r.returncode == 0 and len(SEEN) == n0 + 1 and json.loads(r.stdout.strip().splitlines()[-1]).get('engine') == 'nanobanana',
              'gen-image：作品の既定が codex でも --engine nanobanana で直しに Nano Banana を呼べる（2026-11-19〜）')
    srv.shutdown()
    print('NG ' + str(len(FAIL)) if FAIL else 'all OK')
    return 1 if FAIL else 0


if __name__ == '__main__':
    raise SystemExit(main())
