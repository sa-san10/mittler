"""Gemini の鍵が入っているかを確かめる（値は出さない。文字数と形だけ）。
  python check-gemini-key.py
資格情報マネージャーの汎用の資格情報 ps:GEMINI_API_KEY（Mittler・gemini_tts と同じ読み方）と、環境変数 GEMINI_API_KEY を見る。
"""
import ctypes
import os
from ctypes import wintypes

NAME = 'ps:GEMINI_API_KEY'


class FILETIME(ctypes.Structure):
    _fields_ = [('lo', wintypes.DWORD), ('hi', wintypes.DWORD)]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                ('LastWritten', FILETIME), ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


def read(target):
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    adv.CredReadW.restype = wintypes.BOOL
    p = ctypes.POINTER(CREDENTIALW)()
    if not adv.CredReadW(target, 1, 0, ctypes.byref(p)):
        return None
    try:
        blob = ctypes.string_at(p.contents.CredentialBlob, p.contents.CredentialBlobSize)
    finally:
        adv.CredFree(p)
    return blob.decode('utf-16-le') if len(blob) >= 2 and blob[1:2] == b'\x00' else blob.decode('utf-8')


def describe(v):
    s = v.strip()
    return f'{len(s)} 文字' + ('（前後に空白・改行あり。読むときは取り除く）' if s != v else '')


v = read(NAME)
print(f'資格情報マネージャー {NAME}：' + ('入っていない' if v is None else '入っている。' + describe(v)))
e = os.environ.get('GEMINI_API_KEY')
print('環境変数 GEMINI_API_KEY：' + ('無い' if not e else 'ある（こちらが先に使われる）。' + describe(e)))
