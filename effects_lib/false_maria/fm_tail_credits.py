"""暗転とクレジット（偽マリアのエフェクト集）：曲の終わり（params.song_end＝クリップの頭）から、黒へフェード 〜0.5 秒、黒 〜1.0、クレジットのフェードイン 〜1.8、
表示 〜4.8、フェードアウト 〜5.6、黒（クリップの終わりまで）。クレジットは黒地に白〜淡いピンクの細い欧文を字間を空けて中央に、うすいピンクのにじみを後ろに。
params：credits（行の並び）, font（書体のファイル。無ければ Segoe UI Light → BIZ UDゴシック）, fade_black, cr_in0, cr_in1, cr_out0, cr_out1（song_end からの秒）。
元は偽マリアMV（effects_lib/maria/tail_credits.py）。部品にするときに、クリップの頭を song_end にし（クリップを動かすとついていく）、クレジットの既定を一般的な 1 行にした。
マスター書き出し（ctx.scale）：字の大きさ・行の間・にじみは画面の高さ（H / 1080）で決めているので、4K のキャンバスではそのまま 2 倍の大きさで細かく描ける。"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

STAGE = 'post'
DOC_EN = """Fade to black and credits (False Maria effects): from the end of the song (params.song_end = the clip start): fade to black by 0.5 s, black until 1.0,
credits fade in until 1.8, hold until 4.8, fade out until 5.6, then black until the clip ends. Thin, widely spaced white-to-pale-pink lettering in the center
with a soft pink glow behind it.
params: credits (lines), font (font file; default Segoe UI Light, then BIZ UDGothic), fade_black, cr_in0, cr_in1, cr_out0, cr_out1 (seconds after song_end).
From the False Maria MV."""
META = {'label': '暗転とクレジット（偽マリア）', 'label_en': 'Fade to black and credits (False Maria)', 'window': {'start': 'song_end'}, 'time_params': ['song_end'],
        'scale_aware': True, 'params': {'credits': {'type': 'lines'}},
        'defaults': {'credits': ['THANK YOU FOR WATCHING']}, 'dur': 6.0}

FR = 'C:/Windows/Fonts/BIZ-UDGothicR.ttc'


def apply(ctx, f, clip):
    p = dict(clip.get('params', {}))
    p.setdefault('song_end', clip.get('start', 0.0))
    black, cr = level(ctx.t, p)
    if black >= 1.0:  # 暗転のあと：黒にクレジットだけ
        if cr > 0:
            cache = ctx.cache.setdefault('fm_tail_credits', {})
            key = (repr(p.get('credits')), repr(p.get('font')), ctx.W, ctx.H)
            if key not in cache:
                cache[key] = credit_image(ctx.W, ctx.H, p)
            return (cache[key] * cr).astype(np.uint8)
        return np.zeros((ctx.H, ctx.W, 3), np.uint8)
    if black > 0:
        f = (f.astype(np.float32) * (1 - black)).astype(np.uint8)
    return f


def level(t, p):
    """(黒の強さ 0〜1, クレジットの濃さ 0〜1)"""
    d = t - p['song_end']
    FADE_BLACK, CR_IN0, CR_IN1 = p.get('fade_black', 0.5), p.get('cr_in0', 1.0), p.get('cr_in1', 1.8)
    CR_OUT0, CR_OUT1 = p.get('cr_out0', 4.8), p.get('cr_out1', 5.6)
    if d < 0:
        return 0.0, 0.0
    k = min(d / FADE_BLACK, 1.0)
    black = k * k * (3 - 2 * k)
    if d < CR_IN0 or d >= CR_OUT1:
        c = 0.0
    elif d < CR_IN1:
        c = (d - CR_IN0) / (CR_IN1 - CR_IN0)
    elif d < CR_OUT0:
        c = 1.0
    else:
        c = 1 - (d - CR_OUT0) / (CR_OUT1 - CR_OUT0)
    return black, c * c * (3 - 2 * c)


def credit_image(W, H, p):
    """黒地のクレジットの画面（float32、0〜255）"""
    credits = p.get('credits') or []
    s = H / 1080
    try:
        font = ImageFont.truetype(p.get('font') or 'C:/Windows/Fonts/segoeuil.ttf', int(46 * s))
    except OSError:
        font = ImageFont.truetype(FR, int(42 * s))
    track, lh = 0.12 * 46 * s, int(92 * s)
    cols = [(255, 240, 246), (255, 222, 236), (255, 222, 236)]
    al = Image.new('L', (W, H), 0)
    rgb = Image.new('RGB', (W, H), (0, 0, 0))
    da, dr = ImageDraw.Draw(al), ImageDraw.Draw(rgb)
    y0 = H / 2 - lh * (len(credits) - 1) / 2
    for i, line in enumerate(credits):
        tw = sum(da.textlength(ch, font=font) for ch in line) + track * (len(line) - 1)
        x, y = (W - tw) / 2, y0 + lh * i
        for ch in line:
            da.text((x, y), ch, font=font, fill=255, anchor='lm')
            dr.text((x, y), ch, font=font, fill=cols[i % len(cols)], anchor='lm')
            x += da.textlength(ch, font=font) + track
    a = np.asarray(al, np.float32)[..., None] / 255
    glow = np.asarray(al.filter(ImageFilter.GaussianBlur(16 * s)), np.float32)[..., None] / 255
    out = np.array([255, 120, 190], np.float32) * np.clip(glow * 0.55, 0, 1)
    return out * (1 - a) + np.asarray(rgb, np.float32) * a
