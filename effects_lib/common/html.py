"""HTML のレイヤー（2026-11-18）。作品の中の HTML のページ（Canvas・CSS・SVG・three.js など）を、ヘッドレスの Chromium でコマごとに描いて、このトラックの位置に重ねる。
ページは作品の `html/<名前>/index.html`（ひな形は Mittler の templates/html/：文字の動き kinetic・three.js の光る粒 particles3d・three.js の立体の形 shapes3d。
「作品に入れる」で作品の html/ に写る。three.js は html/vendor/ にある）。ページは mittler.onFrame((t, args) => …) で、クリップの頭から t 秒の絵を描く
（時刻と乱数は Mittler が決める。前のコマを覚えない。背景は透明）。書き方は docs/エフェクトの書き方.md の「HTML のレイヤー」。
params：page（ページのファイル）, args（ページに渡す JSON。mittler.args）, seed（乱数の種）, blend（over・add・screen）, opacity
描く python に Playwright（と Chromium）が要る。無い PC では理由つきで止まる。くわしくは pyengine/mittler/htmllayer.py。"""
from mittler import htmllayer

STAGE = 'v7'
DOC_EN = """HTML layer. Renders an HTML page in the project (Canvas, CSS, SVG, three.js, ...) with headless Chromium for each frame and composites it at this track's position.
The page is the project's `html/<name>/index.html` (templates in Mittler's templates/html/: kinetic text, three.js glowing particles particles3d, three.js 3D shapes shapes3d;
"Add to project" copies them to the project's html/, with three.js in html/vendor/). The page draws the picture at t seconds from the clip start in mittler.onFrame((t, args) => ...)
(Mittler controls time and random numbers; don't keep state from earlier frames; the background is transparent). How to write pages: "HTML layer" in docs/エフェクトの書き方.md.
params: page (the page file), args (JSON passed to the page as mittler.args), seed (random seed), blend (over / add / screen), opacity
The rendering python needs Playwright (and Chromium). Without it, rendering stops with the reason. Details: pyengine/mittler/htmllayer.py."""
META = {
    'label': 'HTML のレイヤー', 'label_en': 'HTML layer', 'window': {'clip': True}, 'scale_aware': True, 'html': True,
    'params': {
        'page': {'type': 'text'}, 'args': {'type': 'json'},
        'seed': {'type': 'int', 'min': 0, 'max': 2147483647},
        'blend': {'type': 'choice', 'choices': ['over', 'add', 'screen']},
        'opacity': {'type': 'number', 'min': 0, 'max': 1, 'step': 0.01},
    },
    # 編集画面で置くときの値と長さ（ページはひな形の文字の動き。「作品に入れる」で作品の html/kinetic/ に写る）
    'defaults': {'page': 'html/kinetic/index.html', 'args': {'text': 'Mittler'}, 'seed': 1, 'blend': 'over', 'opacity': 1.0},
    'dur': 4,
}


def apply(ctx, f, clip):
    return htmllayer.layer(ctx, f, clip)
