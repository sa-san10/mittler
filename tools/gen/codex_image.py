# Mittler（写したときの名前は claude-cut）の写し（元：作者の制作のワークスペースの tools\codex_image.py、2026-10-21。中身はそのまま）。🎬 の開始・終了の絵の生成で Codex のアダプタ tools/codex_jobs.py が呼ぶ。
# 2026-10-30：Codex CLI の場所とモデルを環境変数で変えられるようにした（無ければ前と同じ PATH の codex・gpt-6.1-sol）。
# 2026-11-12：環境変数の名前は MITTLER_CODEX・MITTLER_CODEX_MODEL（古い名前 CC_CODEX・CC_CODEX_MODEL も読む。pyengine/mittler/names.py）。
"""Generate one image with codex-cli's built-in image_gen and save it into the project.

Claude has no built-in image generator, so this wrapper runs `codex exec` non-interactively,
attaches reference images with `-i`, lets Codex call its own image_gen once, then copies the
new file from ~/.codex/generated_images into the requested path. Gemini is not used here.

Attaching with `-i` only lets Codex *see* the references; image_gen receives them only when Codex
passes their paths in `referenced_image_paths`. The instruction requires that, and afterwards the
Codex rollout is checked: the record's `refs_ok` is true only if every reference reached image_gen,
and `spec_coverage` is the share of the spec's lines that reached image_gen verbatim (Codex otherwise
paraphrases into a short English prompt and drops the style).

Examples (from the workspace root):
  .venv/Scripts/python.exe -X utf8 tools/codex_image.py --packet dialogue-video/output/JOB/image-requests/p01_s02.json --out dialogue-video/output/JOB/images/p01_s02.png
  .venv/Scripts/python.exe -X utf8 tools/codex_image.py --prompt-file prompt.txt --ref ref.png --out out.png
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

CODEX_HOME = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
GENERATED = CODEX_HOME / 'generated_images'
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
# Mittler: the model and the codex CLI can be set per PC (env MITTLER_CODEX_MODEL / MITTLER_CODEX; the server passes the VS Code settings
# mittler.codex.model / mittler.codex.path to the job runner. docs/インストールガイド.md 12). Unset = the values below / codex on PATH.
# The old names CC_CODEX_MODEL / CC_CODEX are still read (pyengine/mittler/names.py: env).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pyengine'))
from mittler.names import env as _env  # noqa: E402

DEFAULT_MODEL = _env('CODEX_MODEL') or 'gpt-6.1-sol'  # 2026-10-11 user: luna -> sol (astra also OK)
MAX_TOOL_REFS = 5  # image_gen takes at most 5 reference images

INSTRUCTION = """あなたは画像生成だけを行う担当です。
- 内蔵の image_gen ツールをちょうど1回呼び、下の仕様どおりの画像を1枚生成してください。
- 添付画像は参照画像です。添付順と役割は仕様内の記載に従ってください。
- image_gen の prompt 引数には、下の「画像仕様」の本文を一字一句そのまま入れてください（翻訳・要約・省略・言い換え・並べ替えをしない。長くても全部入れる）。画風・色・質感の指定も含めて、全文が image_gen に届く必要があります。
{ref_rule}- シェルコマンドの実行、ファイルの作成・編集・移動、質問、追加の画像生成はしないでください。
- 生成後の返答は「DONE」だけにしてください。

=== 画像仕様 ===
"""

REF_RULE = """- 参照画像は image_gen に必ず渡してください。image_gen の referenced_image_paths に、次のパスをこの順番のまま全部入れて呼ぶこと（num_last_images_to_include は使わない）。添付を自分で見て文章で説明するだけでは、image_gen には画像が届きません。
{paths}
"""

SESSION_NOTE = """（この作品の続きのカットです。このセッションで以前に生成・採用した画像と同じ世界観・人物・場所の設定を保ってください。
ただし今回添付した画像（基準全景・直前採用カット・人物参照）と下の仕様が正です。以前の不採用画像には合わせないでください。）

"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def snapshot():
    if not GENERATED.is_dir():
        return {}
    return {p: p.stat().st_mtime for p in GENERATED.rglob('*') if p.suffix.lower() in IMAGE_SUFFIXES}


def load_request(args):
    if args.packet:
        packet_path = Path(args.packet).resolve()
        packet = json.loads(packet_path.read_text(encoding='utf-8'))
        refs = [Path(p) for p in packet.get('referenced_image_paths', [])]
        return packet['prompt'], refs, str(packet_path)
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding='utf-8')
    elif args.prompt:
        prompt = args.prompt
    else:
        raise SystemExit('--packet, --prompt-file, or --prompt is required')
    return prompt, [Path(p) for p in args.ref], None


def build_instruction(refs):
    if not refs:
        return INSTRUCTION.format(ref_rule='')
    paths = '\n'.join(f'  {i}. {r}' for i, r in enumerate(refs, 1))
    return INSTRUCTION.format(ref_rule=REF_RULE.format(paths=paths))


def _norm_path_text(s):
    # JS string literals in the rollout double the backslashes; Codex may also use forward slashes.
    return s.replace('\\\\', '\\').replace('/', '\\').lower()


def image_gen_calls(thread_id, since):
    """Inputs of the image_gen calls Codex made in this thread at or after `since` (epoch seconds)."""
    sessions = CODEX_HOME / 'sessions'
    if not thread_id or not sessions.is_dir():
        return []
    calls = []
    for f in sessions.rglob(f'*{thread_id}.jsonl'):
        with open(f, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if 'imagegen' not in line and 'image_gen' not in line:
                    continue
                try:
                    event = json.loads(line)
                    ts = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00')).timestamp()
                except (ValueError, KeyError):
                    continue
                payload = event.get('payload') or {}
                if ts < since or payload.get('type') not in ('custom_tool_call', 'function_call'):
                    continue
                text = payload.get('input') or payload.get('arguments') or ''
                if 'imagegen' in text or 'image_gen' in (payload.get('name') or ''):
                    calls.append(text)
    return calls


def spec_coverage(prompt, calls):
    """Share of the spec's lines that reached image_gen verbatim (Codex tends to paraphrase and drop the style)."""
    lines = [ln.strip() for ln in prompt.splitlines() if len(ln.strip()) >= 8]
    if not lines or not calls:
        return None
    # The call is JS source: newlines and quotes inside the prompt string literal are escaped.
    text = ' '.join(calls).replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'")
    return round(sum(ln in text for ln in lines) / len(lines), 2)


def kill_tree(proc):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
    else:
        proc.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--packet', help='image-context packet JSON (prompt + referenced_image_paths)')
    parser.add_argument('--prompt-file')
    parser.add_argument('--prompt')
    parser.add_argument('--ref', action='append', default=[], help='reference image, in order (repeatable)')
    parser.add_argument('--out', required=True, help='destination image path; never overwritten')
    parser.add_argument('--record', help='record JSON path (default: <out>.codex.json)')
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--effort', default='medium', help='codex model_reasoning_effort')
    parser.add_argument('--service-tier', default='priority',
                        help='codex service_tier: "priority" = Fast mode (luna 1.5x / sol・astra 2x speed, more usage), '
                             '"default" = normal (2026-10-11 user: fast on)')
    parser.add_argument('--timeout', type=int, default=900, help='seconds')
    parser.add_argument('--fix', help='修正指示（差し戻し理由）。プロンプト末尾に追記する')
    parser.add_argument('--session', help='作品（または場所）ごとのCodexセッション記録JSON。'
                        'なければ新規セッションを作って記録し、あれば codex exec resume で同じ会話に続けて生成する')
    parser.add_argument('--replace-rejected', action='store_true',
                        help='既存の --out を不採用として rejected/ へ退避してから生成する（削除しない）')
    args = parser.parse_args()

    out = Path(args.out).resolve()
    record_path = Path(args.record).resolve() if args.record else out.with_name(out.name + '.codex.json')
    if out.exists() and not args.replace_rejected:
        raise SystemExit(f'output already exists; choose a new path or pass --replace-rejected: {out}')
    prompt, refs, packet = load_request(args)
    if args.fix:
        prompt += '\n修正指示（前回の生成からの差し戻し。これを最優先で守る）:\n' + args.fix
    refs = [r.resolve() for r in refs]
    missing = [str(r) for r in refs if not r.is_file()]
    if missing:
        raise SystemExit(f'reference image not found: {missing}')
    # Hash the references now: one of them may be the --out file that a successful run replaces.
    ref_hashes = [sha256(r) for r in refs]
    if len(refs) > MAX_TOOL_REFS:
        sys.stderr.write(f'WARNING: {len(refs)} references; image_gen uses at most {MAX_TOOL_REFS}\n')

    want = _env('CODEX')
    codex = (shutil.which(want) or (want if Path(want).is_file() else None)) if want else shutil.which('codex')
    if not codex:
        raise SystemExit(f'codex CLI not found: {want} (MITTLER_CODEX / mittler.codex.path)' if want else 'codex CLI not found on PATH')

    session_path = Path(args.session).resolve() if args.session else None
    session = None
    if session_path and session_path.is_file():
        session = json.loads(session_path.read_text(encoding='utf-8'))
    lock = None
    if session_path:
        # One codex session must not be driven by two generations at once.
        session_path.parent.mkdir(parents=True, exist_ok=True)
        lock = session_path.with_name(session_path.name + '.lock')
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
        except FileExistsError:
            raise SystemExit(f'session is in use (lock exists): {lock}. Remove it only after confirming no codex_image.py is running.')

    before = snapshot()
    started = time.time()
    common = ['--skip-git-repo-check', '--json', '-c', 'sandbox_mode="read-only"',
              '-c', f'model_reasoning_effort="{args.effort}"', '-c', f'service_tier="{args.service_tier}"',
              '-c', 'notify=[]', '--model', args.model]
    try:
        with tempfile.TemporaryDirectory(prefix='codex-image-') as tmpdir:
            # resume looks sessions up relative to cwd, so a session keeps one fixed working directory.
            work = Path(session['cwd']) if session else (session_path.parent if session_path else Path(tmpdir))
            last_message = Path(tmpdir) / 'last.txt'
            images = [x for r in refs for x in ('-i', str(r))]
            instruction = build_instruction(refs)
            if session:
                cmd = [codex, 'exec', 'resume', *common, '-o', str(last_message), *images, session['thread_id'], '-']
                text = instruction + SESSION_NOTE + prompt
            else:
                cmd = [codex, 'exec', *common, '--color', 'never', '-C', str(work), '-o', str(last_message), *images]
                text = instruction + prompt
            proc = subprocess.Popen(cmd, cwd=work, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, encoding='utf-8', errors='replace')
            try:
                stdout, stderr = proc.communicate(text, timeout=args.timeout)
            except subprocess.TimeoutExpired:
                kill_tree(proc)
                proc.communicate()
                raise SystemExit(f'codex exec timed out after {args.timeout}s (process tree stopped)')
            reply = last_message.read_text(encoding='utf-8', errors='replace').strip() if last_message.exists() else ''
    finally:
        if lock and lock.exists():
            lock.unlink()

    thread_id, errors = (session['thread_id'] if session else None), []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'thread.started':
            thread_id = event.get('thread_id')
        if event.get('type') in ('error', 'turn.failed'):
            errors.append(event)

    after = snapshot()
    new = sorted((p for p, m in after.items() if p not in before or m > before[p]), key=lambda p: after[p])
    if thread_id:
        # Only this thread's images: with several generations running in parallel, the newest image
        # overall may belong to another job, so never fall back to it (a failed run must fail).
        new = [p for p in new if thread_id in p.parts]
    if proc.returncode != 0 or not new:
        sys.stderr.write(stderr[-3000:] + '\n')
        raise SystemExit(f'image generation failed (exit {proc.returncode}, new images {len(new)}, '
                         f'errors {json.dumps(errors, ensure_ascii=False)[:1500]}, reply {reply[:500]!r})')

    source = new[-1]
    calls = image_gen_calls(thread_id, started - 5)
    refs_passed = [str(r) for r in refs if any(_norm_path_text(str(r)) in _norm_path_text(c) for c in calls)]
    refs_ok = (len(refs_passed) == len(refs)) if calls else None  # None: rollout not found, unverified
    coverage = spec_coverage(prompt, calls)
    if coverage is not None and coverage < 0.9:
        sys.stderr.write(f'WARNING: only {coverage:.0%} of the spec lines reached image_gen verbatim '
                         '(Codex paraphrased; style/look may be lost).\n')
    if refs and refs_ok is not True:
        sys.stderr.write(f'WARNING: references did not all reach image_gen (passed {len(refs_passed)}/{len(refs)}, '
                         f'image_gen calls found {len(calls)}). Faces/details may not follow the references.\n')

    # Retire the previous output only now that a replacement exists.
    rejected = None
    if out.exists():
        rejected = out.parent / 'rejected' / f'{out.stem}-{time.strftime("%Y%m%d-%H%M%S")}{out.suffix}'
        rejected.parent.mkdir(parents=True, exist_ok=True)
        os.replace(out, rejected)
        if record_path.is_file():
            os.replace(record_path, rejected.with_name(rejected.name + '.record.json'))
    if session_path:
        if session is None:
            if not thread_id:
                raise SystemExit('generated, but codex did not report a thread id; session not recorded')
            session = {'thread_id': thread_id, 'cwd': str(work), 'model': args.model,
                       'created': time.strftime('%Y-%m-%dT%H:%M:%S'), 'generations': []}
        session['generations'].append({'out': str(out), 'time': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       'fix': bool(args.fix)})
        session_path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding='utf-8')
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + '.part')
    shutil.copy2(source, tmp)
    os.replace(tmp, out)
    try:
        from PIL import Image
        with Image.open(out) as im:
            width, height = im.size
    except Exception:
        width = height = None

    record = {
        'generator': 'codex-cli built-in image_gen',
        'codex_model': args.model,
        'service_tier': args.service_tier,
        'codex_thread_id': thread_id,
        'codex_session_file': str(session_path) if session_path else None,
        'resumed_session': bool(session_path and len(session['generations']) > 1),
        'source_generated_path': str(source),
        'other_new_images': [str(p) for p in new[:-1]],
        'saved_path': str(out),
        'sha256': sha256(out),
        'width': width,
        'height': height,
        'packet': packet,
        'fix': args.fix,
        'replaced_rejected': str(rejected) if rejected else None,
        'references': [{'path': str(r), 'sha256': h} for r, h in zip(refs, ref_hashes)],
        'image_gen_calls': len(calls),
        'refs_passed_to_image_gen': refs_passed,
        'refs_ok': refs_ok,
        'spec_coverage': coverage,
        'prompt': prompt,
        'codex_reply': reply[:2000],
        'seconds': round(time.time() - started, 1),
        'accepted': False,
    }
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: record[k] for k in ('saved_path', 'sha256', 'width', 'height', 'seconds', 'refs_ok', 'spec_coverage')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
