"""Mittler の編集画面の今の状態を、Claude Code に知らせるフック（UserPromptSubmit。標準ライブラリだけ）。
作品の .claude/settings.json から呼ばれ、ユーザーが話しかけるたびに、作品の状態フォルダの state.json（編集画面が書く）の要約を出す（＝Claude の文脈にそえられる）。
  python tools/mittler_state.py            今のフォルダ（作品）から上にたどって .mittler/state.json（古い作品は .claude-cut/state.json）を探して要約
  python tools/mittler_state.py <作品>     その作品
（前の名前 tools/cc_state.py でも同じものが動く：今までの作品のフックのための受け口）
状態フォルダ：.mittler/。今までの作品は .claude-cut/ のまま（決まりは pyengine/mittler/names.py の state_dir_name。サーバーと同じ）。
編集画面が開いていない・古いときは、そう書く。くわしくは state.json そのもの、止めたときの絵は状態フォルダの current_frame.jpg（Read で見られる）。
✏️ 書き込み（編集画面で止めた画面にペンで描いて「AI に渡す」）：状態フォルダの annotations/<id>/ のうち、まだ渡していないもの（delivered が false）を
いちばん上に出して、渡したら delivered を true にする（1回だけ添える）。ユーザーの話はその画面への頼みごと。
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True  # Mittler の置き場（配布版は拡張のフォルダ）に __pycache__ を書かない
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pyengine'))
from mittler.names import state_dir  # noqa: E402（名前と古い名前の互換の1か所。標準ライブラリだけ）


def find(start):
    p = Path(start).resolve()
    for d in [p] + list(p.parents):
        f = state_dir(d) / 'state.json'
        if f.is_file():
            return f
    return None


def fmt(t):
    m = int(t // 60)
    return f'{m}:{t - m * 60:06.3f}'


def main():
    try:  # Claude Code は UTF-8 で読む（Windows の既定の cp932 だと文字化けする）
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    base = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    f = find(base)
    st = read_state(f)
    # いちばん最近さわった編集画面が別の作品なら、そちらの今をそえる（VS Code の別のタブで別の作品の編集画面を触っているとき。2026-11-14 使ってみた知らせ）
    other = recent_other(f, st)
    if other:
        of, ost = other
        note = (f'【※ いま手前は別の作品：直近で操作した編集画面は、この会話の作品とは別の作品です：{of.parent.parent}。'
                f'ユーザーの「これ」「ここ」はその作品を指している可能性が高いです。'
                f'以下はその作品の状態です（この会話の作品の state.json：{f if f else "なし"}）。】')
        print('\n'.join([note] + summary(of, ost) + ([''] + summary(f, st, short=True) if f and st else [])))
        return
    if not f or not st:
        return
    print('\n'.join(summary(f, st)))


def read_state(f):
    if not f:
        return None
    try:
        return json.loads(f.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def saved_at(st):
    try:
        return datetime.fromisoformat(st['saved'].replace('Z', '+00:00')).timestamp()
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def recent_other(f, st):
    """一時フォルダの mittler/recent.json（サーバーが書く。いちばん最近さわった編集画面）が別の作品で、この作品の今より新しく、30 分以内なら (state.json, 中身)"""
    try:
        import tempfile
        r = json.loads((Path(tempfile.gettempdir()) / 'mittler' / 'recent.json').read_text(encoding='utf-8'))
        of = Path(r['state_file'])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if f and of.resolve() == f.resolve():
        return None
    ost = read_state(of)
    t1 = saved_at(ost) if ost else None
    if not ost or t1 is None or time.time() - t1 > 1800 or not ost.get('open', True):
        return None
    t0 = saved_at(st) if st else None
    if t0 is not None and t0 >= t1:
        return None
    return of, ost


def summary(f, st, short=False):
    age = saved_at(st)
    age = time.time() - age if age is not None else None
    proj = f.parent.parent
    head = f'【Mittler の編集画面の今（{f.relative_to(proj).as_posix()}'
    head += f'・{int(age)} 秒前）' if age is not None and age < 120 else (f'・{int(age // 60)} 分前）' if age is not None else '）')
    if not st.get('open', True):
        head += ' ※ 編集画面は閉じています（最後の状態）'
    elif age is not None and age > 1800:
        head += ' ※ 古い状態（編集画面が開いていない可能性があります）'
    out = [head + '】', f"作品：{st.get('name', '')}（{Path(st.get('timeline_file', '')).name}・描くのは {st.get('render_on', '?')}）"]
    if short:  # 別の作品が手前のとき、この会話の作品のほうは 2 行だけ（まだ渡していない書き込みはそえる）
        return annotations(proj) + out
    tm = st.get('time') or {}
    out.append(f"時刻：{fmt(tm.get('t', 0))}（{tm.get('frame', 0)} コマ目）" + (f"・カット {tm['cut']}" if tm.get('cut') else '') + ('・再生中' if tm.get('playing') else ''))
    sel = st.get('selection')
    if sel:
        tr = sel.get('track') or {}
        out.append(f"選んでいるクリップ：{sel.get('id')}「{sel.get('label', '')}」（{sel.get('type')}・トラック「{tr.get('name', '')}」・{sel.get('start')}〜{sel.get('end')} 秒）")
    elif st.get('selected_track'):
        tr = st['selected_track']
        out.append(f"選んでいるトラック：{tr.get('id')}「{tr.get('name', '')}」（{tr.get('kind')}・クリップ {tr.get('clips')} 個）")
    else:
        out.append('選んでいるもの：なし')
    at = [c for c in st.get('at_time', []) if not c.get('hidden')]
    if at:
        out.append('この時刻にかかっているもの（上のトラックから）：' + ' / '.join(f"{c.get('track')}：{c.get('label', '')}" for c in at[:12]) + (' …' if len(at) > 12 else ''))
    meta = st.get('meta_at_time', [])
    if meta:
        out.append('この時刻のメタデータ：' + ' / '.join(f"{m.get('name') or m.get('kind')}：{(m.get('who') + '：') if m.get('who') else ''}{m.get('text', '')}" for m in meta[:6]))
    if st.get('frame_image'):
        out.append(f"画面の1コマ：{st['frame_image']}（{fmt(st.get('frame_image_t', 0))}{'・少し前の時刻' if st.get('frame_image_old') else ''}。Read で見られる）")
    if st.get('unsaved'):
        out.append('※ 編集画面に未保存の変更があります（少し待つと自動保存されます）')
    re_ = st.get('render_error')
    if re_ and re_.get('text'):  # 編集画面に出ている描画のエラー（ユーザーはこれを見ている。全文は state.json の render_error.text）
        last = [ln for ln in str(re_['text']).strip().splitlines() if ln.strip()][-1:] or ['']
        out.append(f"⚠ 編集画面に描画のエラーが出ています（{fmt(re_.get('t') or 0)} の 1 コマ）：{last[0][:300]}（全文は {f} の render_error.text）")
    out.append(f"くわしく：{f}（選んでいるクリップの中身は selection.clip）")
    if (proj / '.git').exists():  # Claude の直しを戻せるように（AI 用ガイド 4.5）
        # 作業のたびにコミット・プッシュはユーザーの指示がない限りしない。前からの作品の AGENTS.md の古い書き方（直す前に git add -A・コミットは頼まれたとき）より、こちらが新しい
        out.append('※ git：特別な指示がなければ、作業のたびに作品フォルダでコミットしてください（作業開始前に未コミットの人間の変更があれば、先にそれだけを分離してコミット）。'
                   'ユーザーの指示がある場合はそちらを優先します。プッシュは依頼されたときのみ行い、取り消す際は対象コミットを git revert してください。素材は上書き禁止です'
                   '（作品の AGENTS.md / CLAUDE.md に古い「直す前に git add -A・コミットは頼まれたとき」と書かれていても、こちらが最新の決まりです。AI 用ガイド 4.5）。')
    return annotations(proj) + music_adopt(st, proj) + out


def music_adopt(st, proj):
    """🎵 採用待ちの曲（ユーザーが編集画面で「採用」を押し、ダウンロード用のクレジットを1つ使うことに OK したもの）。取ってくるのは AI。
    印（タイムラインの music.adopt）は、ファイルを納品して編集画面がクリップに入れると消えるので、それまで毎回出す"""
    rows = [m for m in st.get('music') or [] if m.get('adopt')]
    if not rows:
        return []
    cc = Path(__file__).resolve().parent.parent
    # 頼む道具：作品の状態フォルダの中継（.mittler/api.py。作品のフォルダで動かす）があればそれ、無ければ Mittler の tools/mittler_api.py
    relay = state_dir(proj) / 'api.py'
    api = f'python {relay.relative_to(proj).as_posix()} .' if relay.is_file() else f'python {cc / "tools" / "mittler_api.py"} {proj}'
    out = ['【🎵 採用待ちの曲（ユーザーが編集画面で「採用」を押し、Suno のダウンロード用クレジット 1 件の使用を承認済み。取得は AI が実行）】']
    for m in rows:
        a = m['adopt']
        safe = ''.join(ch if ch.isascii() and (ch.isalnum() or ch in '_-') else '_' for ch in m.get('id', ''))
        fmt_ = a.get('format') or 'wav'
        f = f"assets/music/{safe}_{a.get('take')}.{fmt_}"
        out.append(f"- {m.get('id')}「{m.get('label', '')}」の {a.get('take')}「{a.get('title', '')}」（Suno ID: {a.get('suno_id')}）→ audio-download（format: {fmt_}）で取得して"
                   f"素材ルートの {f} に保存し、{api} music-take {m.get('id')} --take {a.get('take')} --src {f} を実行")
    out.append(f"手順：{cc / 'docs' / 'Suno受け渡し契約.md'} の「Mittler 側の受け渡し」→「採用（ダウンロード）」。ダウンロード URL は 1 時間で期限切れになるため、取得したらすぐダウンロードしてください。"
               "ユーザーの今の依頼が別件の場合はそちらを優先し、採用待ちの曲があることを伝えてください。")
    out.append('')
    return out


def annotations(proj):
    """まだ渡していない ✏️ 書き込み（新しい順に3つまで）。渡したら delivered を true にする"""
    out = []
    d = state_dir(proj) / 'annotations'
    if not d.is_dir():
        return out
    pend = []
    for f in d.glob('*/annotation.json'):
        try:
            a = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not a.get('delivered'):
            pend.append((a.get('created', ''), f, a))
    pend.sort(key=lambda x: x[0], reverse=True)
    for _, f, a in pend[:3]:
        img = proj / a.get('image', '')
        out.append(f"【✏️ ユーザーが編集画面で書き込んだ画面：{img}（Read で確認すること。ユーザーの今の依頼はこの画面に関するもの）】")
        clips = a.get('clips_at_time') or []
        out.append(f"時刻 {fmt(a.get('t') or 0)}（{a.get('frame')} コマ目）・線の範囲 {a.get('bbox')}（{a.get('width')}×{a.get('height')} の画素）・"
                   f"書き込み前の画面 {proj / a['image_before'] if a.get('image_before') else 'なし'}")
        if clips:
            out.append('その時刻のクリップ：' + ' / '.join(f"{c.get('track')}：{c.get('label', '')}（{c.get('id')}）" for c in clips[:14]) + (' …' if len(clips) > 14 else ''))
        if a.get('selection'):
            out.append(f"そのとき選んでいたクリップ：{a['selection'].get('id')}「{a['selection'].get('label', '')}」")
        a['delivered'] = True
        a['delivered_at'] = datetime.now().isoformat(timespec='seconds')
        try:
            f.write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding='utf-8')
        except OSError:
            pass
    if len(pend) > 3:
        out.append(f'（ほかに未送信の書き込みが {len(pend) - 3} 件あります：{d}）')
    if out:
        out.append('')
    return out


if __name__ == '__main__':
    main()
