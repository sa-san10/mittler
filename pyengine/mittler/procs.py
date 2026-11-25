"""子のプロセスを、その子孫ごと止める（書き出しの「止める」・🏆 マスター書き出しの「止める」が使う）。

Windows はまず taskkill /T。断られたら（作者の PC のサービス用のアカウントでは、自分のプロセスにも 5 秒ほど待ってから
「Access denied」になった。2026-11-13）、子孫を数えて1つずつ TerminateProcess。起動用の python.exe（venv）だけを止めても、
本体の python と孫の ffmpeg は残るため。親子の一覧は WMI でなく Toolhelp で取る（そのアカウントでは WMI も Access denied だった）。
サーバーの側は server/server.js の killTree（一覧は server/proctree.ps1）が同じことをする。
"""
import os
import subprocess


def _parents():
    """{pid: 親の pid}（Windows の Toolhelp）。取れなければ空"""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('pid', wintypes.DWORD), ('heapId', ctypes.c_void_p),
                    ('moduleId', wintypes.DWORD), ('threads', wintypes.DWORD), ('ppid', wintypes.DWORD), ('basePri', ctypes.c_long),
                    ('flags', wintypes.DWORD), ('exe', ctypes.c_wchar * 260)]
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k.CreateToolhelp32Snapshot(2, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    out = {}
    e = PE()
    e.dwSize = ctypes.sizeof(PE)
    try:
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out[e.pid] = e.ppid
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return out


def _descendants(pid):
    try:
        parent = _parents()
    except Exception:
        parent = {}
    out = [pid]
    grew = True
    while grew:
        grew = False
        for c, p in parent.items():
            if p in out and c not in out:
                out.append(c)
                grew = True
    return out


def kill_tree(p):
    """p（subprocess.Popen）を子孫ごと止める。待ちはしない（呼ぶ側が p.wait()）"""
    if p.poll() is not None:
        return
    if os.name != 'nt':
        p.kill()
        return
    if subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)], capture_output=True).returncode == 0:
        return
    for pid in _descendants(p.pid):
        try:
            os.kill(pid, 9)  # Windows では TerminateProcess
        except OSError:
            pass


def suspend_tree(p, on):
    """p（subprocess.Popen）を子孫ごと一時停止する（on=True）・続ける（on=False）。Windows だけ（NtSuspendProcess・NtResumeProcess）。
    裏で先に描く係（bake.py）が、編集画面でシークしているあいだ CPU を空けるのに使う（裏で描いていると
    シークの描画がとても遅くなるので、シークした瞬間にためるのを止める）。描きかけのコマはそのまま止まり、続けるとそこから"""
    if os.name != 'nt' or p.poll() is not None:
        return 0
    import ctypes
    nt, k = ctypes.WinDLL('ntdll'), ctypes.WinDLL('kernel32')
    k.OpenProcess.restype = ctypes.c_void_p
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    fn = nt.NtSuspendProcess if on else nt.NtResumeProcess
    fn.argtypes = [ctypes.c_void_p]
    n = 0
    for pid in _descendants(p.pid):
        h = k.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
        if h:
            try:
                fn(h)
                n += 1
            finally:
                k.CloseHandle(h)
    return n
