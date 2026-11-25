"""HTML のレイヤーの書体の確かめ（描画の python。Playwright と Chromium が要る）：
ページの @font-face の書体が、新しいブラウザの最初のコマから効いているか（下地 pyengine/mittler/html_runtime.js が、描いている間に書体の読み込みが始まったら、読み終わってから描き直す。2026-11-22）。
新しいプロセスで t=0 だけを描いた絵と、同じプロセスで t=1 → t=0 の順に描いた t=0 の絵（2 回目なので書体は読み終わっている）が同じになること。
書体は Windows の C:\\Windows\\Fonts\\comic.ttf を試しの作品に写して使う（作品は一時フォルダに作って消す）。
  <描画の python> -X utf8 tools\\smoke_html_font.py
"""

import hashlib, json, shutil, subprocess, sys
from pathlib import Path
import tempfile
eng = Path(__file__).resolve().parents[1] / 'pyengine'
d = Path(tempfile.mkdtemp(prefix='mittler_htmlfont_'))
(d / 'html' / 'ft').mkdir(parents=True); (d / 'assets' / 'fonts').mkdir(parents=True); (d / 'effects').mkdir(); shutil.copy(eng.parent / 'effects_lib' / 'common' / 'html.py', d / 'effects' / 'html.py')
shutil.copy(r'C:\Windows\Fonts\comic.ttf', d / 'assets' / 'fonts' / 'test.ttf')
(d / 'html' / 'ft' / 'index.html').write_text("""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{font-family:'TestFace';src:url('../../assets/fonts/test.ttf')}
html,body{margin:0;background:transparent}</style></head><body><canvas id="c"></canvas><script>
const c=document.getElementById('c'),g=c.getContext('2d');c.width=mittler.W;c.height=mittler.H;
mittler.onFrame(t=>{g.clearRect(0,0,c.width,c.height);g.fillStyle='#fff';g.font='72px TestFace, serif';g.fillText('Hello Mittler',20,120);});
</script></body></html>""", encoding='utf-8')
tl = {'format': 'mittler/py1', 'engine': 'mittler', 'name': 'ft', 'width': 480, 'height': 200, 'fps': 10, 'duration': 2.0, 'root': '.', 'meta': [],
      'tracks': [{'id': 'fx', 'name': 'fx', 'kind': 'effect', 'clips': [{'id': 'h', 'type': 'effect', 'effect': 'html', 'start': 0, 'dur': 2, 'params': {'page': 'html/ft/index.html'}}]}]}
f = d / 'ft.cut.json'; f.write_text(json.dumps(tl), encoding='utf-8')
def stills(at, out):
    r = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m', 'mittler', 'stills', str(f), '--at', at, '--out', str(d / out)], cwd=eng, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode: print(r.stdout[-800:], r.stderr[-1500:])
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest()[:12] for p in sorted((d / out).glob('*.png'))}
a = stills('0', 'first'); b = stills('1,0', 'second')
print('first only :', a); print('after warm :', b)
k = 'still_000.000.png'
ok = bool(a.get(k)) and a.get(k) == b.get(k) and b.get(k) == b.get('still_001.000.png')
shutil.rmtree(d, ignore_errors=True)
print(('OK   ' if ok else 'FAIL ') + '最初のコマから @font-face の書体で描く（最初だけ描いた t=0・温まってからの t=0・t=1 が同じ）')
print('smoke_html_font: ' + ('OK' if ok else 'FAIL'))
sys.exit(0 if ok else 1)

