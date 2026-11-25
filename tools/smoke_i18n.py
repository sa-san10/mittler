"""画面の言葉（英語・日本語の切り替え。既定は英語）の確かめ。ヘッドレスのブラウザ、localhost だけ。
  <Playwright の python> -X utf8 tools/smoke_i18n.py --render-python <描画の python> [--work <フォルダ>] [--shots <フォルダ>] [--base <コミット>]
  （--work：試しの作品を残す場所。無ければ一時フォルダに作って消す。--shots：英語の画面（ダーク・ライト、幅 1600／1280／900）と
    日本語の画面（1280・ダーク）のスクリーンショットを残す。--base：日本語の辞書を比べる、直す前のコミット（既定 6ffddab））
試しの作品（中身は英語：字幕・エフェクト・映像・画像・動画化予定・セリフ・音）を new_project.js --lang en で作り、サーバーを自分で立てて（--lang を付けない＝既定）、終わったら /api/quit で止める。
確かめること：
  (a) 辞書   editor/i18n/en.json と ja.json の鍵が同じ・空の文が無い（{one, other} は英語の複数形）
  (b) 鍵     コードが使う鍵（$t・$L・t・KE・L・I18N.tr・data-i18n…、モジュールの頭つきの呼び方も）が辞書にある。使っていない鍵は数と頭だけ（INFO）
  (c) 英語   既定（英語）の画面に日本語が残らない：上のバー・右の欄（クリップの種類ごと・トラック・色・メタデータ）・アセット窓のタブ・メニュー・
             書き出しとマスターの窓・右クリック・書き込み・カットの道具・＋ 新規・コードの窓・知らせ。文字と title・placeholder・aria-label・data-why
             （作品の中身＝キャラのプリセットの名前・コードの中身・プロジェクトのファイル名は見ない）
  (d) 日本語 ja.json の文のうち、最初に辞書へ移したとき（--base のコミット）のコードの文のままのものの数（知らせるだけ。2026-11-21 に文を整えたので、落とす条件ではない）
  (e) 切替   上のバーの EN／日本語 で、開いている窓（書き出し）・右の欄・ツールチップ・上の知らせがすぐ切りかわる（窓の入力は残る）。
             再読み込みしても覚えている（このブラウザ・サーバー）。URL の &lang= が勝つ。タイムライン・state.json に言葉を書かない
  (f) 崩れ   英語で幅 1600・1280・900：上のバーのボタンがはみ出さない・重ならない・字が切れない・横スクロールが出ない
  (g) アイコン 英語と日本語の (c) と同じ場面で、絵文字と、アイコンにならなかった印 {icon:…} が 1 つも残らない（2026-11-14 アイコン化。作品の中身は見ない）
  (d) は、前のコードの絵文字と今の辞書のアイコンの印を外して比べる（ツールチップで絵文字を言葉に直した文は ICON_REWORD）
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
fails = []


def opt(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


RPY = opt('--render-python')
if not RPY:
    sys.exit('使い方: smoke_i18n.py --render-python <描画の python> [--work <フォルダ>] [--shots <フォルダ>] [--base <コミット>]')
SHOTS = Path(opt('--shots')) if opt('--shots') else None
BASE = opt('--base', '6ffddab')
# 日本語の字：かな・漢字・日本語の約物（、。「」（）：など）。「＋」（全角のプラス）は、どちらの言葉でもボタンの印（＋ New・トラックを足す ＋）なので数えない
JP = re.compile(r'[　-〿぀-ヿ㐀-鿿！-＊，-｠]')
JP_JS = r'/[　-〿぀-ヿ㐀-鿿！-＊，-｠]/'
# 絵文字（画面には使わない。印は Lucide のモノグラムのアイコンだけ）。
# Unicode の絵文字の字（Extended_Pictographic のおもなところ）と、絵文字の形にする字（U+FE0F）。tools/smoke_icons.py と同じ並び
EMO_CLASS = (r'©®‼⁉™ℹ↔-↙↩↪⌚⌛⌨⏏⏩-⏳⏸-⏺Ⓜ▪▫▶◀'
             r'◻-◾☀-➿⤴⤵⬅-⬇⬛⬜⭐⭕〰〽㊗㊙️')
EMO = re.compile('[' + EMO_CLASS + '\U0001F000-\U0001FAFF]')
EMO_JS = '/[' + EMO_CLASS + r'\u{1F000}-\u{1FAFF}]|\{icon:/u'  # 画面に絵文字か、アイコンにならなかった印 {icon:…} が残っていないか
ICON_MARK = re.compile(r'\{icon:[a-z0-9-]+\} ?')


def check(ok, msg):
    print(('OK   ' if ok else 'FAIL ') + msg, flush=True)
    if not ok:
        fails.append(msg)


def info(msg):
    print('INFO ' + msg, flush=True)


def node_cmd():
    n = shutil.which('node')
    return [n] if n else ['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'node']


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close()
    return p


# ---------------- (a) 辞書 ----------------
D = {l: json.loads((ROOT / 'editor' / 'i18n' / f'{l}.json').read_text(encoding='utf-8')) for l in ('en', 'ja')}


def part_dicts():
    en, ja = D['en'], D['ja']
    only = sorted(set(en) ^ set(ja))
    check(not only, f'(a) 辞書：en.json と ja.json の鍵が同じ（{len(en)} 個）' + (f' 片方だけ：{only[:10]}' if only else ''))
    empty = [k for l in ('en', 'ja') for k, v in D[l].items() if k != '_end' and (v == '' or v is None or (isinstance(v, dict) and not v.get('other')))]
    check(not empty, '(a) 辞書：空の文が無い' + (f' {empty[:10]}' if empty else ''))
    jaobj = [k for k, v in ja.items() if isinstance(v, dict)]
    check(not jaobj, '(a) 辞書：日本語は単数・複数を分けない（{one, other} は英語だけ）' + (f' {jaobj[:10]}' if jaobj else ''))
    jp_in_en = [k for k, v in en.items() if JP.search(json.dumps(v, ensure_ascii=False).replace('日本語', ''))
                and not any(x in json.dumps(v, ensure_ascii=False) for x in ('インストールガイド', 'Suno受け渡し契約'))]
    check(not jp_in_en, '(a) 辞書：英語の文に日本語が無い（文書のファイル名を除く）' + (f' {jp_in_en[:10]}' if jp_in_en else ''))


# ---------------- (b) コードが使う鍵 ----------------
CODE = [*sorted((ROOT / 'editor').glob('*.js')), ROOT / 'editor' / 'index.html', *sorted((ROOT / 'server').glob('*.js')), ROOT / 'extension.js', ROOT / 'tools' / 'new_project.js',
        *sorted((ROOT / 'pyengine' / 'mittler').glob('*.py')), *[ROOT / 'tools' / n for n in ('jobs.py', 'h3_jobs.py', 'codex_jobs.py', 'tts_gen.py')]]
CALL = re.compile(r"""(?:\$t|\$L|\bKE|\bL|\bt|I18N\.tr\([^,()]+,|I18N\.L)\(\s*['"]([A-Za-z0-9_.]+)['"]""")
# モジュールの頭つきの呼び方：const X = (k, v) => $t('ex.' + k, v) ／ const T = k => $t('sub.' + k)。同じ名前を場所ごとに作り直していることがある（media.js の T）
WRAP = re.compile(r"""const\s+(\w+)\s*=\s*(?:\(k(?:,\s*v)?\)|k)\s*=>\s*\$[tL]\(\s*'([A-Za-z0-9_.]+\.)'\s*\+\s*k""")
COMMENT = re.compile(r'^\s*(//|#|\*).*$', re.M)  # 行まるごとのコメント（例の鍵を書いている）
ATTR = re.compile(r'data-i18n(?:-title|-ph|-aria)?="([A-Za-z0-9_.]+)"')
LIT = re.compile(r"""['"]([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+\.?)['"]""")


def part_keys():
    keys = set(D['ja']) - {'_end'}
    used, missing, lits, prefixes = set(), [], set(), set()
    for f in CODE:
        src = COMMENT.sub('', f.read_text(encoding='utf-8'))
        rel = f.relative_to(ROOT).as_posix()
        found = set(CALL.findall(src)) | set(ATTR.findall(src))
        defs = [(m.start(), m.group(1), m.group(2)) for m in WRAP.finditer(src)]  # モジュールの頭つきの呼び方（export.js の X('btn') ＝ ex.btn など）
        for _, name, pre in defs:
            prefixes.add(pre)
            for m in re.finditer(r'(?<![\w$.])' + re.escape(name) + r"""\(\s*'([A-Za-z0-9_.]+)'""", src):
                before = [d for d in defs if d[1] == name and d[0] < m.start()]
                if before and before[-1][2] == pre:  # その呼び方のいちばん近い前の定義の頭
                    found.add(pre + m.group(1))
        for k in found:
            if k.endswith('.'):
                prefixes.add(k); continue
            if '.' not in k:
                continue  # t('x') のような鍵でない呼び方（Python の t は鍵だけだが、念のため）
            if k in keys:
                used.add(k)
            elif not any(k.startswith(p) for p in ('mittler.', 'claudeCut.', 'window.', 'S.', 'tl.')):
                missing.append(f'{rel}: {k}')
        for s in LIT.findall(src):
            (prefixes if s.endswith('.') else lits).add(s)
    check(not missing, f'(b) 鍵：コードが使う鍵が辞書にある（{len(used)} 個）' + (f' 無い：{missing[:15]}' if missing else ''))
    # 使っていない鍵：コードのどこにも文字として出てこず、頭（'ex.' + k の 'ex.' など）でも組み立てられないもの。数と頭だけ
    dyn = lambda k: any(k.startswith(p) or ('.' + p) in k for p in prefixes)  # noqa: E731
    unused = sorted(k for k in keys if k not in used and k not in lits and not dyn(k) and not k.startswith(('tpl.',)))
    heads = {}
    for k in unused:
        heads[k.split('.')[0]] = heads.get(k.split('.')[0], 0) + 1
    info(f'(b) 鍵：コードに文字として出てこない鍵 {len(unused)} 個（頭ごと {heads}）' + (f'：{unused[:20]}' if unused else ''))


# ---------------- (d) 日本語の文が直す前と同じ ----------------
# 直す前のコードでは、いくつかの文を部品から組み立てていた（三項演算子・足し算）・新しく足した文（言葉の切り替え）。どれも目で確かめた（2026-11-13）
COMPOSED = set('''
bar.lang.tip src.current src.currentScaled src.proxyAudio clip.ttsPending clip.notGenerated meta.emptyCuts meta.emptyNotes meta.addCutSplit meta.addCutFirst meta.addItem
meta.addCutsLane meta.addCutsLane.tip meta.addNotesLane meta.addNotesLane.tip tr.shyOn tr.shyOff tr.muted tr.mute tr.hidden tr.visible tr.mutedTag tr.hiddenTag
bar.shy.hiding bar.shy.hide sel.perCut sel.fixed sel.enable sel.disable st.extUndo toast.extUndo st.extRedo st.snapOn st.snapOff st.rendererStarting meta.split
grade.titleAll grade.resetCut snap.tipOn snap.tipOff snap.tipOnNone snap.tipOffNone drag.fadeIn drag.fadeOut drag.cutBoundary drag.cutStart drag.cutEnd drag.move
drag.moveN drag.lenN ce.linkOn ce.linkOff ce.vaPlacedSkip ce.selN cm.edgeMoved.boundary cm.edgeMoved.start cm.edgeMoved.end cm.rangeExistV cm.rangeMade cm.rangeMadeV
cm.firstCut cm.firstCutConv cm.cutFrom.tipV f.fadeInCurve f.fadeOutCurve tts.lineGemini tts.lineVv tts.regen tts.gen sub.own sub.inherit sub.shadowColor sub.halign
batch.subsDoneKept batch.doneStopped trk.add trk.deleted trk.deletedN as.emptyLine as.generating as.noBgm as.noVoice as.noAudio as.planStart as.planEnd as.placeBgm
as.placeSfx as.placeFx as.variantsN as.inProject an.delivered an.waiting an2.queued an2.fromImages an2.forEffects np.pick.tip pl.adoptedAllLatest pl.existing
pl.startDone pl.endDone pl.endFrame pl.seedAuto pl.h3Note wp.noNext wp.noPlan wp.slowNo wp.hintShort wp.hintEnough wp.stretchedSlow wp.stretchedHold wp.audioKept
wp.stretchedAllSlow wp.stretchedAllHold wp.inNo wp.speedNo wp.redo wp.manual wp.doneFlow wp.doneDiff mu.open.tip mu.play mu.play.tip mu.beats.tip ex.took.real
ex.workTip.set ex.workTip.unset ex.info.scale ex.elapsed ex.draftMark ex.proxyInUse ex.again ex.back srv.up.overUnused srv.np.abs pr.noFrame.start pr.noFrame.end
pr.noFrameOf.start pr.noFrameOf.end tpl.t_sfx_0
gl3d.off gl3d.noModule gl3d.noContext bl.noBlender bl.noScene bl.fail ex.ph.blender ex.ph.blender.sub srv.fxBadName srv.fxNoLib srv.fxExists
as.libHead as.libAdd as.libAdd.tip as.libAdded as.libAddFailed as.badge3d.tip sel.blRedraw sel.blRedraw.tip sel.blClear sel.blClear.tip sel.blScene sel.blScene.tip
st.blCleared st.blClearFailed src.blRendering
srv.noPresetsDir srv.py.noRenderPython ext.setup.running ext.setup.noPython ext.setup.btnCopy ext.setup.failed ext.setup.allOk ext.setup.missing ext.setup.btnInstallVenv
ext.setup.btn3d ext.setup.btnRecheck ext.setup.btnInstall ext.setup.btnSetup ext.setup.venvPick ext.setup.venvEngine ext.setup.venv3d ext.setup.venvConfirm ext.setup.installing
ext.setup.installed ext.setup.installFail ext.setup.3dConfirm ext.setup.3dDone ext.setup.noRender ext.setup.outHead ext.setup.outSettings ext.setup.mark.warn ext.setup.mark.missing
ext.setup.item.vscode_node ext.setup.item.ffmpeg ext.setup.item.ffmpeg_ass ext.setup.item.render_python ext.setup.item.render_versions ext.setup.item.extension
ext.setup.item.old_extension ext.setup.item.skill ext.setup.item.old_skill ext.setup.item.render ext.setup.item.gl3d ext.setup.item.blender
as.libPack.false_maria ext.first.lack ext.first.lackUpdated ext.first.lackRender ext.first.lackFfmpeg ext.first.sep ext.first.later ext.first.welcome ext.first.btnNew
an2.note an2.requested
bar.follow bar.follow.tipOn bar.follow.tipOff st.followOn st.followOff rm.status rm.noClip rm.noTrack rm.badPane rm.badLang rm.badCmd rm.notReady
srv.ui.noEditor srv.ui.timeout srv.op.unknown srv.op.noClip srv.op.noTake srv.op.noCut srv.op.noTrack srv.op.selected srv.op.noFx srv.op.ttsNoText srv.op.ttsBusy
srv.op.ttsNoLines srv.op.ttsNoPending srv.op.noVideoFile tts.tempo tts.tempo.tip tts.overlap tts.overlapTail mu.lyricsName mu.lyricsNote srv.mu.warnNoArgs srv.mu.warnClipCount srv.mu.warnSameGen
pl.tooMany.tip pl.imgEngine.default pl.imgEngine.project pl.engine.codex pl.engine.openai pl.imgModel.ph pl.imgQuality.default py.oa.maxRefs py.oa.quality
pl.engine.nanobanana pl.nbModel.ph pl.imgSize pl.nbSize.default py.nb.maxRefs py.nb.size pl.longVideo ext.setup.item.html html.noBrowser html.noPage html.loadFail html.jsError html.timeout ex.timeIn ex.timeIn.tip ex.stBadTime bake.on bake.off bake.run bake.paused bake.tipOn bake.tipOff bake.cfgOff bake.stOff bake.stOn src.cachePlay cache.barTip cache.baking ex.nocache ex.nocache.tip ex.cachedUsed src.cached src.take src.takeLoading py.an.u2netDownload an2.stemTrackPlaced srv.op.noStems srv.op.noAudioFile srv.op.stemsPlaced pl.vplay.tip pl.vseek.tip pl.vclose.tip pl.vplayFail
srv.badFormat srv.mu.hidden
'''.split())  # 最後の 1 行：format の名前を新しくした・古い名前は読むだけ（目で確かめた文）  # 2026-11-15〜16：絵のエンジン（OpenAI・作品ごとに決める）の 1 行・ためたコマの絵（fcache）とテイクの動画をプレビューで再生の 1 行（新しく足した文。目で確かめた）  # 2026-11-15 人の操作を API から・オート・使ってみた知らせの直し・Suno の歌詞の時刻の 3 行（新しく足した文。目で確かめた）。上から：Mittler 化（〜2026-11-13）・3D 強化（2026-11-13）の 3 行・パッケージ化（2026-11-13。プリセットの置き場・描く python の案内・「Mittler: 初期設定」）の 5 行・
#   公開の準備（2026-11-13。偽マリアのエフェクト集の見出し・入れた直後の知らせ）の 1 行・公開用の書き出し（2026-11-13。解析の知らせから作者の PC の名前を外した）の 1 行。どれも目で確かめた文
# アイコン化（2026-11-14）：ツールチップ・押せない理由（文字だけの所）で、絵文字を名前の代わりに使っていた文は、絵文字を外して言葉で呼ぶ形に直した（目で確かめた）
ICON_REWORD = set('''
bar.shy.tip meta.alignAll.tip as.close np.dur.tip sel.blRedraw.tip why.noLinkedSel ce.btn.latest.tip
'''.split())


def part_ja_same():
    r = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--verify', BASE + '^{commit}'], capture_output=True, text=True)
    if r.returncode:
        info(f'(d) 日本語：直す前のコミット {BASE} が無い（このクローンには入っていない）ので見ない'); return
    names = subprocess.run(['git', '-C', str(ROOT), 'ls-tree', '-r', '--name-only', BASE], capture_output=True, text=True, encoding='utf-8').stdout.split()
    src = []
    for n in names:
        if n.endswith(('.js', '.html', '.py', '.json')) and (n.startswith(('editor/', 'server/', 'pyengine/', 'tools/', 'effects_lib/', 'templates/')) or n in ('extension.js', 'package.json')):
            src.append(subprocess.run(['git', '-C', str(ROOT), 'show', f'{BASE}:{n}'], capture_output=True, text=True, encoding='utf-8', errors='replace').stdout)
    text = '\n'.join(src)
    flat = re.sub(r'\$\{[^`]*?\}', '\u0001', text)                  # テンプレートの ${…} は「何か」
    flat = re.sub(r"'\s*\+[^'\n]{0,80}?\+\s*'", '\u0001', flat)      # '…' + x + '…' も
    flat = flat.replace('\\n', '\n').replace('\\\\', '\\').replace('\\"', '"')
    # 2026-11-14 アイコン化：前のコードの絵文字（とその後ろの空白 1 つ）と、今の辞書のアイコンの印 {icon:…} を、どちらも外して比べる（差は絵文字のところだけのはず）
    flat = re.sub('(?:' + EMO.pattern + ')+[ 　]?', '', flat)
    bad, n = [], 0
    for k, v in D['ja'].items():
        if k == '_end' or not isinstance(v, str) or not JP.search(v) or k in COMPOSED or k in ICON_REWORD:
            continue
        n += 1
        v = ICON_MARK.sub('', v)
        pat = '.{0,200}?'.join(re.escape(p) for p in re.split(r'\{\w+\}', v))
        if not re.search(pat, flat, re.S):
            bad.append(f'{k}: {v[:40]}')
    # 2026-11-21：日本語の文をまとめて整えた（ですます調・言い回し）ので、「直す前のコードにそのままある」は落とす条件から外した（数を知らせるだけ）。
    # 文の意味は、整える前の辞書と 1 つずつ読み比べて確かめた。鍵と {名前} の差し込みが英日で合っていることは (a)(b) が見る
    info(f'(d) 日本語：ja.json の文 {n} 個のうち、最初にコードから辞書へ移したとき（{BASE}）の文のままのもの {n - len(bad)} 個・あとから言い回しを直したもの {len(bad)} 個')


# ---------------- 試しの作品（中身は英語） ----------------
def make_project(d):
    r = subprocess.run(node_cmd() + [str(ROOT / 'tools' / 'new_project.js'), str(d), '--title', 'i18n test', '--lang', 'en', '--no-git', '--json'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    if r.returncode:
        raise SystemExit('new_project 失敗: ' + r.stdout + r.stderr)
    ff = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i']
    subprocess.run(ff + ['testsrc2=size=320x180:rate=30:duration=3', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3:sample_rate=48000',
                         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(d / 'assets' / 'videos' / 'clip.mp4')], check=True)
    subprocess.run(ff + ['color=c=0x3060C0:s=320x180', '-frames:v', '1', str(d / 'assets' / 'images' / 'blue.png')], check=True)
    subprocess.run(ff + ['color=c=0xFFFFFF@0.0:s=64x64,format=rgba', '-frames:v', '1', str(d / 'assets' / 'overlays' / 'logo.png')], check=True)
    subprocess.run(ff + ['sine=frequency=660:duration=3:sample_rate=48000', '-ac', '2', str(d / 'assets' / 'bgm' / 'tone.wav')], check=True)
    subprocess.run(ff + ['sine=frequency=880:duration=1:sample_rate=48000', '-ac', '2', str(d / 'assets' / 'sfx' / 'beep.wav')], check=True)
    (d / 'characters.json').write_text(json.dumps({'characters': [{'id': 'kuro', 'name': 'Kuro', 'image': '', 'profile': 'A calm guide', 'color': '#7cc4ff',
        'tts': {'default_engine': 'voicevox', 'gemini': {'voice': 'Kore', 'style': ''}, 'voicevox': {'speaker': 2}}}]}, indent=1) + '\n', encoding='utf-8')
    tlf = d / f'{d.name}.cut.json'
    tl = json.loads(tlf.read_text(encoding='utf-8'))
    tl.update(width=320, height=180, fps=30, duration=8)
    T = {t['id']: t for t in tl['tracks']}
    T['t_sub_0']['clips'] = [{'id': 'sub_1', 'type': 'subtitle', 'start': 0.5, 'dur': 2, 'text': 'Hello, a test subtitle'}]
    T['t_video_0']['clips'] = [{'id': 'v_1', 'type': 'video', 'start': 0, 'dur': 3, 'src': 'assets/videos/clip.mp4', 'in': 0, 'cut': 'A'},
                               {'id': 'i_1', 'type': 'image', 'start': 3, 'dur': 2, 'src': 'assets/images/blue.png', 'cut': 'B'}]
    T['t_plan_0']['clips'] = [{'id': 'plan_01', 'type': 'plan', 'start': 5, 'dur': 2, 'label': 'Plan 1', 'start_frame': {'src': 'assets/images/blue.png', 'prompt': 'A classroom'},
                               'end_frame': {'prompt': ''}, 'video': {'prompt': 'turns around'}}]
    T['t_sfx_0']['clips'] = [{'id': 'a_1', 'type': 'audio', 'start': 0, 'dur': 1, 'src': 'assets/sfx/beep.wav', 'in': 0, 'gain': -6}]
    T['t_music_0']['clips'] = [{'id': 'a_2', 'type': 'audio', 'start': 0, 'dur': 3, 'src': 'assets/bgm/tone.wav', 'in': 0, 'gain': -12, 'fade_in': 0.5}]
    tl['tracks'].insert(0, {'id': 't_fx_0', 'name': 'Effects', 'kind': 'effect', 'clips': [
        {'id': 'fx_fade', 'type': 'effect', 'effect': 'fade', 'start': 0, 'dur': 5, 'params': {'fade_in': 0.5, 'fade_out': 0.5}},
        {'id': 'fx_sprite', 'type': 'effect', 'effect': 'sprite', 'start': 1, 'dur': 2, 'params': {'img': 'assets/overlays/logo.png', 'x': 160, 'y': 90, 't0': 1, 't1': 3, 'anim': 'pop', 'scale': 1}}]})
    tl['tracks'].insert(3, {'id': 't_tts_0', 'name': 'Kuro', 'kind': 'tts', 'character': 'kuro', 'clips': [
        {'id': 'tts_1', 'type': 'tts', 'character': 'kuro', 'start': 0.5, 'dur': 2, 'text': 'This is a test line.', 'takes': []}]})
    for m in tl['meta']:
        if m['kind'] == 'cuts':
            m['items'] = [{'label': 'A', 'start': 0, 'end': 3}, {'label': 'B', 'start': 3, 'end': 5}]
        if m['kind'] == 'notes':
            m['items'] = [{'start': 0, 'end': 3, 'text': 'test pattern'}]
    tlf.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    return tlf


class Server:
    def __init__(self, tlf, logf):
        env = dict(os.environ); env['MITTLER_NO_REVEAL'] = '1'; env.pop('MITTLER_LANG', None)
        self.log = open(logf, 'w', encoding='utf-8', errors='replace')
        self.p = subprocess.Popen(['cmd', '/c', str(ROOT / 'tools' / 'mittler.cmd'), 'serve', str(tlf), '--port', str(free_port()), '--render-python', RPY],
                                  stdout=subprocess.PIPE, stderr=self.log, env=env, text=True, encoding='utf-8', errors='replace')
        self.url = self.p.stdout.readline().strip()
        if not self.url.startswith('http://127.0.0.1:'):
            raise SystemExit('サーバーが起動しない: ' + self.url)
        self.token = re.search(r'token=(\w+)', self.url).group(1)
        self.base = self.url.split('/editor/')[0]

    def get(self, path):
        with urllib.request.urlopen(urllib.request.Request(self.base + path, headers={'X-Mittler-Token': self.token}), timeout=60) as r:
            return json.loads(r.read())

    def quit(self):
        try:
            urllib.request.urlopen(urllib.request.Request(self.base + '/api/quit', data=b'{}', method='POST', headers={'X-Mittler-Token': self.token}), timeout=10).read()
        except Exception as e:
            print('quit 失敗', e)
        try:
            self.p.wait(timeout=45)
        except subprocess.TimeoutExpired:
            print('サーバーが止まらない pid', self.p.pid)
        self.log.close()


# 画面に残っている日本語（作品の中身は見ない）
LEFT_JS = r"""() => {
  const JP = """ + JP_JS + r""";
  const skip = el => !el || el.closest('#langSel, #codeText, #codePanel pre, #codePanel textarea, #assetBody .txt, #assetBody .acell span, #assetBody .aname, #presetList, .presetName, #file');
  const out = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
  while ((n = w.nextNode())) { const p = n.parentElement; if (!p || ['SCRIPT', 'STYLE'].includes(p.tagName) || skip(p)) continue;
    const s = n.textContent.replace(/\s+/g, ' ').trim(); if (JP.test(s) && p.getClientRects().length) out.add((p.id || p.className || p.tagName) + '｜' + s.slice(0, 70)); }
  for (const el of document.querySelectorAll('[title],[placeholder],[aria-label],[data-why]')) { if (skip(el)) continue;
    for (const a of ['title', 'placeholder', 'aria-label', 'data-why']) { const v = el.getAttribute(a); if (v && JP.test(v)) out.add(a + '｜' + (el.id || el.className) + '｜' + v.slice(0, 70)); } }
  // VOICEVOX の話者の名前（このPCのエンジンが返す）は作品の外の中身なので見ない（いちばん上の「キャラ設定のまま」だけ見る）
  for (const o of document.querySelectorAll('option')) if (JP.test(o.textContent) && !skip(o) && !(o.parentElement.matches('[data-v=speaker]') && o.index > 0)) out.add('option｜' + o.textContent.slice(0, 50));
  return [...out]; }"""
# 画面に残っている絵文字・アイコンにならなかった印（作品の中身は見ない。見ないところは LEFT_JS と同じ）。文字と title・placeholder・aria-label・data-why・選ぶ欄
EMO_LEFT_JS = r"""() => {
  const E = """ + EMO_JS + r""";
  const skip = el => !el || el.closest('#codeText, #codePanel pre, #codePanel textarea, #assetBody .txt, #assetBody .acell span, #assetBody .aname, #presetList, .presetName, #file');
  const out = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
  while ((n = w.nextNode())) { const p = n.parentElement; if (!p || ['SCRIPT', 'STYLE'].includes(p.tagName) || skip(p)) continue;
    const s = n.textContent.replace(/\s+/g, ' ').trim(); if (E.test(s)) out.add((p.id || p.className || p.tagName) + '｜' + s.slice(0, 70)); }
  for (const el of document.querySelectorAll('[title],[placeholder],[aria-label],[data-why]')) { if (skip(el)) continue;
    for (const a of ['title', 'placeholder', 'aria-label', 'data-why']) { const v = el.getAttribute(a); if (v && E.test(v)) out.add(a + '｜' + (el.id || el.className) + '｜' + v.slice(0, 70)); } }
  return [...out]; }"""


def wait_ready(pg):
    pg.wait_for_function('() => window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl && window.MITTLER_EDITOR.fxReady', timeout=90000)
    pg.wait_for_function("() => document.getElementById('exportBtn') && !document.getElementById('exportBtn').hidden", timeout=60000)
    pg.wait_for_timeout(600)


def esc_all(pg):
    pg.keyboard.press('Escape')
    pg.evaluate("""() => { for (const id of ['durMenu', 'sizeMenu', 'snapMenu']) { const e = document.getElementById(id); if (e) e.hidden = true; }
      const c = document.getElementById('ctxMenu'); if (c) c.remove(); const x = document.getElementById('exportPanel'); if (x) x.hidden = true; }""")


def scenes(pg, shot=None, emo=None):
    """画面を順に開いて、場面ごとに残っている日本語を集める（shot があればスクリーンショットも。emo（dict）があれば、残っている絵文字も集める）"""
    S = 'MITTLER_EDITOR'
    left = {}

    def take(name, wait=300):
        pg.wait_for_timeout(wait)
        got = pg.evaluate(LEFT_JS)
        if got:
            left[name] = got
        if emo is not None:
            e = pg.evaluate(EMO_LEFT_JS)
            if e:
                emo[name] = e
        if shot:
            shot(name)

    def step(name, fn):
        try:
            fn()
        except Exception as e:  # 1 つの場面が開けなくても続ける（開けなかったことは知らせる）
            left[name] = ['（場面を開けなかった）' + str(e).split('\n')[0][:120]]

    pg.evaluate(f"() => {{ if (window.MITTLER_ASSETS) MITTLER_ASSETS.setOpen(true); {S}.seek(1.5); }}")
    take('01 whole', 800)
    for cid in ('sub_1', 'fx_fade', 'fx_sprite', 'v_1', 'i_1', 'plan_01', 'tts_1', 'a_1', 'a_2'):
        step('02 panel ' + cid, lambda cid=cid: (pg.evaluate(f"() => {{ document.querySelector('#paneTabs [data-p=sel]').click(); {S}.select('{cid}'); }}"),
                                                 take('02 panel ' + cid)))
    step('02 track', lambda: (pg.evaluate(f"() => {{ {S}.select(null); document.querySelector('#headList .head[data-track=t_tts_0] .nm').click(); }}"), take('02 track')))
    step('03 color', lambda: (pg.evaluate(f"() => {{ {S}.select(null); document.querySelector('#paneTabs [data-p=grade]').click(); }}"), take('03 color')))
    step('03 meta', lambda: (pg.evaluate("() => document.querySelector('#paneTabs [data-p=meta]').click()"), take('03 meta')))
    pg.evaluate("() => document.querySelector('#paneTabs [data-p=sel]').click()")
    for tab in pg.evaluate("() => [...document.querySelectorAll('#assetTabs [data-tab]')].map(b => b.dataset.tab)"):
        def f(tab=tab):
            pg.evaluate(f"() => document.querySelector('#assetTabs [data-tab={tab}]').click()"); pg.wait_for_timeout(300)
            pg.evaluate("() => { const r = document.querySelector('#assetBody .arow, #assetBody .acell'); if (r) r.click(); }")
            take('04 assets ' + tab, 400)
        step('04 assets ' + tab, f)
    for bid in ('durBtn', 'sizeBtn', 'snapMenuBtn'):
        step('05 menu ' + bid, lambda bid=bid: (esc_all(pg), pg.click('#' + bid), take('05 menu ' + bid)))
    esc_all(pg)

    def exp(btn, name):
        pg.click(btn); take(name, 700)
        pg.evaluate("() => { const d = document.querySelector('#exportPanel details'); if (d) d.open = true; }")
        pg.evaluate("() => { const r = document.querySelector('#exportPanel input[name=xr][value=part]'); if (r) { r.checked = true; r.dispatchEvent(new Event('change')); } }")
        take(name + ' (advanced)')
        esc_all(pg)
    step('06 export', lambda: exp('#exportBtn', '06 export'))
    step('06 master', lambda: exp('#masterBtn', '06 master'))

    def ctx_clip():
        pg.evaluate("() => { document.getElementById('lanesWrap').scrollLeft = 0; }")
        pg.click('#laneList .clip[data-id=a_2]', button='right', position={'x': 20, 'y': 8}); take('07 context menu (analyze)')
        esc_all(pg); pg.mouse.click(5, 5)
    step('07 context clip', ctx_clip)

    def ctx_cut():
        pg.click('#laneList .item.cuts', button='right', position={'x': 20, 'y': 8}); take('07 context menu (cuts)')
        esc_all(pg); pg.mouse.click(5, 5)
    step('07 context cut', ctx_cut)

    def ann():
        pg.click('#annotBtn'); pg.wait_for_timeout(400); take('08 annotate'); pg.keyboard.press('Escape')
    step('08 annotate', ann)

    def multi():
        pg.evaluate(f"() => {{ {S}.select('v_1'); {S}.select('a_1', true); }}"); take('09 multi')
        pg.keyboard.press('c'); take('09 cut tool'); pg.keyboard.press('v'); pg.evaluate(f"() => {S}.select(null)")
    step('09 tools', multi)

    def newp():
        pg.click('#newProjBtn'); take('10 new project', 500); pg.keyboard.press('Escape')
    step('10 new project', newp)

    def code():
        pg.evaluate("() => openCode('fade')"); pg.wait_for_timeout(500); take('11 code'); pg.evaluate("() => { document.getElementById('codePanel').hidden = true; }")
    step('11 code', code)

    def notes():
        pg.keyboard.press('Control+s'); take('12 status (ctrl+s)')
        pg.evaluate("() => MITTLER_EDITOR.select('sub_1')"); pg.keyboard.press('Control+z'); take('12 status (undo)')
    step('12 status', notes)
    return left


def part_english(br, srv, tlf):
    # 新しいブラウザ（覚えた言葉なし）・URL に lang なし・サーバーは既定 → 英語
    ctx = br.new_context(viewport={'width': 1500, 'height': 900}, color_scheme='dark'); pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(srv.url); wait_ready(pg)
    lang = pg.evaluate('() => [MITTLER_I18N.lang, document.documentElement.lang]')
    check(lang == ['en', 'en'], f'(c) 英語：既定は英語（設定も覚えた言葉も URL も無いとき）{lang}')
    emo = {}
    left = scenes(pg, emo=emo)
    uniq = {}  # 同じものは最初の場面だけ
    for k, v in left.items():
        for x in v:
            uniq.setdefault(x, k)
    check(not left, f'(c) 英語：画面に日本語が残らない（場面 {len(left)} か所・{len(uniq)} 種類）' + ''.join(f'\n       {x}　〔{k}〕' for x, k in list(uniq.items())[:60]))
    check_emoji('英語', emo)
    check(not errs, '(c) 英語：ページのエラーなし' + ('' if not errs else ': ' + ' | '.join(errs[:3])))
    ctx.close()


def check_emoji(name, emo):
    uniq = {}
    for k, v in emo.items():
        for x in v:
            uniq.setdefault(x, k)
    check(not emo, f'(g) アイコン（{name}）：どの場面にも、絵文字と、アイコンにならなかった印 {{icon:…}} が残らない（文字・title・placeholder・aria-label・data-why。場面 {len(emo)} か所・{len(uniq)} 種類）'
          + ''.join(f'\n       {x}　〔{k}〕' for x, k in list(uniq.items())[:40]))


def part_japanese(br, srv):
    # 日本語の画面でも同じ場面を開いて、絵文字・印が残らないか（日本語の言葉そのものは (d) で見る）
    ctx = br.new_context(viewport={'width': 1500, 'height': 900}, color_scheme='light'); pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(srv.url.replace('?token=', '?lang=ja&token=')); wait_ready(pg)
    emo = {}
    scenes(pg, emo=emo)
    check_emoji('日本語', emo)
    pg.goto(srv.url.replace('?token=', '?lang=en&token=')); wait_ready(pg)  # サーバーの言葉を英語に戻す（あとの確かめのため）
    check(not errs, '(g) 日本語：ページのエラーなし' + ('' if not errs else ': ' + ' | '.join(errs[:3])))
    ctx.close()


def part_switch(br, srv, tlf, state_json):
    tl0 = tlf.read_text(encoding='utf-8')
    ctx = br.new_context(viewport={'width': 1500, 'height': 900}, color_scheme='dark'); pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(srv.url); wait_ready(pg)
    # 開いている窓（書き出し）・右の欄・ツールチップ・上の知らせ：切り替えたらすぐ
    pg.evaluate("() => MITTLER_EDITOR.select('sub_1')"); pg.keyboard.press('Control+s'); pg.wait_for_timeout(200)
    pg.click('#exportBtn'); pg.wait_for_selector('#xName')
    pg.fill('#xName', 'keep_me'); pg.evaluate("() => { const r = document.querySelector('#exportPanel input[name=xq][value=\"2\"]'); r.checked = true; r.dispatchEvent(new Event('change')); }")
    before = pg.evaluate("() => [document.querySelector('#exportPanel .xhead b').textContent, document.getElementById('undo').title, document.getElementById('status').textContent, document.getElementById('sel').innerText.slice(0, 200)]")
    pg.click('#langSel [data-lang=ja]'); pg.wait_for_timeout(300)
    after = pg.evaluate("() => [document.querySelector('#exportPanel .xhead b').textContent, document.getElementById('undo').title, document.getElementById('status').textContent, document.getElementById('sel').innerText.slice(0, 200)]")
    kept = pg.evaluate("() => [document.getElementById('xName').value, (document.querySelector('#exportPanel input[name=xq]:checked') || {}).value, !document.getElementById('exportPanel').hidden]")
    jp = [bool(JP.search(x)) for x in after]
    check(not any(JP.search(x) for x in before[:3]) and all(jp), f'(e) 切替：日本語にすると、開いている窓・ツールチップ・上の知らせ・右の欄がすぐ切りかわる（{[x[:16] for x in before]} → {[x[:16] for x in after]}）')
    check(kept == ['keep_me_draft', '2', True], f'(e) 切替：開いている窓の入力（ファイル名・品質）は残る {kept}')
    # 再読み込み：このブラウザが覚えている。サーバーも同じ言葉（/api/lang）
    pg.reload(); wait_ready(pg)
    srv_lang = srv.get('/api/lang')
    check(pg.evaluate('() => MITTLER_I18N.lang') == 'ja' and pg.inner_text('#exportBtn').strip().startswith('書き出し') and srv_lang.get('lang') == 'ja',
          f"(e) 切替：再読み込みしても日本語（{pg.inner_text('#exportBtn').strip()}・サーバー {srv_lang}）")
    # URL の &lang= が勝つ
    pg.goto(srv.url.replace('?token=', '?lang=en&token=')); wait_ready(pg)
    check(pg.evaluate('() => MITTLER_I18N.lang') == 'en' and pg.inner_text('#exportBtn').strip() == 'Export', f"(e) 切替：URL の &lang=en が覚えた言葉より勝つ（{pg.inner_text('#exportBtn').strip()}）")
    # 別のブラウザ（覚えた言葉なし）：サーバーの「決めた言葉」（切り替えで決めた）に従う
    ctx2 = br.new_context(viewport={'width': 1280, 'height': 860}); pg2 = ctx2.new_page(); pg2.goto(srv.url); wait_ready(pg2)
    check(pg2.evaluate('() => MITTLER_I18N.lang') == 'ja', '(e) 切替：切り替えで決めた言葉は、ほかのブラウザ（同じサーバー）でも使う')
    pg2.click('#langSel [data-lang=en]'); pg2.wait_for_timeout(300)
    check(pg2.inner_text('#exportBtn').strip() == 'Export' and srv.get('/api/lang').get('lang') == 'en', '(e) 切替：英語に戻すと、すぐ英語・サーバーも英語')
    ctx2.close()
    pg.wait_for_timeout(1500)  # state.json の書き込み（0.5 秒ごと）を待つ
    tl1 = tlf.read_text(encoding='utf-8')
    st = {}
    try:
        st = json.loads(state_json.read_text(encoding='utf-8'))
    except Exception:
        pass
    check(tl0 == tl1 and 'lang' not in tl1 and not any('lang' in k.lower() for k in st), f'(e) 切替：タイムライン・state.json に言葉を書かない（タイムラインは同じ {tl0 == tl1}・state.json の鍵 {[k for k in st if "lang" in k.lower()]}）')
    check(not errs, '(e) 切替：ページのエラーなし' + ('' if not errs else ': ' + ' | '.join(errs[:3])))
    ctx.close()


def part_layout(br, srv):
    for w in (1600, 1280, 900):
        ctx = br.new_context(viewport={'width': w, 'height': 860}, color_scheme='dark'); pg = ctx.new_page()
        pg.goto(srv.url.replace('?token=', '?lang=en&token=')); wait_ready(pg)
        pg.evaluate("() => MITTLER_EDITOR.select('v_1')"); pg.wait_for_timeout(300)
        r = pg.evaluate("""() => { const bar = document.getElementById('bar').getBoundingClientRect();
          const els = [...document.querySelectorAll('#bar > button, #bar > span > button, #bar > .zoom, #bar > #file')].filter(e => e.offsetWidth > 0).map(e => [e.id || e.className, e.getBoundingClientRect()]);
          const out = els.filter(([, b]) => b.right > bar.right + 1 || b.left < bar.left - 1 || b.height > 34).map(x => x[0]);
          const lap = []; for (let i = 0; i < els.length; i++) for (let j = i + 1; j < els.length; j++) { const a = els[i][1], b = els[j][1]; if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) lap.push(els[i][0] + '×' + els[j][0]); }
          const tp = document.getElementById('stage').getBoundingClientRect();
          const tin = [...document.querySelectorAll('#transport button, #transport select, #cutNow')].filter(e => e.offsetWidth > 0 && (e.getBoundingClientRect().right > tp.right + 1 || e.getBoundingClientRect().left < tp.left - 1)).map(e => e.id);
          const cut = [...document.querySelectorAll('#bar button, #cutbar button, #paneTabs button, #assetTabs button, #transport button, #sel .btns button')].filter(e => e.offsetWidth > 0 && !e.closest('#file') && e.scrollWidth > e.clientWidth + 1).map(e => (e.id || e.dataset.act || e.textContent).slice(0, 20));
          const inspector = document.getElementById('inspector'), insOver = inspector.scrollWidth > inspector.clientWidth + 1;
          return { out, lap, tin, cut, insOver, barH: bar.height, sx: document.documentElement.scrollWidth - innerWidth }; }""")
        check(not r['out'] and not r['lap'] and not r['tin'] and not r['cut'] and not r['insOver'] and r['barH'] <= 44 and r['sx'] <= 0,
              f"(f) 崩れ（英語・幅 {w}）：上のバー・再生の操作がはみ出さない・重ならない・ボタンの字が切れない・右の欄に横スクロールが出ない（バーの高さ {r['barH']:.0f}px）{r['out']} {r['lap']} {r['tin']} {r['cut']} {r['insOver']}")
        ctx.close()


def part_shots(br, srv):
    SHOTS.mkdir(parents=True, exist_ok=True)
    for lang, schemes, widths in (('en', ('dark', 'light'), (1600, 1280, 900)), ('ja', ('dark',), (1280,))):
        for scheme in schemes:
            for w in widths:
                ctx = br.new_context(viewport={'width': w, 'height': 900}, color_scheme=scheme, device_scale_factor=1); pg = ctx.new_page()
                pg.goto(srv.url.replace('?token=', f'?lang={lang}&token=')); wait_ready(pg)
                full = w == 1280  # 全部の場面は 1280 だけ。ほかの幅は全体と書き出しの窓
                def shot(name, lang=lang, scheme=scheme, w=w):
                    if full or name.startswith(('01', '06')):
                        pg.screenshot(path=str(SHOTS / f'{lang}_{scheme}_w{w}_{re.sub(r"[^A-Za-z0-9_]+", "_", name)}.png'))
                scenes(pg, shot)
                ctx.close()
    info(f'スクリーンショット：{SHOTS}')


def main(work):
    part_dicts()
    part_keys()
    part_ja_same()
    tlf = make_project(work / 'i18n_en')
    srv = Server(tlf, work / 'server.log')
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            part_english(br, srv, tlf)
            part_layout(br, srv)
            part_japanese(br, srv)
            part_switch(br, srv, tlf, tlf.parent / '.mittler' / 'state.json')
            if SHOTS:
                part_shots(br, srv)
            br.close()
    finally:
        srv.quit()


w = opt('--work')
if w:
    Path(w).mkdir(parents=True, exist_ok=True); main(Path(w))
else:
    with tempfile.TemporaryDirectory(prefix='mittler_smoke_i18n_') as td:
        main(Path(td))
print('ALL OK' if not fails else f'FAIL {len(fails)}')
sys.exit(1 if fails else 0)
