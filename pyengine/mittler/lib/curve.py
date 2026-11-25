"""生成画像に後からトーンカーブをかける（元の画像は変更しない）。

カーブの設定は JSON（既定は作品フォルダの カーブ.json）：
  {"mode": "luma", "points": [[0, 0], [64, 76], [128, 150], [192, 210], [255, 255]]}
  - points: 入力→出力（0〜255）の制御点。点の間は行き過ぎない滑らかな曲線（単調な3次補間）でつなぐ。
  - mode: "luma" は明るさ（Y）だけにかけて色味を保つ。"rgb" は R・G・B それぞれにかける（中間調の彩度も少し上がる）。

使い方:
  python curve.py <入力フォルダ or 画像> <出力フォルダ> [--curve カーブ.json] [--compare 比較画像.jpg]
  入力フォルダなら中の *.png を全部処理し、同じファイル名で出力フォルダへ書く（既にあれば上書き）。
  --compare を付けると、1枚目の画像の補正前・補正後とカーブのグラフを並べた確認用画像も書く。
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
DEFAULT_CURVE = HERE.parent.parent / 'カーブ.json'


def monotone_lut(points):
    """制御点を通る単調な3次補間（Fritsch-Carlson）で 256 段の対応表を作る。"""
    pts = sorted((float(x), float(y)) for x, y in points)
    x = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    h = np.diff(x)
    delta = np.diff(y) / h
    m = np.empty_like(y)
    m[0], m[-1] = delta[0], delta[-1]
    m[1:-1] = (delta[:-1] + delta[1:]) / 2
    for i, d in enumerate(delta):
        if d == 0:
            m[i] = m[i + 1] = 0
        else:
            a, b = m[i] / d, m[i + 1] / d
            s = a * a + b * b
            if s > 9:
                t = 3 / np.sqrt(s)
                m[i], m[i + 1] = t * a * d, t * b * d
    xs = np.arange(256, dtype=float)
    k = np.clip(np.searchsorted(x, xs, side='right') - 1, 0, len(h) - 1)
    t = (xs - x[k]) / h[k]
    h00, h10 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t
    h01, h11 = -2 * t**3 + 3 * t**2, t**3 - t**2
    out = h00 * y[k] + h10 * h[k] * m[k] + h01 * y[k + 1] + h11 * h[k] * m[k + 1]
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def apply(im, lut, mode):
    im = im.convert('RGB')
    if mode == 'rgb':
        return Image.fromarray(lut[np.asarray(im)])
    ycc = np.asarray(im.convert('YCbCr')).copy()
    ycc[..., 0] = lut[ycc[..., 0]]
    return Image.fromarray(ycc, 'YCbCr').convert('RGB')


def curve_plot(lut, points, size=420):
    g = Image.new('RGB', (size, size), (250, 250, 250))
    d = ImageDraw.Draw(g)
    s = (size - 1) / 255
    for v in (64, 128, 192):
        d.line([(v * s, 0), (v * s, size)], fill=(220, 220, 220))
        d.line([(0, size - 1 - v * s), (size, size - 1 - v * s)], fill=(220, 220, 220))
    d.line([(0, size - 1), (size - 1, 0)], fill=(180, 180, 180), width=2)
    d.line([(i * s, size - 1 - int(lut[i]) * s) for i in range(256)], fill=(220, 40, 120), width=4)
    for px, py in points:
        cx, cy = px * s, size - 1 - py * s
        d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], outline=(40, 40, 40), width=3)
    return g


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('out')
    ap.add_argument('--curve', default=str(DEFAULT_CURVE))
    ap.add_argument('--compare')
    a = ap.parse_args()

    cfg = json.loads(Path(a.curve).read_text(encoding='utf-8'))
    lut = monotone_lut(cfg['points'])
    mode = cfg.get('mode', 'luma')
    src = Path(a.src)
    files = sorted(src.glob('*.png')) if src.is_dir() else [src]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in files:
        apply(Image.open(f), lut, mode).save(out / f.name, optimize=True)
        print(f.name)
    if a.compare and files:
        before = Image.open(files[0]).convert('RGB')
        after = apply(before, lut, mode)
        w = 900
        hgt = round(before.height * w / before.width)
        sheet = Image.new('RGB', (w * 2 + 460, max(hgt, 440)), (255, 255, 255))
        sheet.paste(before.resize((w, hgt)), (0, 0))
        sheet.paste(after.resize((w, hgt)), (w, 0))
        sheet.paste(curve_plot(lut, cfg['points']), (w * 2 + 20, 10))
        sheet.save(a.compare, quality=90)
    print('mode', mode, 'mid 128 ->', int(lut[128]), '| 32 ->', int(lut[32]), '| 224 ->', int(lut[224]))


if __name__ == '__main__':
    main()
