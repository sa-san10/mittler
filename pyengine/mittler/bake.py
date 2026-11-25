"""裏で先に描いてためる係（2026-11-16）：
手が止まっているあいだに、空いている CPU で再生位置から先のコマを描いて、作品の work/cache/frames/ にためる（fcache.py）。
ためた区間は、編集画面が ▶ でためた絵のまま流す・止めた絵もすぐ出る・書き出しは描かずに使う。

  python -m mittler bake <タイムライン> --from <秒> [--jobs N] [--chunk 24] [--stop <ファイル>]
- 範囲は --from の秒から終わりまで、そのあと頭から --from まで（再生位置の先を先に）。ためてある・ためない描き方のコマは飛ばす。
- 区間（chunk コマずつ）に分けて、並列 N 本の区間のプロセス（bake-part）で描く。どれも優先度「通常以下」（編集画面のプレビューと書き出しを邪魔しない）。
  並列の数は、言わなければ CPU の論理プロセッサの数の半分から 2 引いた数（1 以上）と、空いているメモリ（master.render_jobs と同じ考え）の小さいほう。
- Blender の 3D のクリップがあれば、区間に分ける前に範囲のコマをまとめて描く（書き出しの prepare と同じ）。
- --stop のファイルができたら止める（区間のプロセスはコマの区切りで止まる）。編集画面のサーバー（server.js の baker）が、タイムラインが変わった・書き出しを始めた・
  閉じたときに作る。進み具合は `BAKE できた数 全部` を 1 秒ごとに出す。終わったら `BAKE_DONE`。
- `<--stop>.pause` のファイルがあるあいだは、区間のプロセス（とその子の ffmpeg）を一時停止する（新しい区間も始めない）。消えたら続ける（描きかけのコマから）。
  サーバーが、編集画面でシーク・操作しているあいだ作る（シークした瞬間にためるのを止めて、シークの描画を速くするため）。
  Blender の 3D をまとめて描く段（prepare）は止めない。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from . import fcache
from .engine import Engine

CHUNK = 24
LOW = getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)


def default_jobs():
    from .master import JOB_GB, KEEP_GB, mem_avail_gb
    j = max(1, (os.cpu_count() or 4) // 2 - 2)
    av = mem_avail_gb()
    if av is not None:
        j = min(j, max(1, int((av - KEEP_GB) / JOB_GB)))
    return j


def _lower_self():
    """このプロセスを優先度「通常以下」に（区間のプロセスと、その子の ffmpeg も同じになる）"""
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
        except (OSError, AttributeError):
            pass


def bake(tl, t_from, jobs=None, chunk=CHUNK, stop=None):
    _lower_self()
    stop = Path(stop) if stop else None
    stopped = lambda: stop is not None and stop.exists()  # noqa: E731
    eng = Engine(tl)
    fps = eng.fps
    nall = int(round(eng.duration * fps))
    n0 = max(0, min(nall, int(round(float(t_from) * fps))))
    order = list(range(n0, nall)) + list(range(0, n0))
    todo = []
    for n in order:  # ためてある・ためない描き方のコマは飛ばす（鍵は 1 コマ 1 ミリ秒ほど）
        k, ok = fcache.has(eng, n / fps)
        if k and not ok:
            todo.append(n)
    total = len(todo)
    print(f'BAKE 0 {total}', flush=True)
    if not total or stopped():
        print('BAKE_DONE', flush=True)
        return 0
    # Blender の 3D：区間に分ける前に、描くコマをまとめて描いてためる（書き出しの prepare と同じ。止める印は --stop）
    from .__main__ import prepare
    try:
        prepare(eng, min(todo), max(todo) + 1, 1, stop or Path(os.devnull + '.never'))
    except SystemExit:
        print('BAKE_DONE', flush=True)
        return 0
    eng.close()
    # 続いているコマを chunk コマずつの区間に（順番は再生位置の先から）
    chunks, cur = [], []
    for n in todo:
        if cur and (n != cur[-1] + 1 or len(cur) >= chunk):
            chunks.append(cur)
            cur = []
        cur.append(n)
    if cur:
        chunks.append(cur)
    jobs = max(1, int(jobs or default_jobs()))
    here = Path(__file__).resolve().parent.parent
    from .procs import suspend_tree
    pause = Path(str(stop) + '.pause') if stop else None
    procs, i, last, paused = [], 0, 0.0, False

    def set_paused(on):
        for p in procs:
            if p.poll() is None:
                try:
                    suspend_tree(p, on)
                except OSError:
                    pass
    try:
        while (i < len(chunks) or any(p.poll() is None for p in procs)) and not stopped():
            want = pause is not None and pause.exists()
            if want != paused:  # シークのあいだ止める・終わったら続ける
                set_paused(want)
                paused = want
                print('BAKE_PAUSED' if want else 'BAKE_RESUMED', flush=True)
            while not paused and i < len(chunks) and sum(p.poll() is None for p in procs) < jobs:
                c = chunks[i]
                cmd = [sys.executable, '-X', 'utf8', '-B', '-m', 'mittler', 'bake-part', str(tl), '--first', str(c[0]), '--last', str(c[-1])] + \
                      (['--stop', str(stop)] if stop else [])
                procs.append(subprocess.Popen(cmd, cwd=str(here), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=LOW))
                i += 1
            if time.time() - last > 1.0:
                last = time.time()
                done = sum(len(chunks[j]) for j, p in enumerate(procs) if p.poll() is not None)
                print(f'BAKE {done} {total}', flush=True)
            time.sleep(0.1)
    finally:
        if paused:  # 止めた区間のプロセスは、続けてから止まってもらう（一時停止のままでは止める印を見られない）
            set_paused(False)
        if stopped():
            from .procs import kill_tree
            t_end = time.time() + 15  # 区間のプロセスはコマの区切りで止まる。待っても止まらなければ止める
            while any(p.poll() is None for p in procs) and time.time() < t_end:
                time.sleep(0.2)
            for p in procs:
                if p.poll() is None:
                    kill_tree(p)
    print(f'BAKE {sum(len(chunks[j]) for j, p in enumerate(procs) if p.poll() is not None)} {total}', flush=True)
    print('BAKE_DONE', flush=True)
    return total


def bake_part(tl, first, last, stop=None):
    """コマ first〜last（どちらも入れる）を描いてためる。ためてあるコマは飛ばす。--stop ができたらコマの区切りで止まる"""
    stop = Path(stop) if stop else None
    eng = Engine(tl)
    try:
        for n in range(int(first), int(last) + 1):
            if stop is not None and stop.exists():
                break
            t = n / eng.fps
            k, ok = fcache.has(eng, t)
            if not k or ok:
                continue
            img = eng.render(t)
            fcache.put(eng, t, img)
    finally:
        eng.close()
