"""字幕を ASS にして ffmpeg の ass フィルタ（libass）で焼く（settings.subtitle.renderer = "ass"。2026-10-21、作者の紙芝居の作品の完全再現で足した）。
dialogue-video（紙芝居・掛け合い動画）の render_dialogue.write_ass と同じ ASS を、タイムラインの字幕クリップから作る。
- 字幕のトラック（kind: subtitle）のクリップ：{text, start, dur, style?}。ASS の時刻は 1/100 秒（round(秒 × 100)、元の timestamp と同じ）。
- 見た目：settings.subtitle.ass（下の DEFAULT_ASS と同じキー。無い項目は既定＝dialogue-video の字幕）。
  クリップの style（編集画面の字幕の欄：size・color・stroke・stroke_color・stroke_alpha・shadow・shadow_color・shadow_alpha・margin_v・align・valign）
  があれば、そのクリップだけ別の Style にする。
- 字のファイル：settings.subtitle.ass.fontsdir（root からの相対。ここの字を libass が使う。字幕の字だけを置く）。
- 焼き方：静止画・プレビューは1コマずつ ffmpeg に通す（burn）。書き出しはエンコードの ffmpeg の -vf にまとめて入れる（vf。元の build_video と同じ）。
  どちらも `setpts=PTS+<コマ番号>,ass=…,setpts=PTS-STARTPTS`（そのコマの時刻で libass が描く）。ffmpeg は root を作業フォルダにして動かす。
- PlayResX・PlayResY はタイムラインの大きさ（eng.W0・eng.H0）。マスター書き出しで s 倍のキャンバス（機能追加案03 v2）でも、libass が字の大きさ・余白を s 倍にして描く。
"""
import hashlib
import subprocess

DEFAULT_ASS = {
    'fontname': 'Noto Serif JP', 'fontsize': 56, 'primary': '&H00EAF3F5', 'secondary': '&H00EAF3F5', 'outline_colour': '&H90302018',
    'back_colour': '&HC0302018', 'bold': 0, 'italic': 0, 'underline': 0, 'strikeout': 0, 'scale_x': 100, 'scale_y': 100, 'spacing': 1,
    'angle': 0, 'border_style': 1, 'outline': 2, 'shadow': 2, 'alignment': 2, 'margin_l': 100, 'margin_r': 100, 'margin_v': 65, 'encoding': 1,
    'wrap_style': 2, 'scaled_border_and_shadow': 'yes', 'fontsdir': 'assets/fonts', 'style_name': 'Dialogue'}
STYLE_KEYS = ['fontname', 'fontsize', 'primary', 'secondary', 'outline_colour', 'back_colour', 'bold', 'italic', 'underline', 'strikeout',
              'scale_x', 'scale_y', 'spacing', 'angle', 'border_style', 'outline', 'shadow', 'alignment', 'margin_l', 'margin_r', 'margin_v', 'encoding']


def ass_text(text):
    # libass override tags and escapes must never come from source dialogue.（render_dialogue.ass_text と同じ）
    return text.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}').replace('\n', '\\N')


def timestamp(seconds):
    ticks = round(seconds * 100)
    return f'{ticks // 360000}:{ticks // 6000 % 60:02}:{ticks // 100 % 60:02}.{ticks % 100:02}'


def _colour(rgb, alpha=1.0):
    r, g, b = [int(x) for x in list(rgb)[:3]]
    a = max(0, min(255, int(round((1 - float(alpha)) * 255))))
    return f'&H{a:02X}{b:02X}{g:02X}{r:02X}'


def _from_clip_style(st):
    """編集画面の字幕の欄（Pillow の字幕と同じキー）→ ASS の Style のキー"""
    out = {}
    if 'size' in st:
        out['fontsize'] = st['size']
    if 'color' in st:
        out['primary'] = out['secondary'] = _colour(st['color'])
    if 'stroke' in st:
        out['outline'] = st['stroke']
    if 'stroke_color' in st or 'stroke_alpha' in st:
        out['outline_colour'] = _colour(st.get('stroke_color', [24, 32, 48]), st.get('stroke_alpha', 1.0))
    if 'shadow' in st:
        out['shadow'] = st['shadow']
    if 'shadow_color' in st or 'shadow_alpha' in st:
        out['back_colour'] = _colour(st.get('shadow_color', [24, 32, 48]), st.get('shadow_alpha', 1.0))
    if 'margin_v' in st:
        out['margin_v'] = st['margin_v']
    if 'align' in st or 'valign' in st:
        h = {'left': 1, 'center': 2, 'right': 3}.get(st.get('align', 'center'), 2)
        v = {'bottom': 0, 'middle': 3, 'top': 6}.get(st.get('valign', 'bottom'), 0)
        out['alignment'] = h + v
    out.update(st.get('ass') or {})  # ASS のキーをそのまま
    return out


def build(eng):
    """タイムラインの字幕クリップ → ASS の文（render_dialogue.write_ass と同じ形）"""
    base = dict(DEFAULT_ASS)
    base.update(((eng.settings.get('subtitle') or {}).get('ass')) or {})
    styles, names, events = [], {}, []

    def style_line(name, s):
        return 'Style: ' + ','.join([name] + [str(s[k]) for k in STYLE_KEYS])
    styles.append(style_line(base['style_name'], base))
    clips = sorted(eng.ass_clips, key=lambda c: c['start'])
    for c in clips:
        name = base['style_name']
        if c.get('style'):
            s = dict(base)
            s.update(_from_clip_style(c['style']))
            key = tuple(str(s[k]) for k in STYLE_KEYS)
            if key not in names:
                names[key] = f"{base['style_name']}_{len(names) + 1}"
                styles.append(style_line(names[key], s))
            name = names[key]
        text = c.get('text', '')
        if not text:
            continue
        events.append(f'Dialogue: 0,{timestamp(c["start"])},{timestamp(c["start"] + c["dur"])},{name},,0,0,0,,{ass_text(text)}')
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {eng.W0}
PlayResY: {eng.H0}
WrapStyle: {base['wrap_style']}
ScaledBorderAndShadow: {base['scaled_border_and_shadow']}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
''' + '\n'.join(styles) + '''

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    return header + '\n'.join(events) + '\n', base['fontsdir']


def ensure(eng):
    """ASS のファイルを root/work/ass/ に書く（中身が同じなら書き直さない）。(作業フォルダ, ASS の相対パス, 字のフォルダの相対パス)"""
    got = eng.cache.get('ass_file')
    text, fontsdir = build(eng)
    h = hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]
    if got and got[0] == h:
        return got[1]
    d = eng.root / 'work' / 'ass'
    d.mkdir(parents=True, exist_ok=True)
    p = d / f'sub_{h}.ass'
    if not p.exists():
        p.write_text(text, encoding='utf-8')  # 元の write_ass と同じ書き方（Windows では改行が CRLF）
    out = (eng.root, f'work/ass/{p.name}', fontsdir)
    eng.cache['ass_file'] = (h, out)
    return out


def vf(eng, n0, step=1):
    """書き出しの区間（頭のコマ番号 n0）のエンコードの ffmpeg に入れる -vf（root を作業フォルダにして動かすこと）。
    step＞1（ドラフトでコマを間引く）のときは、入力の1コマが step コマぶんなので、ずらす量も step で割る"""
    _, rel, fontsdir = ensure(eng)
    off = f'{int(n0)}' if step == 1 else f'{int(n0)}/{int(step)}'
    return f'setpts=PTS+{off},ass={rel}:fontsdir={fontsdir},setpts=PTS-STARTPTS'


def burn(eng, f, n):
    """1コマ（uint8, H×W×3、コマ番号 n）に字幕を焼く。そのコマにかかる字幕が無ければそのまま"""
    t = n / eng.fps
    if not any(c['start'] - 0.02 <= t < c['start'] + c['dur'] + 0.02 for c in eng.ass_clips):
        return f
    cwd, _, _ = ensure(eng)
    cmd = ['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{eng.W}x{eng.H}', '-r', str(eng.fps), '-i', '-',
           '-vf', vf(eng, n), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    r = subprocess.run(cmd, input=f.tobytes(), capture_output=True, cwd=str(cwd))
    if r.returncode or len(r.stdout) != f.size:
        from .i18n import t  # 失敗の文の頭の言葉（環境変数 MITTLER_LANG）。描く絵には関わらない
        raise RuntimeError(t('py.ass.fail', err=r.stderr.decode('utf-8', 'replace')[-800:]))
    import numpy as np
    return np.frombuffer(r.stdout, np.uint8).reshape(f.shape).copy()
