"""見えない字・制御文字の検査（git で追跡しているファイルを全部、バイトで読む。Python の標準だけ。ブラウザもサーバーも要らない）。
  python -X utf8 tools/smoke_text.py              追跡しているファイル全部（作業ツリーの今の中身）
  python -X utf8 tools/smoke_text.py <ファイル>…   そのファイルだけ（わざと混ぜたファイルで、見つけるかを確かめるときなど）
  python -X utf8 tools/smoke_text.py --self-test   検査そのものの確かめ（下の種類を1つずつ混ぜたバイト列を、全部見つけるか）
見つけるもの：タブ（0x09）・LF（0x0A）・CRLF の CR 以外の 0x00〜0x1F と 0x7F、CRLF の一部でない単独の CR（0x0D）、
  ゼロ幅（U+200B〜U+200D・U+2060・U+FEFF。先頭の BOM も）、NBSP（U+00A0）、双方向の制御（U+202A〜U+202E・U+2066〜U+2069）、UTF-8 でないもの。
見つけたら「ファイル:行: 何か」を出して 1 で終わる（無ければ 0）。git が文字でないと見るファイル（attr の -text・バイナリ）は読まない。
なぜ：docs を直す一回きりのスクリプトで `\\v`（0x0B）・`\\a`（0x07）・`\\t` が化けて入った事故が3件あった。
Python の open() の文字モードは \\r を \\n に変えるので、化けた \\r を見落とす → 必ずバイトで読む。
このファイルにも見えない字を入れない（試しの見えない字は chr(コードポイント) で作る）。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAD_UNI = {0x200B: 'ゼロ幅スペース', 0x200C: 'ゼロ幅非接合子', 0x200D: 'ゼロ幅接合子', 0x2060: '単語結合子', 0xFEFF: 'BOM／ゼロ幅のNBSP', 0x00A0: 'NBSP',
           0x202A: '双方向の制御', 0x202B: '双方向の制御', 0x202C: '双方向の制御', 0x202D: '双方向の制御', 0x202E: '双方向の制御',
           0x2066: '双方向の制御', 0x2067: '双方向の制御', 0x2068: '双方向の制御', 0x2069: '双方向の制御'}


def scan(b):
    """バイト列 → [(行, 何か)]"""
    out = []
    line = lambda i: b.count(b'\n', 0, i) + 1
    for i, x in enumerate(b):
        if (x < 0x20 and x not in (0x09, 0x0A, 0x0D)) or x == 0x7F:
            out.append((line(i), f'制御文字 0x{x:02x}'))
        elif x == 0x0D and b[i + 1:i + 2] != b'\n':
            out.append((line(i), '単独の CR（0x0d）'))
    try:
        s = b.decode('utf-8')
    except UnicodeDecodeError as e:
        return out + [(line(e.start), f'UTF-8 でない（{e.reason}）')]
    for i, ch in enumerate(s):
        if ord(ch) in BAD_UNI:
            out.append((s.count('\n', 0, i) + 1, f'{BAD_UNI[ord(ch)]}（U+{ord(ch):04X}）'))
    return out


SKIP_DIRS = {'.git', '__pycache__', 'dist', 'work', '_trash', 'node_modules'}
BINARY = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp', '.mp4', '.webm', '.wav', '.mp3', '.zip', '.vsix', '.pyc', '.onnx', '.ttf', '.ttc', '.otf'}


def own_repo():
    """ROOT が git のリポジトリの根か（公開用の書き出し（git の無いフォルダ）では False）"""
    r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0 and Path(r.stdout.strip()).resolve() == ROOT.resolve()


def tracked():
    """git ls-files --eol → 文字のファイルの相対パス（-text・バイナリは除く）。git のリポジトリでなければ、フォルダをたどる（バイナリの拡張子・作業のフォルダは除く）"""
    if not own_repo():
        return sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*')
                      if p.is_file() and p.suffix.lower() not in BINARY and not SKIP_DIRS & set(p.relative_to(ROOT).parts[:-1]))
    r = subprocess.run(['git', '-c', 'core.quotepath=false', 'ls-files', '--eol', '-z'], cwd=ROOT, capture_output=True, check=True)
    out = []
    for ent in r.stdout.decode('utf-8').split('\0'):
        if not ent:
            continue
        info, _, path = ent.partition('\t')
        if 'i/-text' in info or 'attr/-text' in info:
            continue
        out.append(path)
    return out


def self_test():
    cases = {b'\x0b': '0x0b', b'\x07': '0x07', b'\x00': '0x00', b'\x1b': '0x1b', b'\x7f': '0x7f', b'a\rb': '単独の CR',
             chr(0x200B).encode(): 'ゼロ幅', chr(0xFEFF).encode(): 'BOM', chr(0xA0).encode(): 'NBSP', chr(0x202E).encode(): '双方向', b'\xff\xfe': 'UTF-8 でない'}
    bad = 0
    for raw, want in cases.items():
        got = scan(b'ok line\n' + raw + b'\n')
        ok = any(want in w for _, w in got) and all(ln == 2 for ln, _ in got)
        print(('OK   ' if ok else 'FAIL ') + f'{raw!r} → {got}')
        bad += not ok
    for good in (b'tab\tand LF\n', b'CRLF\r\n', '日本語・全角スペース　も よい\n'.encode()):
        got = scan(good)
        print(('OK   ' if not got else 'FAIL ') + f'{good!r} → {got}（見つからないこと）')
        bad += bool(got)
    return bad


def main():
    if '--self-test' in sys.argv:
        bad = self_test()
        print('self-test:', 'OK' if not bad else f'FAIL {bad}')
        sys.exit(1 if bad else 0)
    files = [a for a in sys.argv[1:] if not a.startswith('--')]
    paths = [(f, Path(f)) for f in files] if files else [(p, ROOT / p) for p in tracked()]
    n = found = 0
    for name, p in paths:
        if not p.is_file():  # 消したファイル（まだコミットしていない）など
            continue
        n += 1
        for ln, what in scan(p.read_bytes()):
            print(f'{name}:{ln}: {what}')
            found += 1
    print(f'smoke_text: {n} ファイルを読んだ・見つけたもの {found}')
    sys.exit(1 if found else 0)


if __name__ == '__main__':
    main()
