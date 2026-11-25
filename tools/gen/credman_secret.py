# Mittler：Windows の資格情報マネージャーから鍵を読む（作者のワークスペースの道具の写し、2026-10-21。2026-11-13 に一般の名前 credman_secret.py に。中身はそのまま。鍵の値は読むだけで表示しない）
"""Read secrets stored with PowerShell SecretManagement (CredMan vault) from Python.

Secrets live in Windows Credential Manager as generic credentials named
"ps:<name>" (SecretManagement.JustinGrote.CredMan). No extra packages needed.

    from credman_secret import get_secret
    key = get_secret("GEMINI_API_KEY")
"""

import ctypes
import os
from ctypes import wintypes

_CRED_TYPE_GENERIC = 1
_ERROR_NOT_FOUND = 1168


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _read_credman(target):
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    pcred = ctypes.POINTER(_CREDENTIALW)()
    if not advapi32.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        err = ctypes.get_last_error()
        if err == _ERROR_NOT_FOUND:
            return None
        raise OSError(err, f"CredReadW failed for {target!r}")
    try:
        cred = pcred.contents
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
    finally:
        advapi32.CredFree(pcred)
    # The CredMan vault stores strings as UTF-8; other tools often use UTF-16.
    if len(blob) >= 2 and blob[1:2] == b"\x00":
        return blob.decode("utf-16-le")
    return blob.decode("utf-8")


def get_secret(name, env_first=True):
    """Return the secret, or None if it is not set.

    An environment variable of the same name wins when env_first is True,
    so a one-off override still works without touching the vault.
    """
    if env_first:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    value = _read_credman(f"ps:{name}")
    return value.strip() if value else None


def _clipboard_text():
    """Windows clipboard text (CF_UNICODETEXT), or None."""
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32.GetClipboardData.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not u32.OpenClipboard(None):
        return None
    try:
        h = u32.GetClipboardData(13)  # CF_UNICODETEXT
        if not h:
            return None
        p = k32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def _clear_clipboard():
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    if u32.OpenClipboard(None):
        u32.EmptyClipboard()
        u32.CloseClipboard()


def set_secret(name, value):
    """Write the generic credential "ps:<name>" (UTF-16, the same as cmdkey). The value is never printed."""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL
    data = value.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    c = _CREDENTIALW()
    c.Type = _CRED_TYPE_GENERIC
    c.TargetName = f"ps:{name}"
    c.CredentialBlobSize = len(data)
    c.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    c.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    c.UserName = name
    if not advapi32.CredWriteW(ctypes.byref(c), 0):
        raise OSError(ctypes.get_last_error(), "CredWriteW failed")


if __name__ == "__main__":
    import sys

    # Mittler（2026-11-15）：鍵をコピーしてから流すと、クリップボードから資格情報マネージャーに入れる（貼り付けの入力欄が要らない。値は出さない）
    #   python credman_secret.py --set-from-clipboard OPENAI_API_KEY
    if sys.argv[1:2] == ["--set-from-clipboard"] and len(sys.argv) == 3:
        n = sys.argv[2]
        v = (_clipboard_text() or "").strip()
        if not v or any(ch.isspace() for ch in v) or len(v) < 20:
            sys.exit("クリップボードに鍵が無いみたい（鍵だけをコピーしてから、もう一度流して）。何も変えていない")
        set_secret(n, v)
        ok = _read_credman(f"ps:{n}")
        _clear_clipboard()
        hint = "（sk- で始まる形）" if n == "OPENAI_API_KEY" and v.startswith("sk-") else ""
        print(f"{n}: 入れた（{len(v)} 文字{hint}。クリップボードは空にした）" if ok and ok.strip() == v else f"{n}: 書いたけど読み直せない")
        sys.exit(0)
    for n in sys.argv[1:]:
        raw = _read_credman(f"ps:{n}")
        state = 'set' if get_secret(n) else ('empty (the name exists but the value is empty: use --set-from-clipboard)' if raw is not None else 'missing')
        print(f"{n}: {state}")
