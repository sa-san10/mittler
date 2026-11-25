"""簡易字幕：アニメーションなし。クリップのあいだ、指定の位置に指定のフォントで文字を出すだけ（紙芝居の字幕、MV の下の歌詞など）。
字幕のトラック（kind: subtitle）のクリップにかかる。クリップ：{text, style:{…}}。style はタイムラインの settings.subtitle（既定）に重ねる。
style：font（root からの相対パス）, size, color [r,g,b], stroke（縁の太さ px）, stroke_color, stroke_alpha（0〜1）,
       shadow（影のずれ px）, shadow_color, shadow_alpha, x, y（基準の点。既定は画面の下の真ん中）, align（center / left / right）,
       valign（bottom / middle / top：基準の点が文字のかたまりのどこか）, line_gap（行の間 px）, spacing（字の間 px）
初期値（既定）は 作者の紙芝居の作品の字幕（ASS：NotoSerifJP 56px、下から 65px、白っぽい字に半透明の紺の縁と影）に合わせてある。"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

STAGE = 'post'
DOC_EN = """Simple subtitles, no animation: shows text at a set position in a set font for the length of the clip (picture-story subtitles, lyrics at the bottom of an MV, etc.).
Applies to clips on subtitle tracks (kind: subtitle). Clip: {text, style:{…}}. style is layered over the timeline's settings.subtitle (defaults).
style: font (path relative to root), size, color [r,g,b], stroke (outline width px), stroke_color, stroke_alpha (0–1),
       shadow (shadow offset px), shadow_color, shadow_alpha, x, y (anchor point; default is the bottom center), align (center / left / right),
       valign (bottom / middle / top: where the anchor is on the text block), line_gap (px between lines), spacing (px between characters)"""
META = {'label': '字幕', 'label_en': 'Subtitles', 'window': {'clip': True}, 'params': {}}

DEFAULT = {'font': 'assets/fonts/NotoSerifJP-Regular.ttf', 'size': 56, 'color': [245, 243, 234], 'stroke': 2, 'stroke_color': [24, 32, 48],
           'stroke_alpha': 0.44, 'shadow': 2, 'shadow_color': [24, 32, 48], 'shadow_alpha': 0.25, 'x': None, 'y': None,
           'align': 'center', 'valign': 'bottom', 'line_gap': 8, 'spacing': 1, 'margin_v': 65}


# 字のファイルが無いとき（新しい作品で assets/fonts/ が空など）に使う、Windows に入っている日本語の字
FALLBACK_FONTS = ['C:/Windows/Fonts/YuGothM.ttc', 'C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/msgothic.ttc']


def font_path(ctx, rel):
    p = ctx.root / rel
    if p.is_file():
        return str(p)
    for f in FALLBACK_FONTS:
        if Path(f).is_file():
            return f
    return str(p)  # 見つからない：そのまま（エラーで場所がわかる）


def style_of(ctx, clip):
    st = dict(DEFAULT)
    st.update(ctx.settings.get('subtitle') or {})
    st.update(clip.get('style') or {})
    if st['x'] is None:
        st['x'] = ctx.W / 2
    if st['y'] is None:
        st['y'] = ctx.H - st['margin_v']
    return st


def apply(ctx, f, clip):
    text = clip.get('text', '')
    if not text:
        return f
    st = style_of(ctx, clip)
    cache = ctx.cache.setdefault('subtitle', {})
    key = (text, repr(sorted(st.items())))
    if key not in cache:
        cache[key] = render(ctx, text, st)
    img, ox, oy = cache[key]
    H, W = f.shape[:2]
    x0, y0 = int(round(st['x'] + ox)), int(round(st['y'] + oy))
    h, w = img.shape[:2]
    xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + w, W), min(y0 + h, H)
    if xa >= xb or ya >= yb:
        return f
    sub = img[ya - y0:yb - y0, xa - x0:xb - x0].astype(np.float32)
    a = sub[..., 3:4] / 255.0
    out = f.copy()
    reg = out[ya:yb, xa:xb].astype(np.float32)
    out[ya:yb, xa:xb] = np.clip(reg * (1 - a) + sub[..., :3] * a, 0, 255).astype(np.uint8)
    return out


def render(ctx, text, st):
    """字幕の絵（RGBA）と、基準の点からの左上のずれ"""
    font = ImageFont.truetype(font_path(ctx, st['font']), int(st['size']))
    lines = text.split('\n')
    dummy = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    sp, sw = st['spacing'], int(st['stroke'])

    def line_w(s):
        return sum(dummy.textlength(ch, font=font) for ch in s) + sp * max(len(s) - 1, 0)
    asc, desc = font.getmetrics()
    lh = asc + desc
    widths = [line_w(s) for s in lines]
    bw = int(max(widths) + 2 * sw + st['shadow'] + 8)
    bh = int(lh * len(lines) + st['line_gap'] * (len(lines) - 1) + 2 * sw + st['shadow'] + 8)
    pad = sw + 4

    def draw_layer(color, alpha, stroke, dx=0, dy=0):
        lay = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        for i, s in enumerate(lines):
            if st['align'] == 'left':
                x = pad
            elif st['align'] == 'right':
                x = bw - pad - widths[i] - st['shadow']
            else:
                x = (bw - st['shadow'] - widths[i]) / 2
            y = pad + i * (lh + st['line_gap'])
            for ch in s:
                d.text((x + dx, y + dy), ch, font=font, fill=tuple(color) + (int(255 * alpha),),
                       stroke_width=stroke, stroke_fill=tuple(color) + (int(255 * alpha),))
                x += d.textlength(ch, font=font) + sp
        return lay
    out = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
    if st['shadow']:
        out.alpha_composite(draw_layer(st['shadow_color'], st['shadow_alpha'], sw, st['shadow'], st['shadow']))
    if sw:
        out.alpha_composite(draw_layer(st['stroke_color'], st['stroke_alpha'], sw))
    out.alpha_composite(draw_layer(st['color'], 1.0, 0))
    ox = {'left': -pad, 'right': -(bw - pad - st['shadow'])}.get(st['align'], -(bw - st['shadow']) / 2)
    oy = {'top': -pad, 'middle': -bh / 2}.get(st['valign'], -(bh - pad - st['shadow']))
    return np.asarray(out), ox, oy
