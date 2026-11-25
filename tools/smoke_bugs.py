"""バグ直し（2026-11-12 のバグ探しの B1〜B16）のやり直しを防ぐ確かめ。ブラウザは要らない（描画の python＝numpy・opencv・Pillow の入ったもので流す）。
  <描画の python> -X utf8 tools/smoke_bugs.py [--work <フォルダ>] [--only B1,B2,…]
  （--work：試しの作品を残す場所。無ければ一時フォルダに作って消す。--only：その番号だけ）
試しの作品（320×180・30fps）は自分で作る。サーバーが要る項目は自分で立てて（127.0.0.1・空いているポート）、終わったら /api/quit で止める。
本物の Codex・H3・Gemini は動かさない。編集画面（ブラウザ）が要る確かめは tools/smoke_bugs_ui.py。
確かめること（番号は、2026-11-12 のバグ探しの報告 report_bughunt.md の番号）：
  B1  音のクリップ 400 個の mix が通る（前は引数が長すぎて落ちた）。引数・ファイル・組に分ける の 3 通りの渡し方で同じ WAV
  B2  書き出しの絵が並列の数で変わらない（1 コマごとに赤・青の画像クリップ 120 個。劣化なしの設定で 並列 1・4・7 の framemd5 が同じ）
  B4  読まれ続けているファイルの置きかえ（server/atomic.js）が失敗しない（画面の側は smoke_bugs_ui.py）
  B6  ジョブ係を同時に 2 つ起動しても、動き続けるのは 1 つ（ジョブは置かない＝Codex・H3 は動かない）
  B7  映像クリップの ffmpeg を開いたままにするのは上限まで。絵は上限なしと同じ
  B8  エフェクトのパラメータが指す絵を同じ名前で上書きすると、プレビューが読み直す
  B9  書き出しが失敗しても一時フォルダ _tmp が残らない
  B10 描く python の設定がまちがっているとき、すぐ理由つきで返る・起動し直しを繰り返さない
  B12 描く python だけ設定しても、既定の ffmpeg のフォルダを探す
  B13 サーバーを閉じたら、解析の（偽の）子プロセスも止まる
  B14 同じ素材の波形・動画の音・サムネを同時に頼んでも失敗しない
  B15 奇数の幅・高さを、作るとき・書き出す前に断る
  B16 小さいもの（mittler.cmd の引数と終了コード・拡張のエラーの画面・サーバーが 2 つ・%E0・仕上げの段の「止める」・再生用の動画づくりを止める）
  SPRITE 重ね絵が float の絵を受けても落ちない（uint8 の絵の結果は変わらない）
  SEEK   映像クリップへ直に飛んで読んだ絵＝頭から順に読んだ絵（素材 30・24fps × 作品 30・60fps、速さ 1・1.5・0.8）。書き出しの絵が並列 1・2・5・7・16 と --from で同じ
  MAYBE  「かもしれない」のうち直したもの（読めないファイルで落ちない・描画サーバーの返事が切れても待ち続けない・TTS の名前・ffprobe の数）
描画の python のほかに要るもの：ffmpeg・ffprobe（PATH）、Node（PATH の node か、Windows は tools\\mittler.cmd＝VS Code の Node）。TTS の項目は VOICEVOX が動いているときだけ。
"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 画面に出る日本語の文は辞書から引く（言い回しを直しても、この確かめを直さなくて済むように）
JA = json.loads((ROOT / 'editor' / 'i18n' / 'ja.json').read_text(encoding='utf-8'))
PY = sys.executable
ENGINE = ROOT / 'pyengine'
fails = []


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


def node_cmd():
    n = shutil.which('node')
    return [n] if n else ['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node']


def node(*args, timeout=120):
    return subprocess.run(node_cmd() + [str(a) for a in args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)


def engine(*args, timeout=600, env=None):
    """python -m mittler …（cwd は pyengine）"""
    return subprocess.run([PY, '-X', 'utf8', '-B', '-m', 'mittler', *map(str, args)], cwd=ENGINE, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout, env=env)


def framemd5(p):
    """映像の1コマごとの MD5 の並び"""
    r = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(p), '-map', '0:v:0', '-f', 'framemd5', '-'], capture_output=True, text=True, check=True)
    return [ln.split(',')[-1].strip() for ln in r.stdout.splitlines() if ln and not ln.startswith('#')]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close()
    return p


def make_project(d):
    """試しの作品：new_project で作って、320×180・赤と青の画像・短い音・音つきの短い動画を置く"""
    from PIL import Image
    r = node(ROOT / 'tools' / 'new_project.js', d, '--no-git', '--json', '--lang', 'ja')
    if r.returncode:
        raise SystemExit('new_project 失敗: ' + r.stdout + r.stderr)
    for name, col in (('red', (220, 30, 30)), ('blue', (30, 30, 220)), ('green', (30, 200, 30)), ('yellow', (230, 220, 30))):
        Image.new('RGB', (320, 180), col).save(d / 'assets' / 'images' / f'{name}.png')
    ff = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'sine=frequency=880:duration=0.5:sample_rate=48000', '-ac', '2', str(d / 'assets' / 'sfx' / 'beep.wav')], check=True)
    subprocess.run(ff + ['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=8', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '15', str(d / 'assets' / 'videos' / 'v1.mp4')], check=True)
    tlf = d / f'{d.name}.cut.json'
    tl = json.loads(tlf.read_text(encoding='utf-8'))
    tl.update(width=320, height=180, fps=30, duration=4)
    tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    return tlf


def variant(P, name, edit):
    """試しの作品のタイムラインの写し <name>.test.cut.json（edit(tl) で中身を作る）"""
    tl = json.loads((P / f'{P.name}.cut.json').read_text(encoding='utf-8'))
    edit(tl)
    f = P / f'{name}.test.cut.json'
    f.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    return f


def track(tl, kind):
    return next(t for t in tl['tracks'] if t['kind'] == kind)


LOSSLESS = {'video': {'crf': 0, 'preset': 'ultrafast'}}  # 劣化なし（区間の切り方でエンコードの結果が変わらない。絵が同じなら framemd5 も同じ）


# ---------------------------------------------------------------- B2
def b2(P, out):
    def edit(tl):
        tl['duration'] = 4
        tl['settings']['export'] = LOSSLESS
        track(tl, 'video')['clips'] = [{'id': f'c{i}', 'type': 'image', 'src': 'assets/images/' + ('red.png' if i % 2 else 'blue.png'), 'start': i / 30, 'dur': (i + 1) / 30 - i / 30}
                                       for i in range(120)]
    tlf = variant(P, 'b2', edit)
    md = {}
    for j in (1, 4, 7):
        r = engine('video', tlf, out / f'b2_j{j}.mp4', '--jobs', j)
        if r.returncode:
            check(False, f'B2 書き出し（並列 {j}）が失敗: ' + (r.stdout + r.stderr)[-400:])
            return
        md[j] = framemd5(out / f'b2_j{j}.mp4')
    bad = {j: [i for i, (a, b) in enumerate(zip(md[1], md[j])) if a != b] for j in (4, 7)}
    check(len(md[1]) == 120 and len(set(md[1])) == 2, f'B2 並列 1：120 コマが赤・青の 2 種類の絵（{len(md[1])} コマ・{len(set(md[1]))} 種類）')
    check(md[1][0::2] == [md[1][0]] * 60 and md[1][1::2] == [md[1][1]] * 60, 'B2 並列 1：1 コマごとに入れ替わる（偶数のコマが青・奇数のコマが赤）')
    check(not bad[4] and not bad[7], f'B2 書き出しの絵が並列の数で変わらない（並列 1 と違うコマ：並列 4 → {bad[4]}、並列 7 → {bad[7]}）')
    # 一部の書き出し（--from）も、全体の書き出しの同じコマと同じ絵
    r = engine('video', tlf, out / 'b2_part.mp4', '--jobs', 3, '--from', 1, '--to', 3)
    part = framemd5(out / 'b2_part.mp4') if not r.returncode else []
    check(part == md[1][30:90], 'B2 一部の書き出し（1〜3 秒・並列 3）が、全体の書き出しの同じコマと同じ絵')


# ---------------------------------------------------------------- B1
def b1(P, out):
    def clips(n):
        return [{'id': f'se{i}', 'type': 'audio', 'src': 'assets/sfx/beep.wav', 'start': i * 0.25, 'dur': 0.4, 'in': 0, 'gain': -12 - (i % 5), 'fade_in': 0.01, 'fade_out': 0.05} for i in range(n)]

    def edit(n):
        def f(tl):
            tl['duration'] = n * 0.25 + 1
            track(tl, 'audio')['clips'] = clips(n)
        return f
    t60, t400 = variant(P, 'b1_60', edit(60)), variant(P, 'b1_400', edit(400))
    # 400 個（前は引数が長すぎて WinError 206 で落ちた）
    r = engine('mix', t400, out / 'b1_400.wav')
    ok = not r.returncode and (out / 'b1_400.wav').is_file()
    check(ok and json.loads(r.stdout.strip().splitlines()[-1]).get('clips') == 400, 'B1 音のクリップ 400 個の mix が通る' + ('' if ok else '：' + (r.stdout + r.stderr)[-300:]))
    # 60 個：引数で渡す（今まで）・フィルタをファイルで渡す・組に分けて下混ぜ の 3 通りが同じ WAV。ファイルで渡す書き方は、片方が使えない ffmpeg でももう片方で通る
    code = r'''
import hashlib, json, sys
from mittler import mix
tl, outdir = sys.argv[1], sys.argv[2]
res = {}
orig = mix._run
for name, maxcmd, opts in (('args', 10 ** 9, None), ('file', None, None), ('file_rev', None, list(reversed(mix.SCRIPT_OPTS))), ('parts', None, None)):
    calls = []
    def run(cmd, calls=calls):
        r = orig(cmd); calls.append(('file' if any(o in cmd for o in mix.SCRIPT_OPTS) else 'args') + ('' if not r.returncode else '!')); return r
    mix._run = run
    items = mix.clip_inputs(json.load(open(tl, encoding='utf-8')), __import__('pathlib').Path(tl).parent)
    inputs = mix._cmdlen([x for it in items for x in ('-i', it['file'])])
    mix.MAXCMD = maxcmd or (inputs + 2000 if name != 'parts' else inputs // 3)
    mix.SCRIPT_OPTS = opts or ['-/filter_complex', '-filter_complex_script']
    o = outdir + '/b1_60_' + name + '.wav'
    mix.mix(tl, o)
    res[name] = [hashlib.sha256(open(o, 'rb').read()).hexdigest(), calls]
print(json.dumps(res))
'''
    r = subprocess.run([PY, '-X', 'utf8', '-B', '-c', code, str(t60), str(out)], cwd=ENGINE, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    if r.returncode:
        check(False, 'B1 60 個の 3 通りの mix が失敗: ' + (r.stdout + r.stderr)[-500:])
        return
    res = json.loads(r.stdout.strip().splitlines()[-1])
    check(res['args'][1] == ['args'] and res['file'][1][-1] == 'file' and len(res['parts'][1]) >= 4, f"B1 3 通りの渡し方を通った（{ {k: v[1] for k, v in res.items()} }）")
    check(len({v[0] for v in res.values()}) == 1, f"B1 60 個の WAV が、引数・ファイル・組に分けて下混ぜ のどれでも同じ（{ {k: v[0][:12] for k, v in res.items()} }）")
    check(sum(c.endswith('!') for c in res['file'][1] + res['file_rev'][1]) == 1, 'B1 フィルタをファイルで渡す書き方：使えないほうは失敗して、もう片方で通る（-/filter_complex と -filter_complex_script）')


# ---------------------------------------------------------------- B4（サーバーの側：置きかえのやり直し）
def b4(P, out):
    """server/atomic.js：Python が読み続けているファイルを、Node が「書いて置きかえる」を 300 回。1 回も失敗しない（前の書き方は Windows で EPERM になる）"""
    import threading
    d = out / 'b4'; d.mkdir(exist_ok=True)
    f = d / 'tl.cut.json'; f.write_text('{}', encoding='utf-8')
    js = d / 'w.js'
    js.write_text('''const fs = require('fs'), path = require('path');
const A = require(path.join(process.argv[2], 'server', 'atomic.js'));
const f = process.argv[3], body = JSON.stringify({ pad: 'x'.repeat(300000) });
let ok = 0, retried = 0; const errs = {};
(async () => {
  for (let i = 0; i < 300; i++) {
    try { fs.writeFileSync(f + '.tmp', body + i); if (A.replace(f + '.tmp', f) > 0) retried++; ok++; } catch (e) { errs[e.code] = (errs[e.code] || 0) + 1; }
    await new Promise(r => setTimeout(r, 5));
  }
  console.log(JSON.stringify({ ok, retried, errs }));
})();
''', encoding='utf-8', newline='\n')
    stop, reads = [], [0]

    def reader():  # 描画サーバーの sig() と同じ読み方を、間をあけずに続ける
        while not stop:
            try:
                hashlib.sha1(f.read_bytes()).hexdigest(); reads[0] += 1
            except OSError:
                pass
    th = threading.Thread(target=reader, daemon=True); th.start()
    try:
        r = node(js, ROOT, f, timeout=180)
    finally:
        stop.append(1); th.join(timeout=5)
    res = json.loads(r.stdout.strip().splitlines()[-1]) if not r.returncode else {'error': r.stdout + r.stderr}
    check(res.get('ok') == 300 and not res.get('errs'), f'B4 読まれ続けているファイルの置きかえ 300 回が全部通る（{res}・読んだ回数 {reads[0]}）')


# ---------------------------------------------------------------- B6
def b6(P, out):
    """ジョブ係（tools/jobs.py）を同時に 2 つ起動して、いつも 1 つだけ残る。ジョブは置かない（Codex・H3 は動かない）。残った 1 つは、何も無ければ数秒で自分で止まる"""
    lock = P / 'work' / 'jobs' / 'runner.json'
    env = dict(os.environ, MITTLER_JOBS_IDLE='4')
    counts = []
    for i in range(8):
        ps = [subprocess.Popen([PY, '-X', 'utf8', str(ROOT / 'tools' / 'jobs.py'), str(P)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env) for _ in range(2)]
        time.sleep(2.0)
        counts.append(sum(p.poll() is None for p in ps))
        for p in ps:  # 残った 1 つが自分で止まるのを待つ（4 秒なにも無ければ止まる）
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.terminate()
                counts.append('止まらない')
    check(counts == [1] * 8, f'B6 ジョブ係を同時に 2 つ起動 × 8 回：動き続けるのはいつも 1 つ（{counts}）')
    check(not lock.exists(), 'B6 止まったあと、動いている印（runner.json）が残らない')


# ---------------------------------------------------------------- B7
def b7(P, out):
    """映像クリップ 12 本（0.5 秒ずつ。3 本目は素材が途中で尽きる）を頭から終わりまで描く：開いたままの ffmpeg は上限まで。絵は、上限なし（前の動き）と全部のコマで同じ"""
    def edit(tl):
        tl['duration'] = 6
        cl = [{'id': f'v{i}', 'type': 'video', 'src': ['assets/videos/v1.mp4'], 'start': i * 0.5, 'dur': 0.5, 'in': (i * 0.6) % 7, 'speed': 1} for i in range(12)]
        cl[2]['in'] = 7.8  # 素材（8 秒）が 0.2 秒で尽きる：あとは最後のコマで止まる
        track(tl, 'video')['clips'] = cl
    tlf = variant(P, 'b7', edit)
    code = r'''
import hashlib, json, sys
from mittler.engine import Engine
res = {}
for name, cap in (('cap', None), ('nocap', 10 ** 9)):
    eng = Engine(sys.argv[1])
    if cap:
        eng.MAX_OPEN = cap
    h = hashlib.sha256()
    peak = 0
    for n in range(int(round(eng.duration * eng.fps))):
        h.update(eng.render(n / eng.fps).tobytes())
        peak = max(peak, sum(1 for v in eng._videos.values() if getattr(v, 'proc', None) is not None and v.proc.poll() is None))
    live = sum(1 for v in eng._videos.values() if getattr(v, 'proc', None) is not None and v.proc.poll() is None)
    back = hashlib.sha256(eng.render(44 / eng.fps).tobytes()).hexdigest()  # 3 本目の、素材が尽きたあとのコマへ戻る（覚えている最後のコマが出る）
    res[name] = dict(sha=h.hexdigest(), live=live, peak=peak, back=back, max=eng.MAX_OPEN)
    eng.close()
print(json.dumps(res))
'''
    r = subprocess.run([PY, '-X', 'utf8', '-B', '-c', code, str(tlf)], cwd=ENGINE, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    if r.returncode:
        check(False, 'B7 描けなかった: ' + (r.stdout + r.stderr)[-500:])
        return
    res = json.loads(r.stdout.strip().splitlines()[-1])
    c, n = res['cap'], res['nocap']
    check(c['peak'] <= c['max'] and c['live'] <= c['max'], f"B7 開いたままの ffmpeg は上限 {c['max']} 本まで（いちばん多いとき {c['peak']} 本・最後 {c['live']} 本。上限なしだと {n['peak']} 本）")
    check(n['peak'] >= 11, f"B7 上限なし（前の動き）だと、通ったクリップの数だけたまる（{n['peak']} 本）")
    check(c['sha'] == n['sha'], 'B7 180 コマの絵が、上限あり・なしで同じ')
    check(c['back'] == n['back'], 'B7 ffmpeg を止めたクリップの、素材が尽きたあとのコマも同じ絵（覚えている最後のコマ）')
    md = []
    r = engine('video', tlf, out / 'b7.mp4', '--jobs', 1)
    check(not r.returncode, 'B7 書き出し（並列 1）が通る' + ('' if not r.returncode else (r.stdout + r.stderr)[-300:]))


class Render:
    """描画サーバー（python -m mittler serve）を直に立てる。止めるのは /quit"""

    def __init__(self, tlf):
        self.port = free_port()
        self.p = subprocess.Popen([PY, '-X', 'utf8', '-B', '-m', 'mittler', 'serve', str(tlf), '--port', str(self.port)], cwd=ENGINE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding='utf-8', errors='replace')
        ln = self.p.stdout.readline()
        if 'serving' not in ln:
            raise SystemExit('描画サーバーが起動しない: ' + ln)

    def get(self, path):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}{path}', timeout=120) as r:
            return r.read()

    def quit(self):
        try:
            self.get('/quit')
        except Exception:
            pass
        try:
            self.p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.p.terminate()


# ---------------------------------------------------------------- B8
def b8(P, out):
    """エフェクトのパラメータが指す絵（sprite の img）を同じ名前で上書きすると、プレビューの絵が変わる（キャッシュのコマも、描き直すコマも）"""
    from PIL import Image
    sp = P / 'assets' / 'overlays' / 'sp.png'
    Image.new('RGBA', (80, 60), (30, 200, 30, 255)).save(sp)

    def edit(tl):
        tl['duration'] = 3
        track(tl, 'video')['clips'] = [{'id': 'a', 'type': 'image', 'src': 'assets/images/red.png', 'start': 0, 'dur': 3}]
        tl['tracks'].insert(0, {'id': 't_fx', 'name': 'fx', 'kind': 'effect', 'clips': [{'id': 'sp', 'type': 'effect', 'effect': 'sprite', 'start': 0, 'dur': 3,
                                'params': {'img': 'assets/overlays/sp.png', 'x': 160, 'y': 90, 't0': 0, 't1': 3, 'anim': 'none', 'scale': 1}}]})
    tlf = variant(P, 'b8', edit)
    R = Render(tlf)
    try:
        h = lambda t: hashlib.sha1(R.get(f'/frame?t={t}')).hexdigest()[:12]
        a1, a2 = h(1), h(2)
        loads0 = json.loads(R.get('/info'))['loads']
        time.sleep(1.1)
        Image.new('RGBA', (80, 60), (230, 220, 30, 255)).save(sp)  # 同じ名前で上書き（緑 → 黄）
        b1_, b2_ = h(1), h(2)
        info = json.loads(R.get('/info'))
        check(a1 != b1_, f'B8 上書きの前に描いてあったコマ（キャッシュ）が新しい絵になる（{a1} → {b1_}）')
        check(a2 != b2_, f'B8 描き直すコマも新しい絵になる（{a2} → {b2_}）')
        check(info['loads'] == loads0 + 1, f"B8 読み直しは 1 回だけ（{loads0} → {info['loads']}）")
        c1 = h(1)
        check(c1 == b1_ and json.loads(R.get('/info'))['loads'] == info['loads'], 'B8 上書きしていなければ読み直さない（同じ絵・読み直しの回数も同じ）')
    finally:
        R.quit()


# ---------------------------------------------------------------- B9
def b9(P, out):
    """書き出しが失敗しても、区間の一時フォルダ（_tmp/mittler_*）が残らない。うまくいったときも空の _tmp が残らない"""
    (P / 'effects' / 'boom.py').write_text('"""試し：1 秒より後ろのコマで落ちるエフェクト"""\nSTAGE = \'post\'\nMETA = {\'label\': \'boom\', \'window\': {\'clip\': True}, \'params\': {}}\n\n\n'
                                           'def apply(ctx, f, clip):\n    if ctx.t > 1.0:\n        raise RuntimeError(\'boom\')\n    return f\n', encoding='utf-8', newline='\n')

    def edit(boom):
        def f(tl):
            tl['duration'] = 2
            track(tl, 'video')['clips'] = [{'id': 'a', 'type': 'image', 'src': 'assets/images/red.png', 'start': 0, 'dur': 2}]
            if boom:
                tl['tracks'].insert(0, {'id': 't_fx', 'name': 'fx', 'kind': 'effect', 'clips': [{'id': 'bm', 'type': 'effect', 'effect': 'boom', 'start': 0, 'dur': 2, 'params': {}}]})
        return f
    d = out / 'b9'; d.mkdir(exist_ok=True)
    r = engine('video', variant(P, 'b9_boom', edit(True)), d / 'boom.mp4', '--jobs', 2)
    left = sorted(p.name for p in (d / '_tmp').rglob('*')) if (d / '_tmp').exists() else None
    check(r.returncode != 0 and '区間' in (r.stdout + r.stderr), 'B9 落ちるエフェクトの書き出しは、区間の失敗として止まる')
    check(left is None, f'B9 失敗のあと、一時フォルダ _tmp が残らない（{left}）')
    r = engine('video', variant(P, 'b9_ok', edit(False)), d / 'ok.mp4', '--jobs', 2)
    check(not r.returncode and (d / 'ok.mp4').is_file() and not (d / '_tmp').exists(), 'B9 うまくいった書き出しのあとも、空の _tmp が残らない')
    (P / 'effects' / 'boom.py').unlink()


class Server:
    """編集画面のサーバー（tools\\mittler.cmd serve）。止めるのは /api/quit"""

    def __init__(self, tlf, logf, args=(), env=None, render_python=PY):
        e = dict(os.environ, MITTLER_NO_REVEAL='1'); e.update(env or {})
        self.logf = Path(logf)
        self.log = open(self.logf, 'w', encoding='utf-8', errors='replace')
        # --lang ja：サーバーが返す文（理由・注意）を日本語で確かめる（既定は英語。英語の確かめは tools/smoke_i18n.py）
        self.p = subprocess.Popen(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'serve', str(tlf), '--port', str(free_port())] + (['--render-python', str(render_python)] if render_python else [])
                                  + ['--lang', 'ja'] + [str(a) for a in args], stdout=subprocess.PIPE, stderr=self.log, env=e, text=True, encoding='utf-8', errors='replace')
        self.url = self.p.stdout.readline().strip()
        if not self.url.startswith('http://127.0.0.1:'):
            raise SystemExit('サーバーが起動しない: ' + self.url)
        self.token = re.search(r'token=(\w+)', self.url).group(1)
        self.base = self.url.split('/editor/')[0]

    def call(self, path, body=None, method=None, timeout=120, token=True):
        """→ (HTTP の番号, 中身の bytes, かかった秒)"""
        t0 = time.time()
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode('utf-8'), method=method or ('POST' if body is not None else 'GET'),
                                     headers={'X-Mittler-Token': self.token} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), time.time() - t0
        except urllib.error.HTTPError as e:
            return e.code, e.read(), time.time() - t0

    def json(self, path, body=None, **kw):
        return json.loads(self.call(path, body, **kw)[1])

    def ready(self, sec=120):
        st = {}
        for _ in range(int(sec * 2)):
            st = self.json('/api/status')
            if st.get('ready') or st.get('error'):
                return st
            time.sleep(0.5)
        return st

    def text(self):
        self.log.flush()
        return self.logf.read_text(encoding='utf-8', errors='replace')

    def quit(self):
        try:
            self.call('/api/quit', body={}, timeout=10)
        except Exception as e:
            print('quit 失敗', e)
        try:
            self.p.wait(timeout=45)
        except subprocess.TimeoutExpired:
            print('サーバーが止まらない pid', self.p.pid)
        self.log.close()


def simple_tl(P, name):
    def edit(tl):
        tl['duration'] = 3
        track(tl, 'video')['clips'] = [{'id': 'a', 'type': 'image', 'src': 'assets/images/red.png', 'start': 0, 'dur': 3}]
    return variant(P, name, edit)


# ---------------------------------------------------------------- B10
def b10(P, out):
    """描く python の設定がまちがっているとき：すぐ理由つきで返る（前は 1 コマごとに 90 秒待つ／落ちては起動し直すのを繰り返す）"""
    tlf = simple_tl(P, 'b10')
    # 1. 無いファイル
    S = Server(tlf, out / 'b10_1.log', render_python=r'C:\nonexistent_mittler\python.exe')
    try:
        st = S.ready(20)
        check(JA['srv.py.settingMissing'].split('（')[0] in str(st.get('error')), f"B10 無い python：/api/status に理由（{str(st.get('error'))[:70]}）")
        code, body, sec = S.call('/api/frame?t=0', timeout=110)
        check(code == 500 and sec < 15, f'B10 無い python：1 コマの頼みがすぐエラーで返る（HTTP {code}・{sec:.1f} 秒。前は 90 秒）')
    finally:
        S.quit()
    # 2. opencv を import できない python（この python に、落ちる cv2 を先に見つけさせる）
    stub = out / 'b10_stub'; stub.mkdir(exist_ok=True)
    (stub / 'cv2.py').write_text("raise ImportError('no cv2 here (smoke_bugs)')\n", encoding='utf-8')
    S = Server(tlf, out / 'b10_2.log', env={'PYTHONPATH': str(stub)})
    try:
        st = S.ready(30)
        err = str(st.get('error'))
        check(JA['srv.py.settingNoImport'].split('{py}）')[1].split('：')[0] in err and 'no cv2 here' in err, f'B10 opencv の無い python：/api/status に理由（{err[:90]}）')
        t0 = time.time()
        while time.time() - t0 < 7:  # 編集画面と同じく 2 秒ごとに聞く
            S.json('/api/status'); time.sleep(2)
        code, body, sec = S.call('/api/frame?t=0', timeout=110)
        check(code == 500 and sec < 15 and 'no cv2 here' in body.decode('utf-8', 'replace'), f'B10 opencv の無い python：1 コマの頼みがすぐ理由つきで返る（HTTP {code}・{sec:.1f} 秒）')
        n = S.text().count('描画サーバーを起動し直します')
        check(n <= 2, f'B10 opencv の無い python：起動し直しを繰り返さない（7 秒で {n} 回。前は約 10 秒で 12 回）')
    finally:
        S.quit()
    # 3. 正しい python：今までどおり描ける
    S = Server(tlf, out / 'b10_3.log')
    try:
        st = S.ready()
        code, body, sec = S.call('/api/frame?t=0')
        check(st.get('ready') and code == 200 and body[:2] == b'\xff\xd8', 'B10 正しい python：描ける（JPEG が返る）')
    finally:
        S.quit()


# ---------------------------------------------------------------- B12
def b12(P, out):
    """描く python だけを設定したときも、既定の ffmpeg のフォルダ（server/defaults.js の ffmpegDirs）を探す"""
    d = out / 'b12_ffmpeg'; d.mkdir(exist_ok=True)
    (d / 'ffmpeg.exe').write_bytes(b'')  # あるかどうかだけを見る
    js = out / 'b12.js'
    js.write_text('''const path = require('path');
const [root, project, tl, py, dir] = process.argv.slice(2);
const PR = require(path.join(root, 'server', 'pyrender.js'));
(async () => {
  const out = {};
  for (const [name, local, defs] of [['python_only', { python: py }, [dir]], ['both', { python: py, ffmpegDir: 'X:/set' }, [dir]], ['none_found', { python: py }, [dir + '_nothing']]]) {
    const r = PR.start({ project, timelineName: tl, local, defaultFfmpegDirs: defs, log: () => { } });
    try { out[name] = (await r.ensure()).ffmpegDir; } catch (e) { out[name] = 'ERR ' + e.message; }
    await r.waitReady().catch(() => { }); r.close();
  }
  console.log(JSON.stringify(out)); setTimeout(() => process.exit(0), 1500);
})();
''', encoding='utf-8', newline='\n')
    tlf = simple_tl(P, 'b12')
    r = node(js, ROOT, P, tlf.name, PY, d, timeout=180)
    res = json.loads(r.stdout.strip().splitlines()[-1]) if not r.returncode and r.stdout.strip() else {'error': (r.stdout + r.stderr)[-400:]}
    check(res.get('python_only') == str(d), f"B12 python だけ設定：既定の ffmpeg のフォルダを使う（{res.get('python_only') or res}）")
    check(res.get('both') == 'X:/set', f"B12 ffmpeg のフォルダも設定していれば、そちら（{res.get('both')}）")
    check(res.get('none_found') == '', f"B12 既定の場所に ffmpeg が無ければ空（PATH の ffmpeg）（{res.get('none_found')!r}）")


# ---------------------------------------------------------------- B14
def b14(P, out):
    """同じ素材の波形・動画の音・サムネを同時に頼んでも、どれも失敗しない（前は同じ名前の一時ファイルを取り合って片方が失敗した）"""
    import concurrent.futures as cf
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=20', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=20:sample_rate=48000',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(P / 'assets' / 'videos' / 'b14.mp4')], check=True)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=330:duration=120:sample_rate=48000', '-ac', '2', str(P / 'assets' / 'sfx' / 'b14.wav')], check=True)

    def edit(tl):
        tl['duration'] = 3
        track(tl, 'video')['clips'] = [{'id': f'v{i}', 'type': 'video', 'src': ['assets/videos/b14.mp4'], 'start': i * 0.5, 'dur': 0.5, 'in': 1.0, 'speed': 1} for i in range(4)]
    S = Server(variant(P, 'b14', edit), out / 'b14.log')
    try:
        S.ready()
        with cf.ThreadPoolExecutor(8) as ex:
            wave = list(ex.map(lambda i: S.json('/api/wave?src=assets/sfx/b14.wav'), range(6)))
            va = list(ex.map(lambda i: S.json('/api/video_audio', {'src': 'assets/videos/b14.mp4'}), range(4)))
            th = list(ex.map(lambda i: S.call(f'/api/thumb?clip=v{i}')[0], range(4)))  # 4 本とも同じ素材・同じ秒＝同じサムネ
        check(all(w.get('ok') for w in wave), f"B14 波形を同時に 6 つ：全部通る（{[w.get('ok') or w.get('error') for w in wave]}）")
        check(all(v.get('ok') and v.get('path') for v in va), f"B14 動画の音を同時に 4 つ：全部通る（{[v.get('ok') or v.get('error') for v in va]}）")
        check(th == [200] * 4, f'B14 同じサムネを同時に 4 つ：全部通る（{th}）')
    finally:
        S.quit()


# ---------------------------------------------------------------- B13
def b13(P, out):
    """🔬 解析の途中でサーバーを止めたら、解析の python も止まる。本物の解析は動かさない：解析の python の代わりに、長く眠るだけの偽の子プロセス
    （この python に、解析として起動されたときだけ 90 秒眠る sitecustomize を先に読ませる）"""
    stub = out / 'b13_stub'; stub.mkdir(exist_ok=True)
    pidf = out / 'b13_pid.txt'
    if pidf.exists():
        pidf.unlink()
    (stub / 'sitecustomize.py').write_text('import os, sys, time\nif "mittler.analyze" in getattr(sys, "orig_argv", []):\n'
                                           '    open(os.environ["B13_PIDFILE"], "w").write(str(os.getpid()))\n    time.sleep(90)\n    raise SystemExit(1)\n', encoding='utf-8')

    def edit(tl):
        tl['duration'] = 3
        track(tl, 'audio')['clips'] = [{'id': 'se', 'type': 'audio', 'src': 'assets/sfx/beep.wav', 'start': 0, 'dur': 0.5, 'in': 0}]
    tlf = variant(P, 'b13', edit)
    # VS Code の中と同じ形：Node のプロセスは生きたまま、サーバーだけを閉じる（編集画面のタブを閉じたとき。単体の mittler.cmd serve は Node ごと終わるので、
    # Windows では子も一緒に終わってしまい、確かめにならない）
    js = out / 'b13.js'
    js.write_text('''const path = require('path'), fs = require('fs'), http = require('http');
const [root, tl, py, pidf] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const alive = pid => { try { process.kill(pid, 0); return true; } catch (e) { return false; } };
(async () => {
  const s = await require(path.join(root, 'server', 'server.js')).start({ timeline: tl, port: 0, local: { python: py }, analysisPython: py });
  const body = JSON.stringify({ clip: { id: 'se', type: 'audio', src: 'assets/sfx/beep.wav', start: 0, dur: 0.5, in: 0 }, kind: 'beats' });
  const posted = await new Promise((ok, ng) => { const q = http.request({ host: '127.0.0.1', port: s.port, path: '/api/analyze', method: 'POST', headers: { 'X-Mittler-Token': s.token } },
    r => { let b = ''; r.on('data', d => { b += d; }); r.on('end', () => ok(b)); }); q.on('error', ng); q.end(body); });
  let pid = 0;
  for (let i = 0; i < 150 && !pid; i++) { await sleep(200); try { pid = +fs.readFileSync(pidf, 'utf8') || 0; } catch (e) { } }
  const before = pid ? alive(pid) : false;
  s.close();
  let after = true;
  for (let i = 0; i < 24 && after; i++) { await sleep(250); after = alive(pid); }
  console.log(JSON.stringify({ posted, pid, before, after }));
  if (pid && after) require('child_process').spawnSync('taskkill', ['/T', '/F', '/PID', String(pid)]);  // 自分の確かめが起動したものは残さない
  setTimeout(() => process.exit(0), 25000).unref();
})().catch(e => { console.log(JSON.stringify({ error: String(e.stack || e) })); process.exit(1); });
''', encoding='utf-8', newline='\n')
    env = dict(os.environ, MITTLER_NO_REVEAL='1', PYTHONPATH=str(stub), B13_PIDFILE=str(pidf))
    r = subprocess.run(node_cmd() + [str(js), str(ROOT), str(tlf), PY, str(pidf)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180, env=env)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith('{')]
    res = json.loads(lines[-1]) if lines else {'error': (r.stdout + r.stderr)[-400:]}
    check(res.get('before') is True, f'B13 解析の（偽の）子プロセスが動いている（{res}）')
    check(res.get('before') is True and res.get('after') is False, f"B13 サーバーを閉じたら（Node は生きたまま）、解析の子プロセスも止まる（pid {res.get('pid')}）")


# ---------------------------------------------------------------- B15
def b15(P, out):
    """奇数の幅・高さ：new_project は作る前に断る。手で奇数にしたタイムラインの書き出しは、描く前に理由つきで止まる"""
    np_ = ROOT / 'tools' / 'new_project.js'
    d = out / 'b15'; d.mkdir(exist_ok=True)
    for args, word in ((['--width', '641'], '偶数'), (['--height', '361'], '偶数'), (['--width', 'abc'], '正の数'), (['--fps', '0'], '正の数')):
        r = node(np_, d / 'odd', '--no-git', *args)
        check(r.returncode != 0 and word in (r.stdout + r.stderr) and not (d / 'odd').exists(), f"B15 new_project {' '.join(args)}：作らずに断る（{(r.stdout + r.stderr).strip()[:60]}）")
    r = node(np_, '--json', d / 'even', '--no-git', '--width', '640', '--height', '360', '--fps', '29.97', '--duration', '2.5')
    tl = json.loads((d / 'even' / 'even.cut.json').read_text(encoding='utf-8')) if (d / 'even' / 'even.cut.json').is_file() else {}
    check(not r.returncode and [tl.get(k) for k in ('width', 'height', 'fps', 'duration')] == [640, 360, 29.97, 2.5], f"B15 new_project --json を作品フォルダの前に置いても作れる・値が入る（{(r.stdout + r.stderr).strip()[:80]}）")

    def edit(tl):
        tl.update(width=641, height=361, duration=1)
        track(tl, 'video')['clips'] = [{'id': 'a', 'type': 'image', 'src': 'assets/images/red.png', 'start': 0, 'dur': 1}]
    tlf = variant(P, 'b15', edit)
    r = engine('video', tlf, d / 'odd.mp4', '--jobs', 2)
    msg = r.stdout + r.stderr
    check(r.returncode != 0 and '奇数' in msg and '641×361' in msg and 'PROGRESS' not in msg, f'B15 奇数の大きさの書き出しは、描く前に理由つきで止まる（{msg.strip()[-90:]}）')
    r = engine('segment', tlf, d / 'odd_seg.mp4', '--from', 0, '--to', 1)
    msg = r.stdout + r.stderr
    check(r.returncode != 0 and 'エンコードの ffmpeg が失敗' in msg, f'B15 区間のエンコードの失敗は、ffmpeg の失敗として知らせる（{msg.strip()[-80:]}）')


# ---------------------------------------------------------------- 重ね絵（sprite）が float の絵を受けても落ちない
def sprite_float(P, out):
    """effects_lib/common/sprite.py：'post' の段で float の絵を返すエフェクトのあとに置いても描ける。uint8 の絵のときの結果は 1 ビットも変わらない"""
    import importlib.util
    import numpy as np
    from PIL import Image
    spec = importlib.util.spec_from_file_location('sprite_now', ROOT / 'effects_lib' / 'common' / 'sprite.py'); sp = importlib.util.module_from_spec(spec); spec.loader.exec_module(sp)
    img = P / 'assets' / 'overlays' / 'spf.png'
    Image.new('RGBA', (60, 40), (250, 240, 30, 200)).save(img)

    class Ctx:
        t, root, cache = 0.5, P, {}
    rng = np.random.default_rng(7)
    base = rng.integers(0, 256, (180, 320, 3), dtype=np.uint8)
    clip = {'params': {'img': 'assets/overlays/spf.png', 'x': 160, 'y': 90, 't0': 0, 't1': 3, 'anim': 'wobble', 'scale': 1.3}}
    a = sp.apply(Ctx, base, clip)
    try:
        b = sp.apply(Ctx, base.astype(np.float32), clip)
        c = sp.apply(Ctx, base.astype(np.float32) * 1.5 - 20, clip)
        ok, same = True, bool((a == b).all()) and c.dtype == np.uint8
    except Exception as e:
        ok, same = False, str(e)
    check(ok and same, f'重ね絵 float の絵を受けても描ける（uint8 の絵のときと同じ結果。{same}）')
    # uint8 の絵のときは、直す前と同じ結果（前の版の式をそのまま：Image.fromarray(f) に uint8 を渡す道は変えていない）
    src = (ROOT / 'effects_lib' / 'common' / 'sprite.py').read_text(encoding='utf-8')
    old = src.replace("    if f.dtype != np.uint8:  # ", "    if False:  # ")
    ns = {}
    exec(compile(old, 'sprite_old', 'exec'), ns)
    hs = []
    for anim in ('pop', 'soft', 'slam', 'float', 'zip', 'wobble', 'none'):
        for t in (0.05, 0.5, 2.9, 3.1):
            Ctx.t = t; clip['params']['anim'] = anim
            hs.append(bool((sp.apply(Ctx, base, clip) == ns['apply'](Ctx, base, clip)).all()))
    check(all(hs) and 'if False:  # ' in old, f'重ね絵 uint8 の絵のときは、直す前の道と 1 ビットも同じ（出方 7 つ × 4 時刻＝{sum(hs)}/{len(hs)}）')


# ---------------------------------------------------------------- バグ探しの「かもしれない」のうち、動かして確かめて直したもの
def maybe(P, out):
    import concurrent.futures as cf
    d = out / 'maybe'; d.mkdir(exist_ok=True)
    for i in range(24):
        shutil.copy(P / 'assets' / 'sfx' / 'beep.wav', P / 'assets' / 'sfx' / f'many{i:02d}.wav')
    tlf = simple_tl(P, 'maybe')
    S = Server(tlf, d / 'server.log')
    try:
        S.ready()
        # /api/assets：音・動画の長さを測る ffprobe（同時に 4 本まで）。全部に長さが入る
        a = S.json('/api/assets')
        durs = [x.get('dur') for x in a.get('audio', []) if x['name'].startswith('many')]
        check(len(durs) == 24 and all(v and v > 0 for v in durs), f'かも /api/assets：音 24 本の長さが全部入る（{len(durs)} 本）')
        # 配っているファイルを、ほかのプロセスが「だれにも読ませない」で開いているとき：その返事だけが切れて、サーバーは落ちない（前は Node ごと落ちた）
        if os.name == 'nt':
            import ctypes
            f = P / 'assets' / 'images' / 'red.png'
            k32 = ctypes.windll.kernel32; k32.CreateFileW.restype = ctypes.c_void_p
            h = k32.CreateFileW(str(f), 0x80000000, 0, None, 3, 0x80, None)  # GENERIC_READ・共有なし・OPEN_EXISTING
            try:
                try:
                    code = S.call('/project/assets/images/red.png', timeout=10)[0]
                except Exception as e:
                    code = type(e).__name__
            finally:
                k32.CloseHandle(ctypes.c_void_p(h))
            time.sleep(0.5)
            alive = S.p.poll() is None
            try:
                after = S.call('/project/assets/images/red.png', timeout=10)[0]
            except Exception as e:
                after = type(e).__name__
            check(alive and after == 200, f'かも 読めないファイルを頼まれても、サーバーは落ちない（そのときの返事 {code}・サーバーが動いている {alive}・放したあと {after}）')
        # /api/tts：同じクリップの頼みが同時に 2 つ来ても、別の名前のテイクになる（VOICEVOX がこの PC で動いているときだけ）
        try:
            urllib.request.urlopen('http://127.0.0.1:50021/version', timeout=3).read()
            vv = True
        except Exception:
            vv = False
        if vv:
            req = {'clip': 'ttsdup', 'taken': [], 'request': {'engine': 'voicevox', 'text': 'テストです', 'voicevox': {'speaker': 3}}}
            with cf.ThreadPoolExecutor(2) as ex:
                rs = list(ex.map(lambda i: S.json('/api/tts', req, timeout=120), range(2)))
            ids = [r.get('id') for r in rs]
            check(all(r.get('ok') for r in rs) and len(set(ids)) == 2 and all((P / r['src']).is_file() for r in rs if r.get('src')), f'かも /api/tts：同時の 2 つが別の名前のテイクになる（{ids}）')
        else:
            print('SKIP かも /api/tts（VOICEVOX が動いていない）', flush=True)
    finally:
        S.quit()
    # 描画サーバーの返事が途中で切れたら、待ち続けずにエラーで終わる（server/pyrender.js の get）。偽の描画サーバー（頭だけ返して切る）で
    js = d / 'cut.js'
    js.write_text('''const path = require('path'), http = require('http');
const [root, project, tl, py] = process.argv.slice(2);
(async () => {
  const r = require(path.join(root, 'server', 'pyrender.js')).start({ project, timelineName: tl, local: { python: py }, log: () => { } });
  await r.waitReady();
  const real = r.st.port;
  const fake = http.createServer((req, res) => { res.writeHead(200, { 'Content-Type': 'image/jpeg', 'Content-Length': 100000 }); res.write(Buffer.alloc(1000)); setTimeout(() => res.destroy(), 200); });
  await new Promise(ok => fake.listen(0, '127.0.0.1', ok));
  r.st.port = fake.address().port;
  const t0 = Date.now();
  const got = await Promise.race([r.frame('0').then(() => 'resolved', e => 'rejected: ' + e.message), new Promise(ok => setTimeout(() => ok('hang'), 6000))]);
  r.st.port = real; fake.close();
  console.log(JSON.stringify({ got, ms: Date.now() - t0 }));
  r.close(); setTimeout(() => process.exit(0), 3000);
})().catch(e => { console.log(JSON.stringify({ error: String(e.stack || e) })); process.exit(1); });
''', encoding='utf-8', newline='\n')
    r = node(js, ROOT, P, tlf.name, PY, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith('{')]
    res = json.loads(lines[-1]) if lines else {'error': (r.stdout + r.stderr)[-300:]}
    check(str(res.get('got', '')).startswith('rejected'), f'かも 描画サーバーの返事が途中で切れたら、待ち続けずにエラーで終わる（{res}）')


# ---------------------------------------------------------------- 映像クリップ：どこから開いても、頭から順に読んだ絵と同じコマ
def seek(P, out):
    """映像クリップへ直に飛んで読んだ絵（プレビュー・📷・静止画・並列の書き出しの区間の頭）が、頭から順に読んだ絵と同じ。
    素材 30fps・24fps × 作品 30fps・60fps、速さ 1・1.5・0.8、素材の頭（in）あり。前は -ss を小数 4 桁で書いていて、3 コマに 1 つ素材の次のコマが出た"""
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24:duration=8', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '24',
                    str(P / 'assets' / 'videos' / 'v24.mp4')], check=True)

    def edit(fps, dur):
        def f(tl):
            tl.update(fps=fps, duration=dur * 4)
            tl['settings']['export'] = LOSSLESS
            specs = [('v1.mp4', 0.5, 1), ('v1.mp4', 1.0, 1.5), ('v24.mp4', 0.7, 1), ('v24.mp4', 2.0, 0.8)]
            track(tl, 'video')['clips'] = [{'id': f's{i}', 'type': 'video', 'src': ['assets/videos/' + s], 'start': i * dur, 'dur': dur, 'in': a, 'speed': sp} for i, (s, a, sp) in enumerate(specs)]
        return f
    t30, t60 = variant(P, 'seek30', edit(30, 1.5)), variant(P, 'seek60', edit(60, 0.75))
    code = r'''
import json, subprocess, sys
import numpy as np
from mittler.engine import Engine
res = {}
for tlf in sys.argv[1:3]:
    A = Engine(tlf); fps = A.fps; N = int(round(A.duration * fps))
    seq = [A.render(n / fps).copy() for n in range(N)]   # 頭から順に
    A.close()
    bad = []
    for n in range(N):                                  # 1 コマずつ、開き直して直に飛ぶ
        B = Engine(tlf); img = B.render(n / fps); B.close()
        if not (img == seq[n]).all():
            bad.append(n)
    # 素材そのものを頭から読んだ並び（-ss なし）の、決まった番号のコマと同じか（速さ 1 のクリップ 2 本）
    W, H = A.W, A.H
    head_bad = []
    for ci, (src, off) in enumerate((('v1.mp4', 0.5), (None, 0), ('v24.mp4', 0.7))):
        if src is None:
            continue
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', sys.argv[3] + '/' + src, '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps}',
                              '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
        per = N // 4
        for k in range(per):
            n = ci * per + k
            fi = int(round((k / fps + off) * fps))  # エンジンと同じ：クリップの頭から k / fps 秒 ＋ 素材の頭（in）→ コマ番号
            want = np.frombuffer(raw[fi * W * H * 3:(fi + 1) * W * H * 3], np.uint8).reshape(H, W, 3)
            if not (seq[n] == want).all():
                head_bad.append(n)
    res[str(fps)] = dict(n=N, bad=bad, head_bad=head_bad)
print(json.dumps(res))
'''
    r = subprocess.run([PY, '-X', 'utf8', '-B', '-c', code, str(t30), str(t60), (P / 'assets' / 'videos').as_posix()], cwd=ENGINE, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1200)
    if r.returncode:
        check(False, 'SEEK 描けなかった: ' + (r.stdout + r.stderr)[-500:])
        return
    res = json.loads(r.stdout.strip().splitlines()[-1])
    for fps, v in res.items():
        check(not v['bad'], f"SEEK 作品 {fps}fps：直に飛んだ絵＝頭から順に読んだ絵（{v['n']} コマ中、違うコマ {len(v['bad'])}：{v['bad'][:12]}）")
        check(not v['head_bad'], f"SEEK 作品 {fps}fps：速さ 1 のクリップの絵＝素材を頭から読んだ並びの、その番号のコマ（違うコマ {len(v['head_bad'])}：{v['head_bad'][:12]}）")
    md = {}
    for name, args in (('j1', ['--jobs', 1]), ('j2', ['--jobs', 2]), ('j5', ['--jobs', 5]), ('j7', ['--jobs', 7]), ('j16', ['--jobs', 16]),
                       ('p1', ['--jobs', 1, '--from', 1, '--to', 5]), ('p3', ['--jobs', 3, '--from', 1, '--to', 5])):
        r = engine('video', t30, out / f'seek_{name}.mp4', *args)
        if r.returncode:
            check(False, f'SEEK 書き出し（{name}）が失敗: ' + (r.stdout + r.stderr)[-300:])
            return
        md[name] = framemd5(out / f'seek_{name}.mp4')
    diff = {k: sum(a != b for a, b in zip(md['j1'], md[k])) for k in ('j2', 'j5', 'j7', 'j16')}
    check(len(md['j1']) == 180 and not any(diff.values()), f'SEEK 書き出しの絵が並列の数で変わらない（並列 1 と違うコマの数：{diff}）')
    check(md['p1'] == md['j1'][30:150] and md['p3'] == md['j1'][30:150], 'SEEK 一部の書き出し（1〜5 秒・並列 1 と 3）が、全体の書き出しの同じコマと同じ絵')


# ---------------------------------------------------------------- B16（小さいもの）
def b16(P, out):
    d = out / 'b16'; d.mkdir(exist_ok=True)
    # 3. tools\mittler.cmd・tools\cc.cmd：引数を全部渡す（前は 8 個まで）・Node の終了コードを返す（前はいつも 0）
    if os.name == 'nt':
        js = d / 'args.js'
        js.write_text("console.log(JSON.stringify(process.argv.slice(2))); process.exit(process.argv.includes('--fail') ? 7 : 0);\n", encoding='utf-8')
        args = list('abcdefghij') + ['--title', '試し の 名前', str(d / 'sp ace'), '--fps', '30', '--duration', '60', '--json']
        for c in ('mittler.cmd', 'cc.cmd'):
            r = subprocess.run(['cmd', '/c', str(ROOT / 'tools' / c), 'node', str(js)] + args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
            got = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None
            check(got == args and r.returncode == 0, f'B16-3 tools\\{c} が引数 {len(args)} 個を全部渡す（{len(got or [])} 個届いた）')
            r = subprocess.run(['cmd', '/c', str(ROOT / 'tools' / c), 'node', str(js), '--fail'], capture_output=True, timeout=60)
            check(r.returncode == 7, f'B16-3 tools\\{c} が Node の終了コードを返す（{r.returncode}）')
    # 7・8. 拡張（extension.js）を、vscode の代わりの偽物で：エラーの画面が HTML をエスケープする／同じタイムラインを同時に 2 つ開いてもサーバーは 1 つ
    tlf = simple_tl(P, 'b16')
    js = d / 'ext.js'
    js.write_text('''const path = require('path'), http = require('http'), Module = require('module');
const [root, tl, py] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
let provider = null;
const cfg = sec => ({ inspect: k => ({ defaultValue: '', globalValue: sec === 'mittler' && k === 'render.python' ? py : undefined }) });
const fake = { workspace: { isTrusted: true, getConfiguration: cfg },
  window: { registerCustomEditorProvider: (id, p) => { provider = provider || p; return { dispose() { } }; } },
  commands: { registerCommand: () => ({ dispose() { } }) },
  env: { asExternalUri: async u => u }, Uri: { parse: s => ({ scheme: 'http', authority: String(s).split('/')[2], toString: () => String(s) }), file: f => ({ fsPath: f }) }, ViewColumn: { Beside: 2 } };
const load = Module._load; Module._load = function (req) { return req === 'vscode' ? fake : load.apply(this, arguments); };
const ext = require(path.join(root, 'extension.js'));
const err = console.error; console.error = () => { };
ext.activate({ subscriptions: [] });
const panel = () => { const p = { webview: { options: null, html: '' }, dispose: null, onDidDispose(fn) { p.dispose = fn; } }; return p; };
const up = port => new Promise(ok => { const q = http.get({ host: '127.0.0.1', port, path: '/api/timeline', timeout: 2000 }, r => { r.resume(); ok(true); }); q.on('error', () => ok(false)); q.on('timeout', () => { q.destroy(); ok(false); }); });
(async () => {
  const out = {};
  const bad = panel(); await provider.resolveCustomTextEditor({ uri: { fsPath: 'C:\\\\nope_mittler\\\\x<img src=1 onerror=alert(1)>.cut.json' } }, bad);
  out.errHtml = bad.webview.html;
  const a = panel(), b = panel();
  await Promise.all([provider.resolveCustomTextEditor({ uri: { fsPath: tl } }, a), provider.resolveCustomTextEditor({ uri: { fsPath: tl } }, b)]);
  const port = h => (/127\\.0\\.0\\.1:(\\d+)/.exec(h) || [])[1];
  out.ports = [port(a.webview.html), port(b.webview.html)];
  out.up = await up(+out.ports[0]);
  a.dispose(); out.upAfterOne = await up(+out.ports[0]);
  b.dispose(); await sleep(1500); out.upAfterBoth = await up(+out.ports[0]);
  console.error = err;
  console.log(JSON.stringify(out)); setTimeout(() => process.exit(0), 24000).unref();
})().catch(e => { console.log(JSON.stringify({ error: String(e.stack || e) })); process.exit(1); });
''', encoding='utf-8', newline='\n')
    r = subprocess.run(node_cmd() + [str(js), str(ROOT), str(tlf), PY], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180, env=dict(os.environ, MITTLER_NO_REVEAL='1'))
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith('{')]
    res = json.loads(lines[-1]) if lines else {'error': (r.stdout + r.stderr)[-500:]}
    eh = res.get('errHtml', '')
    check('&lt;img src=1' in eh and '<img' not in eh, f"B16-7 拡張のエラーの画面が HTML をエスケープする（{eh[-110:] or res}）")
    ports = res.get('ports') or [None, None]
    check(ports[0] and ports[0] == ports[1], f'B16-8 同じタイムラインを同時に 2 つ開いても、サーバーは 1 つ（ポート {ports}）')
    check(res.get('up') and res.get('upAfterOne') and res.get('upAfterBoth') is False, f"B16-8 片方を閉じてもサーバーは残り、両方閉じたら止まる（{[res.get(k) for k in ('up', 'upAfterOne', 'upAfterBoth')]}）")
    # 1・5・6. サーバー：/project/%E0 は 400／仕上げの段に入ってからの「止める」は「できた」になる（.cancel を残さない）／再生用の動画づくりは止められる
    stub = d / 'stub'; stub.mkdir(exist_ok=True)
    (stub / 'sitecustomize.py').write_text('import sys, time\nif any(a.endswith("make_proxy.py") for a in getattr(sys, "orig_argv", [])):\n    time.sleep(60)\n', encoding='utf-8')

    def edit(tl):
        tl['duration'] = 1
        track(tl, 'video')['clips'] = [{'id': 'a', 'type': 'image', 'src': 'assets/images/red.png', 'start': 0, 'dur': 1}]
        track(tl, 'audio')['clips'] = [{'id': f'se{i}', 'type': 'audio', 'src': 'assets/sfx/beep.wav', 'start': (i % 20) * 0.02, 'dur': 0.4, 'in': 0, 'gain': -30} for i in range(250)]
    S = Server(variant(P, 'b16s', edit), d / 'server.log', env={'PYTHONPATH': str(stub)})
    try:
        S.ready()
        code = S.call('/project/%E0', token=False)[0]
        check(code == 400, f'B16-1 /project/%E0 は 400（{code}。前は 500）')

        def wait_state(states, sec=120):
            j = {}
            t0 = time.time()
            while time.time() - t0 < sec:
                j = S.json('/api/export')
                if j.get('state') in states:
                    break
                time.sleep(0.03)
            return j
        S.call('/api/export', {'name': 'b16mux', 'jobs': 2})
        j = wait_state(('muxing', 'done', 'error', 'cancelled'))
        hit = j.get('state') == 'muxing'
        S.call('/api/export/cancel', {})
        j = wait_state(('done', 'error', 'cancelled'))
        mp4, cancel = P / 'output' / 'b16mux.mp4', P / 'output' / 'b16mux.mp4.cancel'
        if hit:
            check(j.get('state') == 'done' and '間に合わず' in str(j.get('warning')) and mp4.is_file() and not cancel.exists(),
                  f"B16-5 仕上げの段での「止める」：書き出しは「できた」になり、そう知らせる・.cancel が残らない（{j.get('state')}・{str(j.get('warning'))[:30]}・.cancel {cancel.exists()}）")
        else:
            print(f"SKIP B16-5 仕上げの段に当てられなかった（{j.get('state')}）", flush=True)
        S.call('/api/export', {'name': 'b16proxy', 'jobs': 2, 'proxy': True})
        j = wait_state(('proxy', 'done', 'error', 'cancelled'))
        check(j.get('state') == 'proxy', f"B16-6 再生用の動画を作っている（{j.get('state')}）")
        t0 = time.time(); S.call('/api/export/cancel', {})
        j = wait_state(('done', 'error', 'cancelled'), 30)
        check(j.get('state') == 'done' and str(j.get('proxyError')) == JA['srv.proxyStopped'] and time.time() - t0 < 20, f"B16-6 再生用の動画づくりを止められる：書き出しは「できた」・再生用の動画は「止めた」（{j.get('state')}・{str(j.get('proxyError'))[:30]}・{time.time() - t0:.1f} 秒）")
    finally:
        S.quit()


def lib_reload(P, out):
    """2026-11-16 使ってみた知らせ 5：エフェクトが import した部品（effects/_lib/*.py）を直すと、動いている描画サーバーも新しい部品で描く
    （前は最初に読んだ版が残った）。作品の effects/ に __pycache__ を書かない"""
    lib = P / 'effects' / '_lib'
    lib.mkdir(parents=True, exist_ok=True)
    (lib / 'kitb.py').write_text('ADD = 10.0\n', encoding='utf-8')
    (P / 'effects' / 'libfx.py').write_text('"""試し：_lib の kitb.ADD だけ明るく"""\nimport os\nimport sys\n'
                                            'sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_lib"))\nimport kitb  # noqa: E402\nSTAGE = "v7"\n\n\n'
                                            'def apply(ctx, f, clip):\n    return f + kitb.ADD\n', encoding='utf-8')

    def edit(tl):
        tl['duration'] = 3
        tl.setdefault('settings', {})['cache'] = {'frames': False}  # ためた絵（fcache）を使わずに、読み直しだけを確かめる
        track(tl, 'video')['clips'] = [{'id': 'a', 'type': 'image', 'src': 'assets/images/red.png', 'start': 0, 'dur': 3}]
        tl['tracks'].insert(0, {'id': 't_fx', 'name': 'fx', 'kind': 'effect', 'clips': [{'id': 'lf', 'type': 'effect', 'effect': 'libfx', 'start': 0, 'dur': 3, 'params': {}}]})
    tlf = variant(P, 'libre', edit)
    R = Render(tlf)
    try:
        h = lambda t: hashlib.sha1(R.get(f'/frame?t={t}')).hexdigest()[:12]
        a1 = h(1)
        time.sleep(1.1)
        (lib / 'kitb.py').write_text('ADD = 90.0\n', encoding='utf-8')
        b1_, b2_ = h(1), h(2)
        check(a1 != b1_, f'LIB _lib の部品を直すと、動いている描画サーバーも新しい部品で描く（{a1} → {b1_}）')
        (lib / 'kitb.py').write_text('ADD = 10.0\n', encoding='utf-8')
        time.sleep(1.1)
        (lib / 'kitb.py').write_text('ADD = 10.0 \n', encoding='utf-8')  # 中身は同じ値・時刻と大きさが変わる
        check(h(1) == a1, 'LIB 戻すと前と同じ絵')
    finally:
        R.quit()
    r = subprocess.run([PY, '-X', 'utf8', '-m', 'mittler', 'stills', str(tlf), '--at', '1', '--out', str(out / 'libre')], cwd=ENGINE, capture_output=True, text=True, encoding='utf-8', errors='replace')
    check(r.returncode == 0 and not list((P / 'effects').rglob('__pycache__')), 'LIB 作品の effects/ に __pycache__ を書かない（-B なしで描いても）' + ('' if r.returncode == 0 else r.stderr[-300:]))


def u2net(P, out):
    """2026-11-16 使ってみた知らせ 3：rembg のモデルが U2NET_HOME の下の深い所（models/<名前>/<名前>.onnx）にあっても使う。無ければ False（取りに行くと知らせる）"""
    home = out / 'u2' / 'rembg'
    deep = home / 'models' / 'u2net_human_seg'
    deep.mkdir(parents=True, exist_ok=True)
    (deep / 'u2net_human_seg.onnx').write_bytes(b'x')
    code = 'import os, sys; from mittler import analyze as A; ok = A.u2net_home(); print(ok, os.environ["U2NET_HOME"])'
    r = subprocess.run([PY, '-X', 'utf8', '-B', '-c', code], cwd=ENGINE, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=dict(os.environ, U2NET_HOME=str(home), AV_AI_MODELS=str(out / 'u2')))
    check(r.stdout.strip() == f'True {deep}', f'U2NET 深い所のモデルを見つけて U2NET_HOME にする（{r.stdout.strip() or r.stderr[-200:]}）')
    empty = out / 'u2e'
    empty.mkdir(exist_ok=True)
    r = subprocess.run([PY, '-X', 'utf8', '-B', '-c', code], cwd=ENGINE, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=dict(os.environ, U2NET_HOME=str(empty), AV_AI_MODELS=str(out / 'u2e')))
    check(r.stdout.strip() == f'False {empty}', f'U2NET 無ければ False（{r.stdout.strip() or r.stderr[-200:]}）')


TESTS = {'B1': b1, 'B2': b2, 'B4': b4, 'B6': b6, 'B7': b7, 'B8': b8, 'B9': b9, 'B10': b10, 'B12': b12, 'B13': b13, 'B14': b14, 'B15': b15, 'B16': b16, 'SPRITE': sprite_float, 'MAYBE': maybe, 'SEEK': seek, 'LIB': lib_reload, 'U2NET': u2net}


def main():
    work = Path(sys.argv[sys.argv.index('--work') + 1]).resolve() if '--work' in sys.argv else None
    only = set(sys.argv[sys.argv.index('--only') + 1].upper().split(',')) if '--only' in sys.argv else None
    tmp = None
    if work is None:
        tmp = tempfile.mkdtemp(prefix='mittler_bugs_')
        work = Path(tmp)
    work.mkdir(parents=True, exist_ok=True)
    P = work / f'bugs{int(time.time()) % 100000}'
    out = work / (P.name + '_out')
    out.mkdir()
    try:
        make_project(P)
        for name, fn in TESTS.items():
            if only and name not in only:
                continue
            try:
                fn(P, out)
            except Exception as e:  # 1つ落ちても、ほかの項目は続ける
                import traceback
                check(False, f'{name} の確かめが例外で止まった: {e}\n{traceback.format_exc()[-800:]}')
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    print('FAIL ' + str(len(fails)) + ' 件' if fails else 'ALL OK')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
