"""人の操作を API から（2026-11-15）の確かめ。ヘッドレスのブラウザ、localhost だけ。
  <Playwright の python> -X utf8 tools/smoke_api.py --render-python <描画の python> [--work <フォルダ>] [--only 名前,名前]
試しの作品（320×180・30fps・12 秒。音つきの動画・絵・セリフ・動画化予定・カット・拍）を自分で作り、サーバーを自分で立てて、終わったら /api/quit で止める。
セリフの声は偽の VOICEVOX（このスクリプトの中の小さなサーバー。文の長さで決まる無音の WAV）。本物の Codex・Gemini・H3・Suno は動かさない。
確かめること：
  (a) 同じ結果   ボタンで押した結果と、tools/mittler_api.py で頼んだ結果が、同じタイムラインからの同じ書きかえ（新しい id とテイクの作った時刻だけを読みかえて比べる）：
                セリフから字幕・セリフのテイクを選ぶ・セリフの声の生成・絵のテイク・動画のテイク・採用・最新を全部採用・動画の音を置く・動画を置く・音ハメ（自動）・
                カットを分ける／ラベル／つなぐ／境目／映像を合わせる／範囲をカットに／採用のときカットも
  (b) API だけ   tts-all --wait・export --wait（下書き）・still・proxy（プレビューに使う・画面の動画も読み直す）・master の画質が窓の初めの値と同じ・export-cancel・
                effects・effect-add・presets・blender-clear・frame-cache・stems-place・new-project・status・知らない操作は理由
  (c) 見える操作 ui の再生・止める・飛ぶ・1 コマ送り・選ぶ（state.json にも）・タブ・拡大・全体・見える位置・言葉・書き出しの窓・マスターの窓・取り消し・オート。
                編集画面が開いていなければ理由を返して止まる。見える操作は取り消しの記録を増やさない
  (d) オート     外でクリップを足す・動かす・長さを変える → 再生位置がその真ん中・見える所・光る印。オフなら動かない。再生中は動かない（印だけ）。取り消しの記録は外の直しの 1 つだけ
"""
import http.server
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
fails = []


def opt(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


RPY = opt('--render-python')
if not RPY:
    sys.exit('使い方: smoke_api.py --render-python <描画の python> [--work <フォルダ>]')
ONLY = set(filter(None, (opt('--only', '') or '').split(',')))


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close()
    return p


def node_cmd():
    n = shutil.which('node')
    return [n] if n else ['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node']


# ---------- 偽の VOICEVOX（/speakers・/audio_query・/synthesis）：文の長さ × 0.12 秒の無音（24 kHz）。同じ文は同じ長さ ----------
class FakeVV(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype):
        self.send_response(200); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        self._send(json.dumps([{'name': '偽', 'styles': [{'id': 1, 'name': 'ノーマル'}]}]).encode(), 'application/json')

    def do_POST(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else b''
        if u.path == '/audio_query':
            text = parse_qs(u.query).get('text', [''])[0]
            self._send(json.dumps({'text': text, 'speedScale': 1}).encode(), 'application/json'); return
        q = json.loads(body or b'{}')
        sec = max(0.3, 0.12 * len(q.get('text', '')))
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b'\0\0' * int(24000 * sec))
        self._send(buf.getvalue(), 'audio/wav')


def make_project(d):
    r = subprocess.run(node_cmd() + [str(ROOT / 'tools' / 'new_project.js'), str(d), '--no-git', '--json', '--lang', 'ja'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    if r.returncode:
        raise SystemExit('new_project 失敗: ' + r.stdout + r.stderr)
    ff = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
    (d / 'assets' / 'videos' / 'gen').mkdir(parents=True, exist_ok=True)
    (d / 'assets' / 'frames').mkdir(parents=True, exist_ok=True)
    (d / 'assets' / 'voice').mkdir(parents=True, exist_ok=True)
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=6', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6:sample_rate=48000',
                         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(d / 'assets' / 'videos' / 'withsound.mp4')], check=True)
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(d / 'assets' / 'videos' / 'gen' / 'plan_1_t1.mp4')], check=True)
    shutil.copy(d / 'assets' / 'videos' / 'gen' / 'plan_1_t1.mp4', d / 'assets' / 'videos' / 'gen' / 'plan_1_t2.mp4')
    for n, c in (('a', '0xDC1E1E'), ('b', '0x1E6EDC')):
        subprocess.run(ff + ['-f', 'lavfi', '-i', f'color=c={c}:s=320x180', '-frames:v', '1', str(d / 'assets' / 'frames' / f'plan_1_start_t{1 if n == "a" else 2}.png')], check=True)
    for k in (1, 2):
        with wave.open(str(d / 'assets' / 'voice' / f'tts_3_t{k}.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b'\0\0' * 24000 * k)
    (d / 'characters.json').write_text(json.dumps({'characters': [{'id': 'hana', 'name': 'ハナ', 'color': '#e07070', 'image': '',
                                                                    'tts': {'default_engine': 'voicevox', 'voicevox': {'speaker': 1}}}]}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    tlf = d / f'{d.name}.cut.json'
    tl = json.loads(tlf.read_text(encoding='utf-8'))
    tl.update(width=320, height=180, fps=30, duration=12)
    tr = {t['kind'] if t['kind'] != 'audio' else t['id']: t for t in tl['tracks']}
    tr['video']['clips'] = [{'id': 'v_1', 'type': 'video', 'src': ['assets/videos/withsound.mp4'], 'start': 0, 'dur': 4, 'in': 0, 'speed': 1, 'label': 'v1', 'cut': '1'},
                            {'id': 'v_2', 'type': 'video', 'src': ['assets/videos/withsound.mp4'], 'start': 4, 'dur': 3, 'in': 1, 'speed': 1, 'label': 'v2', 'cut': '2'}]
    tr['plan']['clips'] = [{'id': 'plan_1', 'type': 'plan', 'start': 8, 'dur': 2, 'label': 'P1',
                            'start_frame': {'src': 'assets/frames/plan_1_start_t1.png', 'prompt': '', 'activeTake': 't1',
                                            'takes': [{'id': 't1', 'src': 'assets/frames/plan_1_start_t1.png', 'engine': 'codex'}, {'id': 't2', 'src': 'assets/frames/plan_1_start_t2.png', 'engine': 'codex'}]},
                            'end_frame': {'src': None, 'prompt': '', 'takes': [], 'activeTake': None},
                            'video': {'prompt': 'x', 'engine': 'h3-fl2va', 'activeTake': 't1', 'takes': [
                                {'id': 't1', 'src': 'assets/videos/gen/plan_1_t1.mp4', 'dur': 2, 'engine': 'h3-fl2va', 'created': '2026-11-15T00:00:00.000Z'},
                                {'id': 't2', 'src': 'assets/videos/gen/plan_1_t2.mp4', 'dur': 2, 'engine': 'h3-fl2va', 'created': '2026-11-15T01:00:00.000Z'}]}}]
    tl['tracks'].insert(2, {'id': 't_video_1', 'name': '映像 2', 'kind': 'video', 'clips': [
        {'id': 'v_3', 'type': 'video', 'src': ['assets/videos/withsound.mp4'], 'start': 0, 'dur': 1, 'in': 0, 'speed': 1, 'label': 'v3'}]})
    tl['tracks'].insert(4, {'id': 't_tts_0', 'name': 'ハナ', 'kind': 'tts', 'character': 'hana', 'clips': [
        {'id': 'tts_1', 'type': 'tts', 'start': 1, 'dur': 1, 'character': 'hana', 'engine': 'voicevox', 'text': 'こんにちは', 'gemini': {}, 'voicevox': {}, 'takes': [], 'gain': 0, 'in': 0, 'fade_in': 0, 'fade_out': 0},
        {'id': 'tts_2', 'type': 'tts', 'start': 3, 'dur': 1, 'character': 'hana', 'engine': 'voicevox', 'text': '<happy>元気です。', 'gemini': {}, 'voicevox': {}, 'takes': [], 'gain': 0, 'in': 0, 'fade_in': 0, 'fade_out': 0},
        {'id': 'tts_3', 'type': 'tts', 'start': 5.5, 'dur': 1, 'character': 'hana', 'engine': 'voicevox', 'text': 'テイクあり', 'gemini': {}, 'voicevox': {}, 'activeTake': 't1', 'gain': 0, 'in': 0, 'fade_in': 0, 'fade_out': 0,
         'takes': [{'id': 't1', 'src': 'assets/voice/tts_3_t1.wav', 'dur': 1, 'engine': 'voicevox', 'text': 'テイクあり'}, {'id': 't2', 'src': 'assets/voice/tts_3_t2.wav', 'dur': 2, 'engine': 'voicevox', 'text': 'テイクあり'}]}]})
    cuts = next(m for m in tl['meta'] if m['kind'] == 'cuts')
    cuts['items'] = [{'label': '1', 'start': 0, 'end': 4}, {'label': '2', 'start': 4, 'end': 8}, {'label': '3', 'start': 8, 'end': 12}]
    tl['meta'].append({'id': 'm_beats', 'kind': 'beats', 'name': 'ビート', 'items': [[round(i * 0.5, 4), i % 4 == 0] for i in range(25)]})
    tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    return tlf


class Server:
    def __init__(self, tlf, logf, vv):
        env = dict(os.environ); env['MITTLER_NO_REVEAL'] = '1'
        self.log = open(logf, 'w', encoding='utf-8', errors='replace')
        self.p = subprocess.Popen(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'serve', str(tlf), '--port', str(free_port()), '--render-python', RPY, '--lang', 'ja',
                                   '--voicevox-url', vv, '--tools-python', sys.executable],
                                  stdout=subprocess.PIPE, stderr=self.log, env=env, text=True, encoding='utf-8', errors='replace')
        self.url = self.p.stdout.readline().strip()
        if not self.url.startswith('http://127.0.0.1:'):
            raise SystemExit('サーバーが起動しない: ' + self.url)
        self.token = re.search(r'token=(\w+)', self.url).group(1)
        self.base = self.url.split('/editor/')[0]
        self.url = self.url.replace('?token=', '?lang=ja&token=')

    def quit(self):
        try:
            urllib.request.urlopen(urllib.request.Request(self.base + '/api/quit', data=b'{}', method='POST', headers={'X-Mittler-Token': self.token}), timeout=10).read()
        except Exception as e:
            print('quit 失敗', e)
        try:
            self.p.wait(timeout=45)
        except subprocess.TimeoutExpired:
            print('サーバーが止まらない pid', self.p.pid)
        self.log.close()


def api(proj, *args, timeout=900):
    r = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'mittler_api.py'), str(proj), *map(str, args), '--json'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    line = (r.stdout.strip().splitlines() or [''])[-1]
    try:
        j = json.loads(line)
    except ValueError:
        j = {'ok': False, 'raw': (r.stdout + r.stderr)[-600:]}
    j['_code'] = r.returncode
    return j


# 比べるとき：新しく出てきた id（頭_英数字 6 字）を出てきた順の印に・テイクの作った時刻を外す
ID_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*_[0-9a-z]{6}$')


def canon(tl, base_ids):
    seen = {}

    def walk(o, key=''):
        if isinstance(o, dict):
            return {k: walk(v, k) for k, v in o.items() if k != 'created'}
        if isinstance(o, list):
            return [walk(v, key) for v in o]
        if isinstance(o, str) and ID_RE.match(o) and o not in base_ids:
            seen.setdefault(o, f'<id{len(seen)}>')
            return seen[o]
        return o
    return json.dumps(walk(tl), ensure_ascii=False, sort_keys=False)


def all_strings(o, out):
    if isinstance(o, dict):
        for v in o.values():
            all_strings(v, out)
    elif isinstance(o, list):
        for v in o:
            all_strings(v, out)
    elif isinstance(o, str):
        out.add(o)
    return out


READY = '() => window.MITTLER_EDITOR && MITTLER_EDITOR.tl && MITTLER_EDITOR.fxReady && window.MITTLER_REMOTE && document.querySelector("#cutbar button")'
SAVED = '() => { const S = MITTLER_EDITOR; return !S.saveTimer && !S.saving && S.lastSaved === JSON.stringify(S.tl); }'


def main(work):
    work.mkdir(parents=True, exist_ok=True)
    proj = work / 'p_api'
    if proj.exists():
        shutil.rmtree(proj)
    tlf = make_project(proj)
    T0 = tlf.read_text(encoding='utf-8')
    base_ids = all_strings(json.loads(T0), set())
    vvport = free_port()
    vv = http.server.ThreadingHTTPServer(('127.0.0.1', vvport), FakeVV)
    threading.Thread(target=vv.serve_forever, daemon=True).start()
    srv = Server(tlf, work / 'server.log', f'http://127.0.0.1:{vvport}')
    try:
        # (c) 開いていない：理由を返して止まる
        r = api(proj, 'ui', 'play')
        check(r.get('ok') is False and '編集画面' in str(r.get('error')), f"(c) 編集画面が開いていない：ui は理由を返して止まる（{r.get('error')}）")
        with sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={'width': 1500, 'height': 900})
            errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))

            def reset():
                tlf.write_text(T0, encoding='utf-8', newline='\n')
                time.sleep(0.3)
                pg.goto(srv.url); pg.wait_for_function(READY, timeout=120000)
                pg.evaluate('() => { MITTLER_ASSETS.setOpen(true); MITTLER_FOLLOW.set(false); }')
                time.sleep(0.3)

            def file_tl():
                return json.loads(tlf.read_text(encoding='utf-8'))

            def wait_edit(e0, timeout=120):
                pg.wait_for_function(f'() => MITTLER_EDITOR.edits > {e0}', timeout=timeout * 1000)
                pg.wait_for_function(SAVED, timeout=60000); time.sleep(0.5)

            def same(name, button, api_args, timeout=120, fix=None):
                if ONLY and name not in ONLY:
                    return
                try:
                    reset()
                    e0 = pg.evaluate('MITTLER_EDITOR.edits')
                    button()
                    wait_edit(e0, timeout)
                    a = file_tl()
                    reset()
                    r = api(proj, *api_args)
                    time.sleep(0.4)
                    b = file_tl()
                    f = fix or (lambda s: s)
                    ok = r.get('ok') and f(canon(a, base_ids)) == f(canon(b, base_ids))
                    if not ok:
                        (work / f'diff_{name}_button.json').write_text(canon(a, base_ids), encoding='utf-8')
                        (work / f'diff_{name}_api.json').write_text(canon(b, base_ids), encoding='utf-8')
                    check(ok, f"(a) {name}：ボタンと API で同じタイムライン" + ('' if ok else f"（API {r.get('error') or r.get('message') or r.get('raw')}・違いは {work}\\diff_{name}_*.json）"))
                except Exception as e:
                    check(False, f'(a) {name}：{type(e).__name__} {str(e)[:300]}')

            ev = pg.evaluate
            sel = lambda cid: ev(f"() => {{ MITTLER_EDITOR.select('{cid}'); MITTLER_EDITOR.showPane('sel'); }}")

            def meta_cuts():
                ev("() => { MITTLER_EDITOR.showPane('meta'); MITTLER_EDITOR.metaTab = 'm_cuts'; buildMetaPanel(); }")

            def set_input(selector, value):
                pg.fill(selector, str(value)); ev(f"() => document.querySelector({json.dumps(selector)}).dispatchEvent(new Event('change', {{bubbles: true}}))")

            reset()
            # ---- (a) ボタンと API ----
            same('subs-from-lines', lambda: (pg.click('#assetTabs [data-tab=lines]'), pg.click('.ttsAllBtn[data-mode=subs]')), ['subs-from-lines'])
            same('tts-take', lambda: (sel('tts_3'), pg.wait_for_selector('#sel .take[data-take=t2] input'), pg.click('#sel .take[data-take=t2] input')), ['tts-take', 'tts_3', 't2'])
            # セリフの声：ボタンで作った tts_1_t1.wav が残っているので、API のほうは次の名前（t2）になる。テイクの名前だけ読みかえる
            same('tts', lambda: (sel('tts_1'), pg.wait_for_selector('#ttsGen'), pg.click('#ttsGen')), ['tts', 'tts_1'],
                 fix=lambda s: re.sub(r'tts_1_t\d', 'tts_1_tN', re.sub(r'"(id|activeTake)": "t[12]"', r'"\1": "tN"', s)))
            same('frame-take', lambda: (sel('plan_1'), pg.click('.planSec[data-which=start_frame] .ptake[data-take=t2]')), ['frame-take', 'plan_1', 'start_frame', 't2'])
            same('video-take', lambda: (sel('plan_1'), pg.click('.vtake[data-take=t2] span')), ['video-take', 'plan_1', 't2'])
            same('adopt', lambda: (sel('plan_1'), pg.click('.vtake[data-take=t1] .adopt')), ['adopt', 'plan_1', 't1'])
            same('adopt-all', lambda: pg.click('#cutbar [data-act=latest]'), ['adopt-all', '--latest'])
            same('cuts-on-adopt', lambda: (sel('plan_1'), pg.click('[data-cutadopt]')), ['cuts-on-adopt', 'on'])
            same('cut-from-clip', lambda: (sel('plan_1'), pg.click('[data-cutfrom]')), ['cut-from-clip', 'plan_1'])
            same('video-audio', lambda: (sel('v_1'), pg.click('#cutbar [data-act=vaudio]')), ['video-audio', 'v_1'])
            same('place-video', lambda: (pg.click('#assetTabs [data-tab=videos]'), pg.click('#assetBody .arow[data-path="assets/videos/withsound.mp4"]'), pg.click('#apVid')),
                 ['place-video', 'assets/videos/withsound.mp4', '--at', '0'])
            same('cut-split', lambda: (ev('() => MITTLER_EDITOR.seek(2)'), meta_cuts(), pg.click('#mSplit')), ['cut-split', '2'])
            same('cut-rename', lambda: (meta_cuts(), set_input('#metaBody .mrow[data-i="0"] .mlabel', 'A1')), ['cut-rename', '1', 'A1'])
            same('cut-join', lambda: (meta_cuts(), pg.click('#metaBody .mrow[data-i="1"] .mjp')), ['cut-join', '2', 'prev'])
            same('cut-edge', lambda: (meta_cuts(), set_input('#metaBody .mrow[data-i="0"] .me', 3.5)), ['cut-edge', '1', 'end', '3.5'])
            same('cut-align', lambda: (meta_cuts(), pg.click('#mAlignAll')), ['cut-align'])
            # 分ける：カットに付いた映像（v_1・v_2）は動かせない決まりなので、カットに付いていない v_3 で
            same('split', lambda: (ev('() => MITTLER_EDITOR.seek(0.5)'), sel('v_3'), pg.click('#cutbar [data-act=split]')), ['split', '0.5', 'v_3'])
            same('delete', lambda: (sel('tts_1'), pg.click('#cutbar [data-act=del]')), ['delete', 'tts_1'])
            same('ripple', lambda: (sel('tts_1'), pg.click('#cutbar [data-act=ripple]')), ['ripple', 'tts_1'])
            same('gaps', lambda: (sel('tts_2'), pg.click('#cutbar [data-act=gaps]')), ['gaps', 'tts_2'])
            same('stretch', lambda: (sel('v_3'), pg.select_option('#sel .stretch [data-x=to]', 'sec'), pg.fill('#sel .stretch [data-x=sec]', '3'), pg.click('#sel .stretch [data-x=hold]')),
                 ['stretch', 'v_3', '--len', '3', '--how', 'hold'])
            same('onbeat', lambda:(sel('v_1'), pg.click('#sel [data-act=auto]')), ['onbeat', 'v_1'], timeout=600)

            # ---- (b) API だけ ----
            reset()
            if not ONLY or 'b' in ONLY:
                r = api(proj, 'tts-all', '--wait', timeout=600)
                tl = file_tl(); tts = {c['id']: c for t in tl['tracks'] for c in t['clips'] if c['type'] == 'tts'}
                check(r.get('ok') and all(tts[i].get('takes') for i in ('tts_1', 'tts_2')) and len(tts['tts_3']['takes']) == 2,
                      f"(b) tts-all --wait：未生成のセリフ 2 本にテイク、テイクのあるものはそのまま（{r.get('message')}）")
                r = api(proj, 'tts-status')
                check(r.get('running') is False and r.get('done') == 2, f"(b) tts-status（{r.get('message')}）")
                r = api(proj, 'export', '--to', '1', '--step', '2', '--wait', timeout=900)
                outp = (r.get('result') or {}).get('path')
                check(r.get('ok') and outp and (proj / outp).exists() and '_draft' in outp, f"(b) export --to 1 --step 2 --wait：下書きの MP4（{outp}）")
                r = api(proj, 'export-status')
                check(r.get('state') == 'done', f"(b) export-status（{r.get('state')}）")
                r = api(proj, 'still', '--at', '1')
                check(r.get('ok') and (proj / r.get('path', '_')).exists(), f"(b) still --at 1（{r.get('path')}）")
                if outp:
                    r = api(proj, 'proxy', outp, timeout=900)
                    tl = file_tl()
                    check(r.get('ok') and (tl.get('preview') or {}).get('proxy') == r.get('proxy'), f"(b) proxy：WebM を作って preview.proxy に（{r.get('proxy')}）")
                    try:
                        pg.wait_for_function(f"() => (document.getElementById('proxy').getAttribute('src') || '').includes({json.dumps(Path(r.get('proxy') or 'x').name)})", timeout=15000)
                        check(True, '(b) proxy：開いている画面の再生用の動画も読み直した')
                    except Exception:
                        check(False, '(b) proxy：開いている画面の再生用の動画も読み直した')
                mi = api(proj, 'master-info')
                ev('() => MITTLER_EXPORT.open(true)')
                pg.wait_for_selector('input[name=xUp]:checked')
                win_up = ev("() => document.querySelector('input[name=xUp]:checked').value")
                ev('() => MITTLER_EXPORT.close()')
                r = api(proj, 'master', '--to', '0.2')
                api(proj, 'export-cancel'); api(proj, 'export-status', '--wait', timeout=600)
                check(r.get('ok') and r.get('upscale') == win_up, f"(b) master：画質を言わなければ窓の初めの値（窓 {win_up}・API {r.get('upscale')}）")
                fx = api(proj, 'effects')
                lib = sorted((fx.get('library') or {}).keys())
                check(fx.get('ok') and 'subtitle' in (fx.get('project') or {}) and lib, f"(b) effects：作品のエフェクトと部品の置き場（置き場 {len(lib)} 本）")
                name = next((n for n in lib if n.startswith('fm_')), lib[0] if lib else '')
                r = api(proj, 'effect-add', name)
                check(r.get('ok') and (proj / 'effects' / f'{name}.py').exists(), f"(b) effect-add {name}")
                r = api(proj, 'effect-add', name)
                check(r.get('ok') is False and r.get('error'), f"(b) effect-add もう一度：理由（{r.get('error')}）")
                r = api(proj, 'presets')
                check('characters' in r, f"(b) presets：一覧か理由（{r.get('error') or len(r.get('characters') or [])}）")
                r = api(proj, 'blender-clear', 'v_1')
                check(r.get('ok') and r.get('files') == 0, '(b) blender-clear（ためた絵が無い：0 ファイル）')
                r = api(proj, 'frame-cache')
                n = r.get('frames')
                r2 = api(proj, 'frame-cache', 'clear')
                r3 = api(proj, 'frame-cache')
                check(r.get('ok') and isinstance(n, int) and r2.get('ok') and r2.get('frames') == n and r3.get('frames') == 0 and not list((proj / 'work' / 'cache' / 'frames').glob('*/*.jpg')),
                      f'(b) frame-cache（プレビューでためたコマ {n} 枚 → clear で 0）')
                # ステムを置く（Suno の audio-stems の WAV の代わりに、セリフの WAV を写したもの）：音のクリップを 1 本足してから
                st = proj / 'assets' / 'music' / 'mus_1_t1_stems'
                st.mkdir(parents=True, exist_ok=True)
                for nm in ('vocals', 'drums'):
                    shutil.copy(proj / 'assets' / 'voice' / 'tts_3_t2.wav', st / f'{nm}.wav')
                tl_ = file_tl()
                mtr = next(t for t in tl_['tracks'] if t['kind'] == 'audio')
                mtr['clips'].append({'id': 'mus_1', 'type': 'audio', 'src': 'assets/voice/tts_3_t2.wav', 'start': 2, 'dur': 2, 'in': 0.5, 'gain': -3, 'fade_in': 0, 'fade_out': 0, 'label': 'BGM'})
                tlf.write_text(json.dumps(tl_, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
                time.sleep(0.5)
                n0 = len(tl_['tracks'])
                r = api(proj, 'stems-place', 'mus_1', 'assets/music/mus_1_t1_stems/vocals.wav', 'assets/music/mus_1_t1_stems/drums.wav')
                time.sleep(0.4)
                tl_ = file_tl()
                new = [t for t in tl_['tracks'] if t.get('from_stems') == 'mus_1']
                ok = (r.get('ok') and len(tl_['tracks']) == n0 + 2 and len(new) == 2 and all(t['muted'] and t['kind'] == 'audio' for t in new) and
                      [t['clips'][0]['src'].split('/')[-1] for t in new] == ['vocals.wav', 'drums.wav'] and
                      all((c['start'], c['dur'], c['in'], c['gain']) == (2, 2, 0.5, -3) for t in new for c in t['clips']) and 'vocals' in new[0]['name'])
                check(ok, f"(b) stems-place：パートごとにミュートした音のトラック（もとのクリップと同じ時刻・長さ・in・音量）（{r.get('message') or r.get('error')}）")
                r = api(proj, 'stems-place', 'mus_1', 'assets/music/nothing.wav')
                check(r.get('ok') is False and 'nothing.wav' in str(r.get('error')), f"(b) stems-place 無いファイル：理由（{r.get('error')}）")
                r = api(proj, 'new-project', str(work), 'p_new_api', '--title', 'API で作った', '--no-git', '--no-open')
                check(r.get('ok') and (work / 'p_new_api' / 'p_new_api.cut.json').exists(), f"(b) new-project（{r.get('timeline') or r.get('error')}）")
                r = api(proj, 'cut-join', 'zzz', 'prev')
                check(r.get('ok') is False and 'zzz' in str(r.get('error')), f"(b) 無いカット：理由（{r.get('error')}）")
                r = api(proj, 'plan-resolve', 'plan_1', 'video')
                check('prompt' in r and 'imports' in r, f"(b) plan-resolve：送るものと参照（{str(r.get('prompt'))[:30]}）")
                r = api(proj, 'job-cancel', 'job_nothing')
                check(r.get('ok') is False, f"(b) job-cancel 無いジョブ：理由（{r.get('error')}）")
                r = api(proj, 'tts-take', 'tts_1', 't99')
                check(r.get('ok') is False and r.get('error'), f"(b) 無いテイク：理由（{r.get('error')}）")

            # ---- (c) 見える操作 ----
            reset()
            if not ONLY or 'c' in ONLY:
                u0 = ev('MITTLER_EDITOR.undo.length')
                r = api(proj, 'ui', 'seek', '2.5')
                check(r.get('ok') and abs(ev('MITTLER_EDITOR.t') - 2.5) < 1e-6, f"(c) ui seek 2.5（{(r.get('state') or {}).get('t')}）")
                r = api(proj, 'ui', 'step', '3')
                check(r.get('ok') and abs(ev('MITTLER_EDITOR.t') - (2.5 + 3 / 30)) < 1e-6, '(c) ui step 3（3 コマ送り）')
                r = api(proj, 'ui', 'select', 'v_2', '--seek')
                time.sleep(1.2)
                st = json.loads((proj / '.mittler' / 'state.json').read_text(encoding='utf-8'))
                check(r.get('ok') and ev('MITTLER_EDITOR.sel') == 'v_2' and (st.get('selection') or {}).get('id') == 'v_2' and abs(ev('MITTLER_EDITOR.t') - 5.5) < 1e-6,
                      '(c) ui select v_2 --seek：選んで真ん中へ・state.json にも')
                r = api(proj, 'ui', 'pane', 'meta')
                check(r.get('ok') and ev('MITTLER_EDITOR.pane') == 'meta', '(c) ui pane meta')
                r = api(proj, 'ui', 'zoom', '120')
                check(r.get('ok') and abs(ev('MITTLER_EDITOR.pps') - 120) < 1e-6, f"(c) ui zoom 120（{ev('MITTLER_EDITOR.pps')}）")
                r = api(proj, 'ui', 'scroll', '8')
                check(r.get('ok') and (r['state']['view']['from'] <= 8 <= r['state']['view']['to']), f"(c) ui scroll 8（見える {r.get('state', {}).get('view')}）")
                r = api(proj, 'ui', 'fit')
                check(r.get('ok') and abs(ev('MITTLER_EDITOR.pps') - ev('MITTLER_EDITOR.fitPps()')) < 1e-6, '(c) ui fit')
                r = api(proj, 'ui', 'lang', 'en')
                check(r.get('ok') and ev('MITTLER_I18N.lang') == 'en' and ev("document.getElementById('followBtn').textContent.trim()") == 'Auto', '(c) ui lang en（画面が英語に）')
                api(proj, 'ui', 'lang', 'ja')
                check(ev('MITTLER_I18N.lang') == 'ja', '(c) ui lang ja（戻す）')
                r = api(proj, 'ui', 'open-master')
                check(r.get('ok') and pg.is_visible('#exportPanel') and r['state']['export_open'], '(c) ui open-master：マスターの窓')
                api(proj, 'ui', 'close-export')
                r = api(proj, 'ui', 'open-export')
                check(r.get('ok') and pg.is_visible('#exportPanel #xName'), '(c) ui open-export：書き出しの窓')
                api(proj, 'ui', 'close-export')
                check(not pg.is_visible('#exportPanel'), '(c) ui close-export')
                r = api(proj, 'ui', 'play')
                check(r.get('ok') and ev('MITTLER_EDITOR.playing'), '(c) ui play')
                r = api(proj, 'ui', 'pause')
                check(r.get('ok') and not ev('MITTLER_EDITOR.playing'), '(c) ui pause')
                check(ev('MITTLER_EDITOR.undo.length') == u0, '(c) 見える操作は取り消しの記録を増やさない')
                api(proj, 'subs-from-lines'); pg.wait_for_function(f'() => MITTLER_EDITOR.undo.length > {u0}', timeout=20000)
                r = api(proj, 'ui', 'undo')
                time.sleep(1.0)
                check(r.get('ok') and not any(t['kind'] == 'subtitle' and any(c.get('from_tts') for c in t['clips']) for t in file_tl()['tracks']), '(c) ui undo：API の直しを取り消してファイルにも')
                r = api(proj, 'ui', 'nope')
                check(r.get('ok') is False and 'nope' in str(r.get('error')), '(c) 知らない操作：理由')

            # ---- (d) オート（AI を追う） ----
            reset()
            if not ONLY or 'd' in ONLY:
                r = api(proj, 'ui', 'follow', 'on')
                check(r.get('ok') and ev('MITTLER_FOLLOW.on') and ev("document.getElementById('followBtn').classList.contains('on')"), '(d) オン（上のバーのボタンが選んでいる見た目）')
                ev('() => { MITTLER_EDITOR.seek(0); MITTLER_EDITOR.setZoom(200); document.getElementById("lanesWrap").scrollLeft = 0; }')

                def ext(fn):
                    tl = file_tl(); fn(tl); tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')

                def clip(tl, cid):
                    return next(c for t in tl['tracks'] for c in t['clips'] if c['id'] == cid)
                u0 = ev('MITTLER_EDITOR.undo.length')
                ext(lambda tl: clip(tl, 'tts_3').update(start=10))
                try:
                    pg.wait_for_function('() => Math.abs(MITTLER_EDITOR.t - 10.5) < 1e-6', timeout=15000)
                    ok = True
                except Exception:
                    ok = False
                view = ev('() => { const w = document.getElementById("lanesWrap"); return [w.scrollLeft / MITTLER_EDITOR.pps, (w.scrollLeft + w.clientWidth) / MITTLER_EDITOR.pps]; }')
                flash = ev("() => !!document.querySelector('#laneList .clip.aiflash[data-id=\"tts_3\"]')")
                check(ok and view[0] <= 10 and 11 <= view[1] + 0.01 and flash, f"(d) 外で動かした → 再生位置が真ん中（{ev('MITTLER_EDITOR.t')}）・見える所（{view}）・光る印（{flash}）")
                check(ev('MITTLER_EDITOR.undo.length') == u0 + 1, '(d) 取り消しの記録は外の直しの 1 つだけ')
                ext(lambda tl: clip(tl, 'v_2').update(dur=2))
                try:
                    pg.wait_for_function('() => Math.abs(MITTLER_EDITOR.t - 5) < 1e-6', timeout=15000); ok = True
                except Exception:
                    ok = False
                check(ok, f"(d) 長さを変えた → 真ん中（{ev('MITTLER_EDITOR.t')}）")
                ext(lambda tl: next(t for t in tl['tracks'] if t['kind'] == 'subtitle')['clips'].append({'id': 'sub_new', 'type': 'subtitle', 'start': 6, 'dur': 1, 'text': '足した'}))
                try:
                    pg.wait_for_function('() => Math.abs(MITTLER_EDITOR.t - 6.5) < 1e-6', timeout=15000); ok = True
                except Exception:
                    ok = False
                check(ok, f"(d) 足した → 真ん中（{ev('MITTLER_EDITOR.t')}）")
                api(proj, 'ui', 'follow', 'off')
                t0 = ev('MITTLER_EDITOR.t')
                ext(lambda tl: clip(tl, 'tts_1').update(start=0.2))
                time.sleep(2.5)
                check(abs(ev('MITTLER_EDITOR.t') - t0) < 1e-6 and ev('MITTLER_EDITOR.tl.tracks.flatMap(t => t.clips).find(c => c.id === "tts_1").start') == 0.2, '(d) オフ：読み直すが再生位置は動かない')
                api(proj, 'ui', 'follow', 'on'); api(proj, 'ui', 'seek', '0')
                time.sleep(3.2)  # API で飛んだ直後（3 秒）はそちらが勝つ
                ev('() => MITTLER_EDITOR.setPlaying(true)')
                ext(lambda tl: clip(tl, 'tts_2').update(start=11))
                time.sleep(1.5)
                t1 = ev('MITTLER_EDITOR.t')
                flash = ev("() => !!document.querySelector('#laneList .clip.aiflash[data-id=\"tts_2\"]')")
                ev('() => MITTLER_EDITOR.setPlaying(false)')
                check(t1 < 5 and flash, f"(d) 再生中は飛ばない（{t1:.2f} 秒）・印だけ（{flash}）")
            # ---- (e) 使ってみた知らせ（2026-11-14）の直し ----
            reset()
            if not ONLY or 'e' in ONLY:
                # 6. セリフの速さ（生成のあと atempo）・5. 重なりの印
                r0 = api(proj, 'tts', 'tts_1')
                r1 = api(proj, 'tts', 'tts_1', '--tempo', '1.5')
                tl = file_tl(); c1 = next(c for t in tl['tracks'] for c in t['clips'] if c['id'] == 'tts_1')
                k = next(x for x in c1['takes'] if x['id'] == r1.get('take'))
                check(r1.get('ok') and c1.get('tempo') == 1.5 and k.get('tempo') == 1.5 and abs(r1['dur'] - r0['dur'] / 1.5) < 0.03,
                      f"(e6) tts --tempo 1.5：クリップの tempo・テイクの tempo・長さ {r0.get('dur')} → {r1.get('dur')}")
                ev("() => MITTLER_EDITOR.change(() => { const t = MITTLER_EDITOR.tl.tracks.find(x => x.kind === 'tts'); t.clips.find(c => c.id === 'tts_2').start = 1.2; })")
                pg.wait_for_function(SAVED, timeout=30000)
                ov = ev("() => !!document.querySelector('#laneList .clip.tts.overlap[data-id=\"tts_1\"] .ovl')")
                r = api(proj, 'tts', 'tts_1')
                check(ov and r.get('overlaps') == 'tts_2', f"(e5) 同じトラックのセリフが重なると印（{ov}）・API の結果にも（{r.get('overlaps')}）")
                # 2. 再生用の動画が無い作品で再生しても、失敗の色・右下の知らせにしない
                ev('() => { MITTLER_EDITOR.seek(0); MITTLER_EDITOR.setPlaying(true); }')
                time.sleep(1.5)
                lv = ev("() => document.getElementById('status').dataset.level")
                toasts = ev("() => document.querySelectorAll('.mittlerToast.bad').length")
                ev('() => MITTLER_EDITOR.setPlaying(false)')
                time.sleep(0.3)
                check(lv not in ('bad',) and toasts == 0 and ev("() => document.getElementById('status').dataset.level") != 'bad',
                      f"(e2) 再生用の動画が無くても赤くならない（上のバー {lv}・右下の失敗 {toasts}）・止めると消える")
                # 1. フック：いちばん最近さわった編集画面が別の作品なら、そちらの今
                ev('() => MITTLER_EDITOR.seek(1)'); time.sleep(1.2)
                other = work / 'p_new_api'
                if other.exists():
                    h = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'tools' / 'mittler_state.py'), str(other)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
                    check('別の作品' in h.stdout and str(proj) in h.stdout and '選んでいる' in h.stdout, f'(e1) フック：別の作品の編集画面を触っていたら、そちらの今をそえる（{h.stdout[:80]!r}）')
                # 3. mittler.cmd に空白・= ・, の入った引数
                sp = work / f'p_space_{int(time.time())}'
                r = subprocess.run(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node', str(ROOT / 'tools' / 'new_project.js'), str(sp), '--title', 'Kuro Coffee, A=B', '--no-git', '--json'],
                                   capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
                spf = sp / f'{sp.name}.cut.json'
                nm = json.loads(spf.read_text(encoding='utf-8')).get('name') if spf.exists() else None
                check(r.returncode == 0 and nm == 'Kuro Coffee, A=B', f'(e3) mittler.cmd：空白・, ・= の入った --title がそのまま届く（{nm}）')
            # ---- (f) Suno：歌詞の時刻（偽のサイドカー）・1 回の生成で 2 本の注意 ----
            reset()
            if not ONLY or 'f' in ONLY:
                tl = file_tl()
                next(t for t in tl['tracks'] if t['id'] == 't_music_0')['clips'] = [{'id': 'mu_1', 'type': 'audio', 'src': None, 'start': 0, 'dur': 6, 'in': 0, 'gain': 0, 'label': '曲',
                                                                                    'music': {'prompt': '', 'lyrics': 'こんにちは 世界\nまたね', 'title': 't', 'style': 'pop', 'instrumental': False, 'takes': [], 'activeTake': None}}]
                tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
                time.sleep(0.5); pg.goto(srv.url); pg.wait_for_function(READY, timeout=120000)
                (proj / 'work' / 'suno').mkdir(parents=True, exist_ok=True)
                subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=330:duration=6:sample_rate=48000', '-ac', '2', str(proj / 'assets' / 'music' / 'song_a.wav')], check=True)
                args = {'lyrics': 'こんにちは 世界\nまたね', 'style': 'pop', 'title': 't'}
                words = [{'word': 'こんにちは ', 'start_s': 0.5, 'end_s': 1.2, 'success': True}, {'word': '世界\n', 'start_s': 1.3, 'end_s': 2.0, 'success': True},
                         {'word': '[Chorus]\n', 'start_s': 2.0, 'end_s': 2.0, 'success': True}, {'word': 'またね\n', 'start_s': 3.0, 'end_s': 3.8, 'success': False}]
                for n, sid in ((1, '11111111-2222-3333-4444-555555555555'), (2, '66666666-2222-3333-4444-555555555555')):
                    (proj / 'work' / 'suno' / f's{n}.json').write_text(json.dumps({'source': 'suno-mcp', 'suno_id': sid, 'song_url': f'https://suno.com/song/{sid}', 'title': 't', 'lyrics': args['lyrics'],
                        'created': '2026-11-15T03:00:00Z', 'create_args': args, 'analysis': {'status': 'complete', 'bpm': 120, 'beats': [[0.5, 1], [1.0, 2]]},
                        'lyrics_alignment': {'status': 'complete', 'words': words}}, ensure_ascii=False), encoding='utf-8')
                r1 = api(proj, 'music-take', 'mu_1', '--sidecar', 'work/suno/s1.json', '--src', 'assets/music/song_a.wav')
                r2 = api(proj, 'music-take', 'mu_1', '--sidecar', 'work/suno/s2.json')
                check(r1.get('ok') and not r1.get('warnings') and (r1.get('lyrics_alignment') or {}).get('lines') == 2 and r1['lyrics_alignment']['uncertain'] == 1,
                      f"(f) music-take：歌詞の時刻を受け取る（行 {(r1.get('lyrics_alignment') or {}).get('lines')}・置けなかった単語 {(r1.get('lyrics_alignment') or {}).get('uncertain')}）・注意なし")
                check(r2.get('ok') and any('2 本目' in w for w in r2.get('warnings') or []), f"(f) 同じ生成の 2 本目は注意（受け取りは断らない）：{r2.get('warnings')}")
                pg.wait_for_function("() => (MITTLER_EDITOR.tl.tracks.flatMap(t => t.clips).find(c => c.id === 'mu_1').music.takes || []).length === 2", timeout=30000)
                pg.wait_for_function(SAVED, timeout=30000)
                sel('mu_1'); pg.click('.mtake[data-take=t1] .muAdopt')
                pg.wait_for_function("() => (MITTLER_EDITOR.tl.meta || []).some(m => m.kind === 'lyrics' && m.from_music === 'mu_1')", timeout=30000)
                pg.wait_for_function(SAVED, timeout=30000)
                m = next(x for x in file_tl()['meta'] if x['kind'] == 'lyrics' and x.get('from_music') == 'mu_1')
                it = m['items']
                check(len(it) == 2 and it[0]['text'] == 'こんにちは 世界' and len(it[0]['words']) == 2 and it[1].get('uncertain') == 1 and it[1]['words'][0][3] is False and m.get('from_suno'),
                      f"(f) 採用：歌詞のメタデータ（kind lyrics・行 {len(it)}・単語の時刻・置けなかった単語の印・from_music／from_suno）")
            check(not errs, f'ページのエラーなし {errs[:3]}')
            br.close()
    finally:
        srv.quit()
        vv.shutdown()
    print('---')
    print('FAIL の数', len(fails))
    return 1 if fails else 0


if __name__ == '__main__':
    w = opt('--work')
    if w:
        sys.exit(main(Path(w)))
    with tempfile.TemporaryDirectory() as d:
        sys.exit(main(Path(d)))
