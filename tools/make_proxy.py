"""再生用の動画（プロキシ）を作る：VS Code の中でも再生できる WebM（映像 VP9・音 Opus）。
VS Code（Electron）は特許の都合で H.264 の映像と AAC の音を再生できない（MP4 のままだと絵も音も出ない）。
  python make_proxy.py <*.cut.json> <元の動画.mp4> [--height 540]
→ <プロジェクト>/work/proxy/<元の名前>.webm を作り、タイムラインの preview.proxy をそれに書きかえる（--no-timeline なら作るだけ）。
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
ap.add_argument('--no-timeline', action='store_true', help='タイムラインは書きかえない（編集画面が preview.proxy を入れる）。結果を JSON で出す')
a = ap.parse_args()
tlf = Path(a.timeline).resolve()
src = Path(a.src).resolve()
out = tlf.parent / 'work' / 'proxy' / (src.stem + '.webm')
out.parent.mkdir(parents=True, exist_ok=True)
tmp = out.with_name(out.stem + f'.part{os.getpid()}.webm')  # 拡張子 .webm のまま（ffmpeg が形を決める）
t0 = time.time()
cmd = ['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-vf', f'scale=-2:{a.height}', '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '36',
       '-deadline', 'realtime', '-cpu-used', '8', '-row-mt', '1', '-g', '24', '-c:a', 'libopus', '-b:a', '128k', str(tmp)]
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
tl['preview']['proxy_note'] = f'{src.name} から作った WebM（VS Code でも再生できる VP9＋Opus）'
tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print('proxy', out, f'{out.stat().st_size / 1e6:.1f} MB', f'{time.time() - t0:.0f}s')
