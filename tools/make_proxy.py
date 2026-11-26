"""再生用の動画（プロキシ）を作る：小さな MP4（映像 H.264・音 AAC・頭に目次＝faststart）。
  python make_proxy.py <*.cut.json> <元の動画.mp4> [--height 540] [--format mp4|webm]
→ <プロジェクト>/work/proxy/<元の名前>.mp4 を作り、タイムラインの preview.proxy をそれに書きかえる（--no-timeline なら作るだけ）。
--height は短い辺の長さ（縦長の作品は幅がこの長さ）。
前は WebM（VP9＋Opus）だったが、作者の PC の VS Code では WebM がどれも開けず（error 4）、MP4（H.264＋AAC）は再生できたので、既定を MP4 にした（2026-11-26）。
MP4 が再生できない環境のために --format webm も残す。
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('timeline')
ap.add_argument('src')
ap.add_argument('--height', type=int, default=540)
ap.add_argument('--format', choices=['mp4', 'webm'], default='mp4', help='mp4（H.264＋AAC。既定）か webm（VP9＋Opus）')
ap.add_argument('--no-timeline', action='store_true', help='タイムラインは書きかえない（編集画面が preview.proxy を入れる）。結果を JSON で出す')
a = ap.parse_args()
tlf = Path(a.timeline).resolve()
src = Path(a.src).resolve()
out = tlf.parent / 'work' / 'proxy' / (src.stem + '.' + a.format)
out.parent.mkdir(parents=True, exist_ok=True)
tmp = out.with_name(out.stem + f'.part{os.getpid()}' + out.suffix)  # 拡張子はそのまま（ffmpeg が形を決める）
t0 = time.time()
# 短い辺を --height に（横長は高さ、縦長は幅。前は高さだけで、縦長の作品は幅 304 の小さな絵になった）
scale = f"scale='if(gt(iw,ih),-2,{a.height})':'if(gt(iw,ih),{a.height},-2)'"
if a.format == 'mp4':
    codec = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-pix_fmt', 'yuv420p', '-g', '24', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart']
else:
    codec = ['-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '36', '-deadline', 'realtime', '-cpu-used', '8', '-row-mt', '1', '-g', '24', '-c:a', 'libopus', '-b:a', '128k']
cmd = ['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-vf', scale] + codec + [str(tmp)]
# 書き終わるまでは別の名前に書き、できてから置きかえる（作っている途中のファイルを編集画面が読むと error 4 になり、読み直さなかった。2026-11-26）
try:
    subprocess.run(cmd, check=True)
    os.replace(tmp, out)
finally:
    if tmp.exists():
        tmp.unlink()
if a.no_timeline:
    print(json.dumps({'ok': True, 'proxy': out.relative_to(tlf.parent).as_posix(), 'bytes': out.stat().st_size, 'sec': round(time.time() - t0, 1)}, ensure_ascii=False))
    raise SystemExit(0)
tl = json.loads(tlf.read_text(encoding='utf-8'))
tl.setdefault('preview', {})['proxy'] = out.relative_to(tlf.parent).as_posix()
tl['preview']['proxy_note'] = f'{src.name} から作った再生用の動画（{a.format.upper()}）'
tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print('proxy', out, f'{out.stat().st_size / 1e6:.1f} MB', f'{time.time() - t0:.0f}s')
