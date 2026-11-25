"""作品の .claude/settings.json のフック（話しかけるたびに編集画面の今をそえる）を、今の書き方にそろえる。標準ライブラリだけ。
  python tools/fix_hooks.py <作品のフォルダ か works のフォルダ> [...] [--dry-run] [--absolute]
今の書き方（既定。2026-11-13 パッケージ化〜）：Mittler の場所を書かない形。python が環境変数 CLAUDE_PROJECT_DIR（無ければ今のフォルダ）から上にたどって、
作品の状態フォルダの中継 .mittler/hook.py（前からの作品は .claude-cut/hook.py）を探して動かす（中継は、拡張が作品を開くたびに書く。server/project_env.js）。
→ 作品を別の PC に写しても、配布版の拡張を更新して置き場が変わっても、書き直さなくてよい。まだ編集画面で開いていない作品では何もしない（話しかけるのは止めない）。
  （新しい作品のひな形と同じ文字列：tools/new_project.js の HOOK_CMD。同じことを tools/smoke_package.py が確かめる）
--absolute：前の書き方（この Mittler の tools/mittler_state.py の絶対パス）に書き直す（開発版で、中継を使わずに直接動かしたいとき）。
古い名前のフック（tools/cc_state.py。2026-11-12 に Mittler に改名する前の作品）・前の絶対パスのフックも、ここで今の書き方に書き直す
（書き直さなくても動く：リポジトリが同じ場所にある限り、cc_state.py・mittler_state.py の絶対パスはそのまま動く）。
- works のフォルダを渡すと、その下の作品（*.cut.json があるフォルダ）を全部。
- フックが無ければ足す（.claude/settings.json が無ければ作る）。ほかの設定はそのまま。作品の AGENTS.md・CLAUDE.md は直さない（手順は docs/インストールガイド.md の 15）。
- 作品が git なら、直す前に git add -A（いまの状態をステージ。git diff で見え、git restore で戻せる）。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / 'mittler_state.py'
CMD_ABS = f'python "{HOOK.as_posix()}"'
CMD = ("python -c \"import os,runpy,pathlib as P;d=P.Path(os.environ.get('CLAUDE_PROJECT_DIR') or '.').resolve();"
       "h=[x/s/'hook.py' for x in [d,*d.parents] for s in ('.mittler','.claude-cut') if (x/s/'hook.py').is_file()];"
       "h and runpy.run_path(str(h[0]),run_name='__main__')\"")
IS_HOOK = re.compile(r"mittler_state\.py|cc_state\.py|\.mittler'.{0,80}hook\.py")  # cc_state.py＝古い名前の互換（前の名前のフックも、このフックとして見つける）


def works_in(p):
    if any(p.glob('*.cut.json')):
        return [p]
    return sorted(d for d in p.iterdir() if d.is_dir() and any(d.glob('*.cut.json')))


def fix(proj, dry, cmd):
    sp = proj / '.claude' / 'settings.json'
    st = json.loads(sp.read_text(encoding='utf-8')) if sp.exists() else {}
    groups = st.setdefault('hooks', {}).setdefault('UserPromptSubmit', [])
    before, found = [], False
    for g in groups:
        for h in g.get('hooks', []):
            if IS_HOOK.search(str(h.get('command', ''))):
                before.append(h['command']); h['command'] = cmd; found = True
    if not found:
        groups.append({'hooks': [{'type': 'command', 'command': cmd}]})
    if before == [cmd]:
        print(f'{proj.name}: そのまま（{cmd}）'); return
    print(f'{proj.name}: {" / ".join(before) or "（フックなし）"} → {cmd}')
    if dry:
        return
    if (proj / '.git').exists():
        subprocess.run(['git', '-C', str(proj), 'add', '-A'], check=False)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(st, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--dry-run', action='store_true', help='直さずに、どう直すかだけ出す')
    ap.add_argument('--absolute', action='store_true', help='前の書き方（この Mittler の mittler_state.py の絶対パス）にする')
    a = ap.parse_args()
    projs = [w for p in a.paths for w in works_in(Path(p).resolve())]
    if not projs:
        sys.exit('作品（*.cut.json があるフォルダ）が見つからない')
    for p in projs:
        fix(p, a.dry_run, CMD_ABS if a.absolute else CMD)


if __name__ == '__main__':
    main()
