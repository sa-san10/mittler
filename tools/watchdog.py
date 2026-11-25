"""重い処理の見張り（重い処理は必要なら回してよい。その代わり、常に独立に処理時間・GPU・メモリ・CPU を見張り、
異常（想定を超えた長時間の全力・スワップの爆増）があれば止める仕組みを立て続ける）。Python の標準だけ。

  python tools/watchdog.py --expect-min 10 [--log work/watch.log] -- <コマンド> [引数…]   コマンドを起動して見張る（終わりの番号はコマンドのもの）
  python tools/watchdog.py --expect-min 10 --pid <PID> [--on-stop "<コマンド>"]            動いているプロセスを見張る
  python tools/watchdog.py --expect-min 10 --on-stop "python .mittler/api.py . export-cancel"   書き出しなど（サーバーの子）を見張る：異常なら止める命令を流す

見るもの（--interval 秒ごと）：経過時間・CPU・メモリ・コミット（スワップ込みの使用量）・GPU（nvidia-smi があれば：使用率・VRAM）。
止めるとき（異常。理由を出して、番号 3 で終わる）：
- 経過時間が --max-min（既定は --expect-min の 2 倍、最低 +5 分）を超えた（想定を超えた長さ）
- メモリの使用率が --mem-pct（既定 95）以上のまま 30 秒
- コミット（スワップ込み）が上限の --commit-pct（既定 95）以上、またはコミットが物理メモリを超えた状態で 1 分に --swap-gb-min（既定 4）GB 以上ふえた（スワップの爆増）
- --progress <ファイル> を付けたとき、そのファイルが --stall-min（既定 10）分のあいだ変わらず、CPU か GPU が全力（進まないまま回っている）
止め方：--pid・起動したコマンドは子孫ごと止める（taskkill /T、断られたら子孫を数えて 1 つずつ）。--on-stop があれば流す。
GPU の VRAM がいっぱいなのは知らせるだけ（Blender などは普通に使い切る）。
記録：--log に 1 行 1 JSON（時刻・値・知らせ）。最後に 1 行の JSON（{"ok", "reason", "minutes", "peak"}）を標準出力に。
"""
import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pyengine'))
GB = 1 << 30


class MEMSTAT(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong), ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong), ('ullTotalVirtual', ctypes.c_ulonglong),
                ('ullAvailVirtual', ctypes.c_ulonglong), ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]


def memory():
    """{mem_pct, phys_gb, commit_gb, commit_limit_gb}（Windows はコミット、ほかはスワップの使用量をコミットに足す）"""
    if os.name == 'nt':
        m = MEMSTAT(); m.dwLength = ctypes.sizeof(MEMSTAT)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return {'mem_pct': m.dwMemoryLoad, 'phys_gb': m.ullTotalPhys / GB,
                'commit_gb': (m.ullTotalPageFile - m.ullAvailPageFile) / GB, 'commit_limit_gb': m.ullTotalPageFile / GB}
    info = {}
    for ln in Path('/proc/meminfo').read_text().splitlines():
        k, v = ln.split(':', 1); info[k] = int(v.split()[0]) * 1024
    used = info['MemTotal'] - info.get('MemAvailable', info['MemFree'])
    swap = info.get('SwapTotal', 0) - info.get('SwapFree', 0)
    return {'mem_pct': round(100 * used / info['MemTotal']), 'phys_gb': info['MemTotal'] / GB,
            'commit_gb': (used + swap) / GB, 'commit_limit_gb': (info['MemTotal'] + info.get('SwapTotal', 0)) / GB}


class Cpu:
    """CPU の使用率（前に見たときからの割合）"""
    def __init__(self):
        self.prev = self._times()

    def _times(self):
        if os.name == 'nt':
            i, k, u = (ctypes.c_ulonglong() for _ in range(3))
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
            return i.value, k.value + u.value  # kernel は idle を含む
        v = [int(x) for x in Path('/proc/stat').read_text().split('\n', 1)[0].split()[1:]]
        return v[3] + v[4], sum(v)

    def pct(self):
        idle, total = self._times()
        di, dt = idle - self.prev[0], total - self.prev[1]
        self.prev = (idle, total)
        return round(100 * (1 - di / dt)) if dt > 0 else 0


def gpu():
    """[{util, vram_pct}]（nvidia-smi が無ければ空）"""
    exe = shutil.which('nvidia-smi')
    if not exe:
        return []
    try:
        r = subprocess.run([exe, '--query-gpu=utilization.gpu,memory.used,memory.total', '--format=csv,noheader,nounits'],
                           capture_output=True, text=True, timeout=10)
        out = []
        for ln in r.stdout.strip().splitlines():
            u, used, tot = (float(x) for x in ln.split(','))
            out.append({'util': u, 'vram_pct': round(100 * used / tot) if tot else 0})
        return out
    except Exception:
        return []


def alive(pid):
    if os.name == 'nt':
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0); return True
    except OSError:
        return False


def kill_pid_tree(pid):
    if os.name != 'nt':
        try:
            os.kill(pid, 9)
        except OSError:
            pass
        return
    if subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True).returncode == 0:
        return
    from mittler.procs import _descendants
    for p in _descendants(pid):
        try:
            os.kill(p, 9)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser(description='重い処理の見張り（異常なら止める）')
    ap.add_argument('--expect-min', type=float, required=True, help='想定の長さ（分）')
    ap.add_argument('--max-min', type=float, default=None, help='これを超えたら止める（既定 max(想定×2, 想定+5)）')
    ap.add_argument('--pid', type=int, default=None)
    ap.add_argument('--on-stop', default='', help='異常で止めるときに流すコマンド（シェル）')
    ap.add_argument('--interval', type=float, default=5)
    ap.add_argument('--mem-pct', type=float, default=95)
    ap.add_argument('--commit-pct', type=float, default=95)
    ap.add_argument('--swap-gb-min', type=float, default=4)
    ap.add_argument('--progress', default='', help='進むと書きかわるファイル（出力・ログ）')
    ap.add_argument('--stall-min', type=float, default=10)
    ap.add_argument('--log', default='')
    ap.add_argument('cmd', nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ['--'] else a.cmd
    if not cmd and a.pid is None and not a.on_stop:
        ap.error('-- <コマンド>、--pid、--on-stop のどれかが要る')
    limit = a.max_min if a.max_min is not None else max(a.expect_min * 2, a.expect_min + 5)
    proc = subprocess.Popen(cmd) if cmd else None
    pid = proc.pid if proc else a.pid
    logf = open(a.log, 'a', encoding='utf-8') if a.log else None
    cpu = Cpu()
    t0 = time.time()
    hist = []  # (時刻, commit_gb)
    mem_hi_since = None
    peak = {'cpu': 0, 'mem_pct': 0, 'commit_gb': 0, 'gpu': 0, 'vram_pct': 0}
    warned = set()
    reason = None

    def note(kind, msg, **kw):
        rec = dict(t=round((time.time() - t0) / 60, 2), kind=kind, msg=msg, **kw)
        print(json.dumps(rec, ensure_ascii=False), file=sys.stderr, flush=True)
        if logf:
            logf.write(json.dumps(rec, ensure_ascii=False) + '\n'); logf.flush()

    note('start', f'見張り開始：想定 {a.expect_min} 分・上限 {limit} 分', pid=pid, cmd=cmd)
    while True:
        if proc is not None and proc.poll() is not None:
            break
        if proc is None and pid is not None and not alive(pid):
            break
        time.sleep(a.interval)
        now = time.time(); mins = (now - t0) / 60
        m = memory(); c = cpu.pct(); g = gpu()
        gu = max((x['util'] for x in g), default=0); gv = max((x['vram_pct'] for x in g), default=0)
        for k, v in (('cpu', c), ('mem_pct', m['mem_pct']), ('commit_gb', round(m['commit_gb'], 1)), ('gpu', gu), ('vram_pct', gv)):
            peak[k] = max(peak[k], v)
        hist.append((now, m['commit_gb'])); hist = [h for h in hist if now - h[0] <= 60]
        rise = m['commit_gb'] - hist[0][1] if now - hist[0][0] >= 30 else 0
        if logf:
            logf.write(json.dumps({'t': round(mins, 2), 'cpu': c, 'mem_pct': m['mem_pct'], 'commit_gb': round(m['commit_gb'], 1),
                                   'gpu': gu, 'vram_pct': gv}) + '\n'); logf.flush()
        if mins > a.expect_min and 'over' not in warned:
            warned.add('over'); note('warn', f'想定の {a.expect_min} 分を超えた（上限 {limit} 分で止める）')
        if gv >= 98 and 'vram' not in warned:
            warned.add('vram'); note('warn', f'VRAM がほぼいっぱい（{gv}%）。止めはしない')
        mem_hi_since = (mem_hi_since or now) if m['mem_pct'] >= a.mem_pct else None
        full = c >= 95 or gu >= 95
        if mins > limit:
            reason = f'想定を超えた長さ（{mins:.2f} 分 > 上限 {limit} 分）'
        elif mem_hi_since and now - mem_hi_since >= 30:
            reason = f'メモリの使用率が {m["mem_pct"]}%（{a.mem_pct}% 以上が 30 秒）'
        elif m['commit_gb'] >= m['commit_limit_gb'] * a.commit_pct / 100:
            reason = f'コミット（スワップ込み）が上限に近い（{m["commit_gb"]:.1f} / {m["commit_limit_gb"]:.1f} GB）'
        elif m['commit_gb'] > m['phys_gb'] and rise * 60 / max(30, now - hist[0][0]) >= a.swap_gb_min:
            reason = f'スワップの爆増（コミットが物理メモリを超えて 1 分に {rise:.1f} GB ふえた）'
        elif a.progress and full:
            try:
                idle_min = (now - os.path.getmtime(a.progress)) / 60
            except OSError:
                idle_min = mins
            if idle_min >= a.stall_min:
                reason = f'進まないまま全力（{a.progress} が {idle_min:.1f} 分変わらない・CPU {c}% GPU {gu}%）'
        if reason:
            break
    code = 0
    if reason:
        note('stop', '異常で止める：' + reason, cpu=peak['cpu'], mem_pct=peak['mem_pct'])
        if pid is not None:
            kill_pid_tree(pid)
        if a.on_stop:
            subprocess.run(a.on_stop, shell=True, timeout=120)
        code = 3
    elif proc is not None:
        code = proc.returncode
    note('end', '終わり' if not reason else '止めた', code=code)
    print(json.dumps({'ok': not reason, 'reason': reason, 'minutes': round((time.time() - t0) / 60, 2), 'peak': peak, 'code': code}, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
