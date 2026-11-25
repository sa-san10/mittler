"""OpenAI（GPT Image）の絵のエンジンの確かめ（本物の OpenAI には送らない。この PC の偽のサーバーで）。標準だけ。
  python tools/smoke_openai_image.py
- tools/gen/openai_image.py：参照なし＝generations（JSON）・参照あり＝edits（multipart の image[]）・PNG と記録（鍵は書かない）・鍵の間違いはやり直さない
- tools/openai_image_jobs.py：大きさ（16 の倍数・比）・モデルと品質の決まる順・参照 16 枚まで
- tools/jobs.py：engine が openai のジョブを流して、done と result.src・model
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
import openai_image_jobs as OA  # noqa: E402

FAIL = []


def check(ok, msg):
    print(('OK  ' if ok else 'NG  ') + msg)
    if not ok:
        FAIL.append(msg)


def tiny_png(w, h):
    raw = b''.join(b'\x00' + b'\x80\x40\x20' * w for _ in range(h))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


SEEN = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        SEEN.append({'path': self.path, 'auth': self.headers.get('Authorization'), 'ctype': self.headers.get('Content-Type'), 'body': body})
        if self.headers.get('Authorization') != 'Bearer test-key':
            self.send_response(401); self.end_headers()
            self.wfile.write(json.dumps({'error': {'message': 'Incorrect API key provided'}}).encode()); return
        res = {'created': 1, 'data': [{'b64_json': base64.b64encode(tiny_png(32, 18)).decode()}], 'size': '2048x1152', 'quality': 'high',
               'usage': {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30}}
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
        self.wfile.write(json.dumps(res).encode())


def main():
    srv = HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(os.environ, MITTLER_OPENAI_BASE=f'http://127.0.0.1:{srv.server_port}/v1', OPENAI_API_KEY='test-key', MITTLER_LANG='ja')
    gen = [sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'gen' / 'openai_image.py')]
    with tempfile.TemporaryDirectory(prefix='mittler_oa_') as td:
        td = Path(td)
        (td / 'p.txt').write_text('テストの絵', encoding='utf-8')
        ref = td / 'ref.png'; ref.write_bytes(tiny_png(4, 4))
        # 参照なし
        r = subprocess.run(gen + ['--prompt-file', str(td / 'p.txt'), '--out', str(td / 'a.png'), '--size', '2048x1152', '--quality', 'high'],
                           capture_output=True, text=True, encoding='utf-8', env=env, timeout=60)
        info = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {}
        req = json.loads(SEEN[-1]['body']) if SEEN else {}
        check(r.returncode == 0 and SEEN[-1]['path'] == '/v1/images/generations' and req.get('model') == 'gpt-image-2.5-sunburst'
              and req.get('size') == '2048x1152' and req.get('quality') == 'high' and req.get('prompt') == 'テストの絵',
              f'参照なし → generations に JSON（既定のモデル gpt-image-2.5-sunburst・大きさ・品質・プロンプト）{r.stderr[-300:]}')
        check((td / 'a.png').read_bytes()[:8] == b'\x89PNG\r\n\x1a\n' and info.get('width') == 32 and info.get('height') == 18, 'PNG を書いて、幅・高さを出す')
        side = (td / 'a.png.openai.json').read_text(encoding='utf-8') if (td / 'a.png.openai.json').is_file() else ''
        check(side and 'test-key' not in side and json.loads(side).get('usage', {}).get('total_tokens') == 30, '記録（.openai.json）に使った量があり、鍵は書かない')
        # 参照あり
        r = subprocess.run(gen + ['--prompt-file', str(td / 'p.txt'), '--out', str(td / 'b.png'), '--ref', str(ref), '--ref', str(ref), '--model', 'gpt-image-2.5-flare'],
                           capture_output=True, text=True, encoding='utf-8', env=env, timeout=60)
        b = SEEN[-1]['body']
        check(r.returncode == 0 and SEEN[-1]['path'] == '/v1/images/edits' and SEEN[-1]['ctype'].startswith('multipart/form-data')
              and b.count(b'name="image[]"') == 2 and b'gpt-image-2.5-flare' in b, '参照あり → edits に multipart（image[] が 2 つ・選んだモデル）')
        # 鍵の間違い：やり直さずに止まる
        n0 = len(SEEN)
        r = subprocess.run(gen + ['--prompt-file', str(td / 'p.txt'), '--out', str(td / 'c.png')], capture_output=True, text=True, encoding='utf-8',
                           env=dict(env, OPENAI_API_KEY='wrong'), timeout=60)
        check(r.returncode == 1 and len(SEEN) - n0 == 1 and 'HTTP 401' in r.stderr and 'wrong' not in r.stderr and not (td / 'c.png').exists(),
              '鍵の間違い（401）：1 回で止まり、理由を出し、鍵は出さない')

        # アダプタ：大きさ・モデルと品質の決まる順・参照の上限
        sizes = {(1920, 1080): OA.pick_size(1920, 1080), (1080, 1920): OA.pick_size(1080, 1920), (1080, 1080): OA.pick_size(1080, 1080), (640, 360): OA.pick_size(640, 360)}
        def good(s, W, H):
            w, h = map(int, s.split('x'))
            return w % 16 == 0 and h % 16 == 0 and abs(w / h - W / H) / (W / H) < 0.02 and OA.MIN_PX <= w * h <= OA.MAX_PX
        check(all(good(s, *k) for k, s in sizes.items()) and sizes[(1920, 1080)] == '2048x1152', f'大きさ：16 の倍数・同じ比・画素の範囲 {sizes}')
        q = {'engine': 'openai', 'prompt': 'x', 'refs': [], 'width': 1920, 'height': 1080, 'root': str(td), 'project_dir': str(td)}
        b1 = OA.build(dict(q))
        b2 = OA.build(dict(q, default_model='gpt-image-2', default_quality='medium'))
        b3 = OA.build(dict(q, model='gpt-image-2.5-flare', quality='xhigh', default_model='gpt-image-2', default_quality='medium'))
        check((b1['image']['model'], b1['image']['quality']) == ('gpt-image-2.5-sunburst', 'high') and (b2['image']['model'], b2['image']['quality']) == ('gpt-image-2', 'medium')
              and (b3['image']['model'], b3['image']['quality']) == ('gpt-image-2.5-flare', 'xhigh'), 'モデル・品質：絵の欄 → PC の設定 → 既定（sunburst・high）')
        try:
            OA.build(dict(q, refs=['r.png'] * 17)); ok = False
        except OA.Refuse:
            ok = True
        check(ok and OA.build(dict(q, refs=['r.png'] * 16))['ok'], '参照は 16 枚まで（17 枚は断る）')

        # ジョブ係：engine が openai のジョブ
        proj = td / 'proj'; (proj / 'work' / 'jobs').mkdir(parents=True)
        im = OA.build(dict(q, root=str(proj), project_dir=str(proj)))['image']
        im['out'] = 'assets/frames/p1_start_t1.png'
        (proj / 'work' / 'jobs' / 'job_1.json').write_text(json.dumps({'id': 'job_1', 'kind': 'image', 'clip': 'p1', 'which': 'start_frame', 'state': 'queued', 'image': im}), encoding='utf-8')
        r = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'jobs.py'), str(proj), '--once'], capture_output=True, text=True, encoding='utf-8', env=env, timeout=120)
        j = json.loads((proj / 'work' / 'jobs' / 'job_1.json').read_text(encoding='utf-8'))
        check(j.get('state') == 'done' and (j.get('result') or {}).get('src') == im['out'] and (j['result'].get('model') == 'gpt-image-2.5-sunburst')
              and (proj / im['out']).is_file(), f"ジョブ係：openai のジョブが done・result の src と model {j.get('state')} {j.get('error', '')[-300:]}")
        # 素材の絵（api gen-image）：作品の settings.image_engine だけ・編集画面なしで・上書きしない
        gp = td / 'genproj'; gp.mkdir()
        tlg = {'width': 1920, 'height': 1080, 'fps': 30, 'duration': 1, 'tracks': [], 'settings': {}}
        (gp / 'genproj.cut.json').write_text(json.dumps(tlg), encoding='utf-8')
        api = [sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'mittler_api.py'), str(gp), 'gen-image']
        run = lambda *x: subprocess.run(api + list(x) + ['--json'], capture_output=True, text=True, encoding='utf-8', env=env, timeout=120)
        r = run('assets/images/gen/grain.png', '--prompt', 'フィルムグレイン')
        check(r.returncode == 1 and 'settings.image_engine' in r.stdout + r.stderr, 'gen-image：作品のエンジンが決まっていなければ断る')
        tlg['settings']['image_engine'] = 'openai'; (gp / 'genproj.cut.json').write_text(json.dumps(tlg), encoding='utf-8')
        r = run('assets/images/gen/grain.png', '--prompt', 'フィルムグレイン', '--size', '1024x1024', '--background', 'transparent', '--ref', 'ref.png')
        check(r.returncode == 1 and '参照画像が無い' in r.stdout + r.stderr, 'gen-image：無い参照画像は断る')
        (gp / 'ref.png').write_bytes(tiny_png(4, 4))
        r = run('assets/images/gen/grain.png', '--prompt', 'フィルムグレイン', '--size', '1024x1024', '--background', 'transparent', '--ref', 'ref.png')
        b = SEEN[-1]['body']
        res = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
        check(r.returncode == 0 and res.get('ok') and (gp / 'assets/images/gen/grain.png').is_file() and SEEN[-1]['path'] == '/v1/images/edits'
              and b'1024x1024' in b and b'transparent' in b, f'gen-image：OpenAI で素材を作る（大きさ・透明・参照）{r.stderr[-300:]}')
        r = run('assets/images/gen/grain.png', '--prompt', 'x')
        check(r.returncode == 1 and '上書きしない' in r.stdout + r.stderr, 'gen-image：同じ名前は上書きしない')
        r = run('../outside.png', '--prompt', 'x')
        check(r.returncode == 1 and not (td / 'outside.png').exists(), 'gen-image：作品の外には書かない')
        # 同時に 4 本頼んでも、プロンプトを取り違えない（2026-11-15 mittler-mv の報告：一時ファイルの名前がミリ秒だけで上書きしあった）
        procs = [subprocess.Popen(api + [f'assets/images/gen/par_{i}.png', '--prompt', f'並べて頼んだ {i} 番'] + ['--json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
                 for i in range(4)]
        for p_ in procs:
            p_.communicate(timeout=120)
        got = {i: json.loads((gp / f'assets/images/gen/par_{i}.png.openai.json').read_text(encoding='utf-8')).get('prompt', '') if (gp / f'assets/images/gen/par_{i}.png.openai.json').is_file() else '' for i in range(4)}
        check(all(got[i].startswith(f'並べて頼んだ {i} 番') for i in range(4)), f'gen-image：同時に 4 本でもプロンプトを取り違えない {[(i, got[i][:10]) for i in range(4)]}')
        tlg['settings']['image_engine'] = 'codex'; (gp / 'genproj.cut.json').write_text(json.dumps(tlg), encoding='utf-8')
        r = run('assets/images/gen/b.png', '--prompt', 'x', '--engine', 'openai')
        check(r.returncode == 0 and json.loads(r.stdout.strip().splitlines()[-1]).get('engine') == 'openai' and SEEN[-1]['path'] == '/v1/images/generations',
              'gen-image：作品の既定が codex でも --engine openai で OpenAI を呼べる（2026-11-19〜。何でも呼べる）')
        r = run('assets/images/gen/c.png', '--prompt', 'x', '--engine', 'openai', '--model', 'gpt-image-2')
        check(r.returncode == 0 and json.loads(SEEN[-1]['body']).get('model') == 'gpt-image-2', 'gen-image：--engine と --model')
    srv.shutdown()
    print('NG ' + str(len(FAIL)) if FAIL else 'all OK')
    return 1 if FAIL else 0


if __name__ == '__main__':
    raise SystemExit(main())
