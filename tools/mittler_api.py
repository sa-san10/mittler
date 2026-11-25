"""Claude Code（編集画面の外）から、開いている編集画面のサーバーに頼む。Python の標準だけ。
（前の名前 tools/cc_api.py でも同じものが動く：今までの作品の CLAUDE.md・手順のための受け口）
作品のフォルダからは中継 `python .mittler/api.py . <コマンド>`（引数は同じ）。どのコマンドも --json で結果を JSON（1 行）で出す。終わりの番号は 0＝できた・1＝できなかった。
2026-11-15：人が編集画面で押していた操作を、Suno の採用と H3 の生成のほかは全部ここから頼めるようにした。
タイムラインを書きかえるものは、ボタンと同じ計算（editor/ops.js）をサーバーがして、ファイルを書く。
開いている編集画面は「外の直し」として読み直す（Ctrl+Z で戻せる。オートなら直した所へ再生位置が飛ぶ）。一覧と例は docs/スターターガイド（AI用）.md の 7.53。

■ 状態
  status                                  サーバーが動いているか・ジョブ係・ジョブの数
  jobs                                    生成のジョブの一覧
■ 生成（🎬 動画化予定。生成は外に送る・計算機を使うので、先にユーザーに一言）
  image <予定> start_frame|end_frame [--engine codex|openai|nanobanana] [--model M] [--quality Q]
                                          開始・終了の絵を生成（エンジンは絵の欄の engine → 設定 mittler.image.engine → Codex。
                                          openai＝OpenAI の Image API：モデルは絵の欄の model → 設定 → gpt-image-2.5-sunburst。
                                          nanobanana＝Nano Banana（Gemini）：モデルは → gemini-3-pro-image、--quality に解像度 1K・2K・4K（既定 2K）。--engine などはこの 1 回だけ）
  video <予定>… | --all [--dry] [--draft [--steps 10]]   動画化（H3。Colab の許可ボタンは人が押す）
  gen-image <出力> (--prompt 文 | --prompt-file F) [--ref 絵]… [--engine E] [--size WxH] [--background transparent] [--model M] [--quality Q]
                                          素材の絵を 1 枚作る（動画化予定に限らない：グレイン・テクスチャ・一部だけ動かす絵・エフェクトの中の絵・モックなど）。
                                          出力は作品からの相対（assets/images/gen/… か work/mock/…。上書きしない）。エンジンは --engine → 作品の settings.image_engine
                                          （無ければ断る：先にユーザーに聞いて書く）。--size・--background は OpenAI だけ（Codex には文で伝える。Nano Banana は --size を縦横の比に、
                                          --background transparent は文で）。Nano Banana の --quality は解像度 1K・2K・4K。参照画像は 14 枚まで。終わるまで待つ。編集画面は要らない
  frame-take <予定> start_frame|end_frame <テイク>          絵のテイクを選ぶ（その絵を使う）
  video-take <予定> <テイク>               動画のテイクを選ぶ（採用の前でも、その場所に映る）
  adopt <予定> [<テイク>]                  採用：映像トラックの同じ時間に映像クリップを置く（採用済みなら差しかえる）
  adopt-all [--track <予定のトラック>] [--latest]          選んでいるテイク（--latest：いちばん新しいテイク）を全部採用
■ セリフの声（Gemini TTS は文字を Google に送る。先にユーザーに一言。VOICEVOX はこの PC）
  tts <セリフ>… [--tempo 1.15]             1 本ずつ生成して新しいテイクにする（作り直しも同じ。前のテイクは残る。--tempo：生成のあとの速さをクリップの tempo に書いてから）
                                          重なり：声の長さで伸びて同じトラックの次のセリフに重なったら、結果の overlaps と知らせに出る
  tts-all [--regen] [--wait]               未生成のセリフを全部（--regen：文のあるもの全部を作り直す）。時間の順に 1 本ずつ
  tts-status [--wait] / tts-stop          まとめての進み具合・止める（今の 1 本のあとで）
  tts-take <セリフ> <テイク>               テイクを選ぶ
  subs-from-lines [<セリフ>…]              セリフから字幕を作る（前に作った字幕は時間を合わせ直す。手で直した文はそのまま）
■ 書き出し
  export [--step 2|4] [--scale 0.5|0.25] [--from S] [--to E] [--name N] [--jobs N] [--no-proxy] [--no-cache] [--wait]
                                          書き出し（--step：下書き＝コマを間引く）。既定は窓の初めの値（最終・全部・作品の名前と日時・プレビューに使う）
  master [--upscale none|anime|real] [--force] [--fresh] [--jobs N] [--from S] [--to E] [--name N] [--wait]
                                          マスター書き出し（画質を言わなければ、マスターの窓で選ばれている画質）
  export-status [--wait] / export-cancel  進み具合（--wait：終わるまで待って進み具合を出す）・止める
  master-info / master-cache-clear        マスターの設定・道具・キャッシュ／キャッシュを空にする
  still [--at 秒]                          1 コマを PNG（output/stills/。--at が無ければ編集画面の今の時刻）
  proxy <output/…mp4>                      再生用の動画（WebM）を作ってプレビューに使う
■ 映像・音
  place-video <素材> [--at 秒] [--track <id>]  動画を映像トラックに置く（音があれば取り出してリンクして置く）
  video-audio <映像クリップ>…              動画の音を置く（取り出して「動画の音」のトラックにリンクして置く）
  onbeat <映像クリップ> [--set 名前=値]… [--adv JSON]   音ハメ（自動）。名前は min・max・lam・jerk・slip・thr・smooth・half・end（無ければ欄の値）
  analyze <クリップ> <種類> [--wait]        解析（音＝beats・transcribe・stems、セリフ＝transcribe、映像＝pose・mask、画像＝pose・mask・cutout）
  stems-place <音のクリップ> <WAV>…        ステム（Suno の audio-stems で取った歌・伴奏・楽器ごとの WAV など）をミュートした音のトラックに置く（名前はファイルの名前）
  analyses [--wait]                        解析の一覧
■ カット編集（道具のバーと同じ。🔗 連動はオン＝動画とその音も一緒。--no-link で外す）
  split <秒> [<クリップ>…]                 分ける（クリップを言わなければ、見えているトラックでその時刻にかかるもの全部）
  delete <クリップ>… / ripple <クリップ>…   消す／リップル削除（消して同じトラックの後ろを詰める）
  gaps [<クリップ>…] [--track <id>]        隙間を詰める（そのクリップのトラック・そのトラック）
  stretch <映像クリップ>… [--len next|plan|<秒>] [--how hold|slow]    ⟷ 伸ばす（次のクリップの頭まで・予定の長さ・秒数へ。最後のコマで止める／ゆっくり）
  job-cancel <ジョブ>                       生成のジョブを止める（編集画面の「止める」）
  plan-resolve <予定> start_frame|end_frame|video    プロンプトの参照（@import）を読んで、送るものと間違いを見る（参照のチップと同じ）
■ カットの段（ラベルで指す）
  cut-first / cut-lane cuts|notes          最初のカット（全体）／カット・ト書きの段を作る
  cut-split <秒> [--label L]               分ける（新しいラベルは今のラベルから）
  cut-join <ラベル> prev|next / cut-remove <ラベル>      つなぐ／消す（隣に吸わせる）
  cut-rename <ラベル> <新しいラベル>        ラベルを変える（参照しているクリップの cut も）
  cut-edge <ラベル> start|end <秒>          境目を動かす（隣のカットも一緒）
  cut-align [<ラベル>…]                     映像をカットに合わせる（ラベルが無ければ ⚠ のもの全部）
  cut-from-clip <クリップ>                  クリップの範囲をカットにする
  cuts-on-adopt on|off                     採用するとき、その範囲をカットにする
■ 部品・キャラ・作品
  effects                                  作品のエフェクトと、部品の置き場にあって作品にまだ無いもの
  effect-add <名前>                        部品の置き場から作品の effects/ に入れる
  presets / preset-add <id> [--overwrite]  キャラのプリセットの一覧／作品に入れる
  blender-clear <クリップ>                  Blender の 3D のためた絵を消す
  frame-cache [clear]                      書き出し・プレビューでためたコマの絵（work/cache/frames）の数と大きさ／全部消す
  new-project <置く親のフォルダ> <名前> [--title T] [--width W --height H --fps F --duration D] [--lang ja|en] [--no-git] [--no-open]
                                          新しい作品（編集画面の「＋ 新規」と同じ。VS Code の中なら開く）
■ 🎵 Suno（Suno を呼ぶのは AI。採用＝クレジットの OK は人）
  music [--pending] [--json] / music-take <クリップ> --sidecar <JSON> | --take t<n> --src <音>
■ 画面の見える操作（作品は変えない。編集画面が開いていること）：ui <操作> [引数]
  ui play | pause | toggle | seek <秒> | step <コマ> | select <クリップ>… [--seek] | select --none | select-track <トラック>
  ui pane clip|color|meta | zoom <px/秒> | fit | scroll <秒> | lang en|ja | open-export | open-master | close-export
  ui reload | undo | redo | follow on|off | state
決まり：
- 編集画面（その作品の *.cut.json を VS Code で開いたもの）が開いていること。サーバーは起動すると作品の状態フォルダ（.mittler/。今までの作品は .claude-cut/）の server.json（ポート・トークン）を書く。
  無い・古い（つながらない）なら「編集画面を開いて（開いていればウィンドウの再読み込み）」と出る。
- 生成（Codex・H3・Gemini TTS）・外に送ることは、API で頼めても、先にユーザーに一言（AI の決まりは変わらない）。作業のたびのコミット（プッシュはしない。AI 用ガイドの 4.5）も今までどおり。
- 頼む前に、プロンプト・文などはタイムラインのファイルに書いておく（サーバーはタイムラインのクリップを使う）。work/jobs/ を手で書かない。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.dont_write_bytecode = True  # Mittler の置き場（配布版は拡張のフォルダ）に __pycache__ を書かない
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pyengine'))
from mittler.names import TOKEN_HEADER, state_dir  # noqa: E402（名前と古い名前の互換の1か所。標準ライブラリだけ）

ACTIVE = {'queued', 'running', 'waiting'}
EXPORT_BUSY = {'preparing', 'rendering', 'muxing', 'proxy', 'cancelling'}


def die(msg):
    sys.exit('mittler_api: ' + msg)


class Api:
    def __init__(self, proj):
        f = state_dir(proj) / 'server.json'  # .mittler/（今までの作品は .claude-cut/）
        if not f.exists():
            die(f'編集画面のサーバーが見つからない（{f} が無い）。この作品の *.cut.json を VS Code で開いて（開いていればウィンドウの再読み込み）')
        self.info = json.loads(f.read_text(encoding='utf-8'))
        self.base = f"http://127.0.0.1:{self.info['port']}"
        self.proj = proj

    def call(self, path, body=None, timeout=60):
        req = urllib.request.Request(self.base + path, method='POST' if body is not None else 'GET',
                                     data=None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8'),
                                     headers={TOKEN_HEADER: self.info['token'], 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            txt = e.read().decode('utf-8', 'replace')
            try:
                j = json.loads(txt)
                if isinstance(j, dict) and 'error' in j and e.code != 403:
                    return dict(j, ok=False)
            except ValueError:
                pass
            die(f'{path} → HTTP {e.code} {txt[:300]}（server.json が古いかも。ウィンドウの再読み込み）')
        except OSError as e:
            die(f'{self.base} につながらない（{e}）。編集画面が閉じている：この作品の *.cut.json を開いて（開いていればウィンドウの再読み込み）')


def plans(tl):
    return {c['id']: c for t in tl.get('tracks', []) if t.get('kind') == 'plan' for c in t.get('clips', [])}


def music_list(api, pending_only, as_json):
    """🎵 音のクリップのうち music のあるもの：状態（生成待ち・採用待ち・採用済み…）、テイク、採用待ちなら取ってくるテイクと置く名前"""
    tl = api.call('/api/timeline').get('timeline') or {}
    dl = [d for d in api.call('/api/music').get('deliveries', []) if not d.get('applied')]
    out = []
    for t in tl.get('tracks', []):
        for c in t.get('clips', []):
            m = c.get('music')
            if c.get('type') != 'audio' or not isinstance(m, dict):
                continue
            takes = list(m.get('takes') or [])
            takes += [d['data'] for d in dl if d.get('clip') == c['id'] and d.get('kind') == 'take' and d.get('data')]  # 編集画面がまだ入れていない納品
            ad = m.get('adopt') or None
            safe = ''.join(ch if ch.isalnum() and ch.isascii() or ch in '_-' else '_' for ch in c['id'])
            st = ('採用待ち（ダウンロード待ち）' if ad else '生成待ち' if (m.get('prompt') or m.get('lyrics') or m.get('style') or '').strip() and not takes
                  else 'プロンプトなし' if not takes else '採用済み' if m.get('adopted') and c.get('src') else 'テイクあり（未採用）')
            row = {'clip': c['id'], 'label': c.get('label', ''), 'track': t.get('name', ''), 'start': c.get('start'), 'dur': c.get('dur'), 'state': st,
                   'src': c.get('src'), 'music': {k: m.get(k) for k in ('prompt', 'lyrics', 'title', 'style', 'instrumental', 'duration') if m.get(k) not in (None, '')},
                   'takes': [{k: x.get(k) for k in ('id', 'suno_id', 'song_url', 'title', 'dur', 'src') if x.get(k) is not None} for x in takes], 'adopted': m.get('adopted')}
            if ad:
                k = next((x for x in takes if x.get('id') == ad.get('take')), {})
                row['adopt'] = dict(ad, suno_id=k.get('suno_id'), song_url=k.get('song_url'), format=ad.get('format') or 'wav',
                                    file=f"assets/music/{safe}_{ad.get('take')}.{ad.get('format') or 'wav'}")
            if not pending_only or st in ('生成待ち', '採用待ち（ダウンロード待ち）'):
                out.append(row)
    if as_json:
        print(json.dumps({'root': tl.get('root', '.'), 'clips': out}, ensure_ascii=False, indent=1))
        return
    if not out:
        print('（' + ('生成待ち・採用待ちの曲は無い' if pending_only else '🎵 Suno の曲のクリップ（音のクリップの music）は無い') + '）')
    for r in out:
        print(f"{r['clip']}「{r['label']}」（{r['track']}・{r['start']}〜 {r['dur']} 秒）：{r['state']}" + (f"・音 {r['src']}" if r['src'] else ''))
        if r['music']:
            print('  music: ' + json.dumps(r['music'], ensure_ascii=False))
        for k in r['takes']:
            print(f"  {k.get('id')}：{k.get('title', '')}・{k.get('dur', '?')} 秒・{k.get('song_url', '')}" + (f"・ファイル {k['src']}" if k.get('src') else '・ファイルなし'))
        if r.get('adopt'):
            a = r['adopt']
            print(f"  → 採用待ち：{a.get('take')}（Suno {a.get('suno_id')}）を audio-download（format {a['format']}）で取って、素材の根の {a['file']} に置き、"
                  f"music-take {r['clip']} --take {a.get('take')} --src {a['file']}")


def out(a, r, text=None):
    """結果を出して終わる：--json なら JSON の 1 行、無ければ知らせの文（無ければ JSON）。ok でなければ終わりの番号 1"""
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        msg = text or r.get('message') or r.get('error')
        print(msg if msg else json.dumps(r, ensure_ascii=False, indent=1))
    sys.exit(0 if r.get('ok', True) else 1)


def progress(msg):
    print(msg, file=sys.stderr, flush=True)


def wait_export(api, a):
    """書き出しが終わるまで待つ（進み具合を 2 秒ごとに標準エラーへ）→ 最後の状態"""
    last = ''
    while True:
        j = api.call('/api/export')
        if j.get('state') not in EXPORT_BUSY:
            return j
        line = f"{j.get('state')} {j.get('phase') or ''} {j.get('done', 0)}/{j.get('total', 0)} コマ・{j.get('sec', 0)} 秒".replace('  ', ' ')
        if line != last:
            progress('PROGRESS ' + line)
            last = line
        time.sleep(2)


def export_result(j):
    r = {k: j.get(k) for k in ('state', 'name', 'master', 'from', 'to', 'jobs', 'draft', 'step', 'scale', 'result', 'error', 'warning', 'proxyError', 'proxyApplied', 'cfg', 'stop', 'cached', 'total') if j.get(k) is not None}
    r['ok'] = j.get('state') in ('done', 'idle') or j.get('state') in EXPORT_BUSY
    if j.get('state') == 'done' and j.get('result'):
        r['message'] = f"できた：{j['result'].get('path')}（{j['result'].get('bytes', 0) / 1e6:.1f} MB・SHA {str(j['result'].get('sha256', ''))[:12]}…）" + (f"・プレビュー {j['result'].get('proxy')}" if j['result'].get('proxy') else '') +             (f"・ためた絵を使ったコマ {j['cached']}/{j.get('total')}" if j.get('cached') else '')
    elif j.get('state') == 'error':
        r['ok'] = False
        r['message'] = '失敗：' + str(j.get('error', ''))[-600:]
    elif j.get('state') == 'cancelled':
        r['ok'] = False
        r['message'] = '止めた'
    return r


def parse_val(v):
    if v in ('true', 'false'):
        return v == 'true'
    try:
        return float(v)
    except ValueError:
        return v


def project_timeline(proj):
    """作品のタイムライン（<フォルダ名>.cut.json があればそれ、無ければ *.test.cut.json でないもの 1 つ）"""
    c = proj / f'{proj.name}.cut.json'
    if c.is_file():
        return c
    fs = sorted(f for f in proj.glob('*.cut.json') if not f.name.endswith('.test.cut.json'))
    return fs[0] if fs else None


CHECK_IMAGE = ('使う前に、この絵を開いて確かめること：人物の配置（人数・位置・大きさ・参照どおりか）・手と指（1 つずつ拡大して本数を数える）・'
               '向き（顔・体・視線・左右・反転）。まちがいがあれば使わずに作り直す（AI 用ガイドの 0）')


def gen_image(a, proj):
    """素材の絵を 1 枚（部分的な素材・フィルムグレイン用の絵・一部だけ動かす絵・エフェクトの中で使う絵などにも、積極的に使ってよい）。
    エンジンは --engine（この 1 枚だけ）→ 作品の settings.image_engine（ユーザーに最初に聞いて決めた既定）。Codex は作品の Codex の会話（work/codex-session.json）を続ける"""
    if len(a.args) != 1 or not (a.prompt or a.prompt_file):
        die('gen-image <出力（作品からの相対。例 assets/images/gen/grain_01.png）> --prompt 文 | --prompt-file F [--ref 絵]… [--size WxH] [--background transparent]')
    tlf = project_timeline(proj)
    tl = json.loads(tlf.read_text(encoding='utf-8')) if tlf else {}
    # エンジン：--engine（この 1 枚だけ。どのエンジンも呼べる＝生成と直しでエンジンを使い分ける）→ 作品の settings.image_engine（作品の既定）
    engine = (a.engine or (tl.get('settings') or {}).get('image_engine') or '').strip()
    if engine not in ('codex', 'openai', 'nanobanana'):
        die('この作品の絵のエンジンが決まっていない（タイムラインの settings.image_engine）。先にユーザーに「Codex か OpenAI か Nano Banana か」を聞いて書く（AI 用ガイドの 0）。この 1 枚だけなら --engine')
    outp = (proj / a.args[0]).resolve()
    if proj not in outp.parents:
        die('出力は作品のフォルダの中に（assets/images/gen/… か work/mock/…）')
    if outp.exists():
        die(f'{a.args[0]} はもうある（素材は上書きしない。新しい名前で）')
    if outp.suffix.lower() != '.png':
        die('出力は .png')
    prompt = Path(a.prompt_file).read_text(encoding='utf-8') if a.prompt_file else a.prompt
    refs = [str((proj / r).resolve()) for r in a.ref]
    for r in refs:
        if not Path(r).is_file():
            die(f'参照画像が無い：{r}')
    outp.parent.mkdir(parents=True, exist_ok=True)
    tools = Path(__file__).resolve().parent
    jobs = proj / 'work' / 'jobs'
    jobs.mkdir(parents=True, exist_ok=True)
    # プロンプトの一時ファイルは依頼ごとに別の名前（前はミリ秒だけで、同時に頼むと上書きしあってプロンプトを取り違えた。2026-11-15 mittler-mv の報告）
    pf = jobs / f'gen_{int(time.time() * 1000)}_{os.getpid()}_{uuid.uuid4().hex[:8]}.prompt.txt'
    if engine == 'openai':
        sys.path.insert(0, str(tools))
        import openai_image_jobs as OA
        size = a.size or OA.pick_size(tl.get('width') or 1920, tl.get('height') or 1080)
        q = a.quality or OA.DEFAULT_QUALITY
        pf.write_text(prompt, encoding='utf-8')
        cmd = [sys.executable, '-X', 'utf8', str(tools / 'gen' / 'openai_image.py'), '--prompt-file', str(pf), '--out', str(outp),
               '--model', a.model or OA.DEFAULT_MODEL, '--quality', q, '--size', size, '--background', a.background or 'auto']
    elif engine == 'nanobanana':
        # Nano Banana（Gemini）：鍵は Gemini TTS と同じ。--size（WxH）は近い縦横の比に、--quality は解像度（2026-11-19）
        sys.path.insert(0, str(tools))
        import gemini_image_jobs as NB
        if len(refs) > NB.MAX_REFS:
            die(f'参照画像は {NB.MAX_REFS} 枚まで（Nano Banana）')
        size = (a.quality or NB.DEFAULT_SIZE).upper()
        if size not in NB.SIZES:
            die(f'Nano Banana の --quality は解像度 {" / ".join(NB.SIZES)}（{a.quality} は使えない）')
        try:
            w, h = (int(v) for v in a.size.lower().split('x')) if a.size else (tl.get('width') or 1920, tl.get('height') or 1080)
        except ValueError:
            die(f'--size は 横x縦（{a.size}）')
        extra = ['【背景】透明にはできないので、単色のフラットな背景（あとで抜く）'] if a.background == 'transparent' else []
        pf.write_text(prompt + ('\n\n' + '\n'.join(extra) if extra else ''), encoding='utf-8')
        cmd = [sys.executable, '-X', 'utf8', str(tools / 'gen' / 'gemini_image.py'), '--prompt-file', str(pf), '--out', str(outp),
               '--model', a.model or NB.DEFAULT_MODEL, '--image-size', size, '--aspect', NB.pick_aspect(w, h)]
    else:
        if a.model or a.quality:
            print('（--model・--quality は OpenAI・Nano Banana だけ。Codex では使わない）', file=sys.stderr)
        extra = []
        if a.size:
            extra.append(f'【大きさ】横 {a.size.lower().replace("x", " × 縦 ")} の比')
        if a.background == 'transparent':
            extra.append('【背景】透明（アルファつきの PNG）。透明にできなければ、単色のフラットな背景')
        pf.write_text(prompt + ('\n\n' + '\n'.join(extra) if extra else ''), encoding='utf-8')
        cmd = [sys.executable, '-X', 'utf8', str(tools / 'gen' / 'codex_image.py'), '--prompt-file', str(pf), '--out', str(outp),
               '--session', str(proj / 'work' / 'codex-session.json')]
    for r in refs:
        cmd += ['--ref', r]
    print(f'{engine} で生成中：{a.args[0]}', file=sys.stderr)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=str(proj))
    ok = p.returncode == 0 and outp.is_file()
    info = {}
    for line in reversed((p.stdout or '').strip().splitlines()):
        try:
            info = json.loads(line); break
        except ValueError:
            continue
    r = {'ok': ok, 'out': a.args[0].replace('\\', '/'), 'engine': engine, 'width': info.get('width'), 'height': info.get('height'), 'model': info.get('model')}
    if not ok:
        r['error'] = ((p.stderr or '') + (p.stdout or '')).strip()[-800:]
    else:  # 使う前に読み戻して確かめる（AI 用ガイドの 0。2026-11-22）
        r['check'] = CHECK_IMAGE
    out(a, r, None if not ok else f"できた：{r['out']}（{engine}{' ' + str(info.get('model')) if info.get('model') else ''} {info.get('width')}×{info.get('height')}）\n{CHECK_IMAGE}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project')
    ap.add_argument('cmd')
    ap.add_argument('args', nargs='*')
    ap.add_argument('--json', action='store_true', help='結果を JSON で出す')
    ap.add_argument('--wait', action='store_true', help='終わるまで待つ（進み具合は標準エラー）')
    ap.add_argument('--pending', action='store_true', help='music：生成待ち・採用待ちだけ')
    ap.add_argument('--sidecar', default='', help='music-take：Suno の情報の JSON（素材の根からの相対パス）')
    ap.add_argument('--take', default='', help='music-take：ファイルを付けるテイク（t1 など）')
    ap.add_argument('--src', default='', help='music-take：音のファイル（素材の根からの相対パス。.wav か .mp3）')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--draft', action='store_true', help='video：ステップを減らした下書き（シードは本番と同じ）')
    ap.add_argument('--steps', type=int, default=0, help='video：下書きのステップ（既定はクリップの video.draft_steps か 10）')
    ap.add_argument('--regen', action='store_true', help='tts-all：文のあるもの全部を作り直す')
    ap.add_argument('--tempo', type=float, default=None, help='tts：生成のあとの速さ（0.5〜2。クリップの tempo に書いてから生成）')
    ap.add_argument('--step', type=int, default=1, help='export：下書き（2＝2 コマに 1 コマ・4）')
    ap.add_argument('--scale', type=float, default=1, help='export：下書きの大きさ（0.5・0.25）')
    ap.add_argument('--from', dest='frm', type=float, default=None)
    ap.add_argument('--to', type=float, default=None)
    ap.add_argument('--name', default='')
    ap.add_argument('--jobs', type=int, default=None)
    ap.add_argument('--no-proxy', action='store_true', help='export：再生用の動画を作らない')
    ap.add_argument('--no-cache', action='store_true', help='export：ためた絵（fcache）を使わずに全部描く')
    ap.add_argument('--upscale', default='', choices=['', 'none', 'anime', 'real'])
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--fresh', action='store_true')
    ap.add_argument('--at', type=float, default=None)
    ap.add_argument('--track', default='')
    ap.add_argument('--latest', action='store_true')
    ap.add_argument('--label', default=None)
    ap.add_argument('--set', action='append', default=[], help='onbeat：名前=値')
    ap.add_argument('--adv', default='', help='onbeat：そのほかの設定（JSON）')
    ap.add_argument('--overwrite', action='store_true')
    ap.add_argument('--engine', default='', choices=['', 'codex', 'openai', 'nanobanana'], help='image・gen-image：絵のエンジン（この 1 回だけ。いつもなら絵の欄の engine → 作品の settings.image_engine）')
    ap.add_argument('--model', default='', help='image：OpenAI のモデル（gpt-image-2.5-sunburst・gpt-image-2.5-flare・gpt-image-2 …）か Nano Banana のモデル（gemini-3-pro-image・gemini-nano-banana-2.1 …）')
    ap.add_argument('--quality', default='', choices=['', 'auto', 'low', 'medium', 'high', 'xhigh', 'max', '1K', '2K', '4K', '1k', '2k', '4k'], help='image：OpenAI の品質か Nano Banana の解像度（1K・2K・4K）')
    ap.add_argument('--prompt', default='', help='gen-image：プロンプト')
    ap.add_argument('--prompt-file', default='', help='gen-image：プロンプトのファイル')
    ap.add_argument('--ref', action='append', default=[], help='gen-image：参照画像（作品からの相対。いくつでも）')
    ap.add_argument('--size', default='', help='gen-image：大きさ WxH（OpenAI。両辺 16 の倍数。既定は作品の動画の比）')
    ap.add_argument('--background', default='', choices=['', 'auto', 'opaque', 'transparent'], help='gen-image：背景（OpenAI。transparent＝透明の PNG）')
    ap.add_argument('--no-link', action='store_true', help='split・delete・ripple・gaps・stretch：リンクしたクリップ（動画とその音）を一緒にしない')
    ap.add_argument('--how', default='hold', choices=['hold', 'slow'], help='stretch：hold＝最後のコマで止める・slow＝ゆっくりにする')
    ap.add_argument('--len', dest='to_len', default='', help='stretch：伸ばす先（next＝次のクリップの頭まで・plan＝動画化予定の長さ・秒数。既定 next）')
    ap.add_argument('--title', default='')
    ap.add_argument('--width', type=int, default=None)
    ap.add_argument('--height', type=int, default=None)
    ap.add_argument('--fps', type=float, default=None)
    ap.add_argument('--duration', type=float, default=None)
    ap.add_argument('--lang', default='')
    ap.add_argument('--no-git', action='store_true')
    ap.add_argument('--no-open', action='store_true')
    ap.add_argument('--none', action='store_true', help='ui select：選ぶのをやめる')
    ap.add_argument('--seek', action='store_true', help='ui select：そのクリップの真ん中へ再生位置も')
    a = ap.parse_args()
    proj = Path(a.project).resolve()
    if a.cmd == 'gen-image':  # 編集画面のサーバーを使わない（その場で作って終わる）
        gen_image(a, proj)
    api = Api(proj)
    cmd, A = a.cmd, a.args

    def need(n, usage):
        if len(A) < n:
            die(usage)

    def op(name, args, timeout=120):
        out(a, api.call('/api/op', {'op': name, 'args': args}, timeout=timeout))

    # ---- 状態・生成（前からのもの）----
    if cmd == 'status':
        st = api.call('/api/status')
        j = api.call('/api/jobs')
        print(json.dumps({'server': api.base, 'render': st, 'runner': j.get('runner'), 'jobs': len(j.get('jobs', []))}, ensure_ascii=False, indent=1)); return
    if cmd == 'music':
        music_list(api, a.pending, a.json); return
    if cmd == 'music-take':
        if len(A) != 1:
            die('music-take <クリップ> --sidecar <JSON>（新しいテイク）か music-take <クリップ> --take t<n> --src <音のファイル>（採用のファイル）')
        if a.take and not a.src:
            die('--take には --src（取ってきた音のファイル）が要る')
        body = {'clip': A[0]}
        for k in ('sidecar', 'take', 'src'):
            if getattr(a, k):
                body[k] = getattr(a, k).replace('\\', '/')
        r = api.call('/api/music/take', body, timeout=120)
        print(json.dumps(r, ensure_ascii=False)); sys.exit(0 if r.get('ok') else 1)
    if cmd == 'analyze':
        need(2, 'analyze <クリップ> <種類> [--wait]')
        cid, kind = A[0], A[1]
        tl = api.call('/api/timeline').get('timeline') or {}
        c = next((x for t in tl.get('tracks', []) for x in t.get('clips', []) if x.get('id') == cid), None)
        if not c:
            die(f'クリップ {cid} が無い')
        r = api.call('/api/analyze', {'clip': c, 'kind': kind, 'by': 'mittler_api'}, timeout=60)
        if a.wait and r.get('ok'):
            while True:
                j = next((x for x in api.call('/api/analyze').get('jobs', []) if x.get('id') == r['id']), {})
                if j.get('state') not in ('queued', 'running'):
                    r = dict(r, state=j.get('state'), result=j.get('result'), error=j.get('error'), ok=j.get('state') == 'done')
                    break
                progress(f"PROGRESS 解析 {j.get('state')}")
                time.sleep(5)
        print(json.dumps(r, ensure_ascii=False)); sys.exit(0 if r.get('ok') else 1)
    if cmd == 'analyses':
        while True:
            js = api.call('/api/analyze').get('jobs', [])
            busy = [j for j in js if j.get('state') in ('queued', 'running')]
            if not (a.wait and busy):
                break
            time.sleep(5)
        for j in js[-20:]:
            r = j.get('result') or {}
            print(j.get('id'), j.get('kind'), j.get('clip'), j.get('state'), 'タイムラインに入れた' if j.get('applied') else '', r.get('summary') or j.get('error') or '', ' '.join((r.get('files') or {}).values()))
        return
    if cmd in ('jobs', 'image', 'video'):
        jobs = api.call('/api/jobs').get('jobs', [])
        if cmd == 'jobs':
            if a.json:
                print(json.dumps(jobs, ensure_ascii=False)); return
            for j in sorted(jobs, key=lambda x: x.get('created', '')):
                print(j.get('id'), j.get('kind'), j.get('clip'), j.get('which'), j.get('state'), (j.get('result') or {}).get('src', '') or j.get('error', '') or '')
            return
        tl = api.call('/api/timeline').get('timeline') or {}
        ps = plans(tl)
        busy = {(j.get('clip'), j.get('which')) for j in jobs if j.get('state') in ACTIVE}
        if cmd == 'image':
            if len(A) != 2 or A[1] not in ('start_frame', 'end_frame'):
                die('image <クリップ> start_frame|end_frame')
            cid, which = A
            if cid not in ps:
                die(f'動画化予定のクリップ {cid} が無い')
            if (cid, which) in busy:
                die(f'{cid} の {which} は、もう生成している（待っている）')
            clip = ps[cid]
            over = {k: v for k, v in (('engine', a.engine), ('model', a.model), ('quality', a.quality)) if v}
            if over:  # この 1 回だけ（タイムラインは書きかえない）
                clip = dict(clip, **{which: dict(clip.get(which) or {}, **over)})
            r = api.call('/api/jobs', {'kind': 'image', 'clip': clip, 'which': which}, timeout=120)
            print(json.dumps(r, ensure_ascii=False)); sys.exit(0 if r.get('ok') else 1)
        ids = [cid for cid, c in ps.items() if ((c.get('video') or {}).get('prompt') or '').strip() and not (c.get('video') or {}).get('takes') and (cid, 'video') not in busy] if a.all else A
        if not ids:
            die('動画化するクリップが無い（クリップの id を並べるか --all。--all は、動画のプロンプトがあって、テイクも、動いているジョブも無いもの）')
        bad = 0
        for cid in ids:
            if cid not in ps:
                print(f'{cid}: 動画化予定のクリップが無い'); bad += 1; continue
            if (cid, 'video') in busy:
                print(f'{cid}: もう動画化している（待っている）ので出さない'); continue
            c = ps[cid]
            steps = a.steps or (c.get('video') or {}).get('draft_steps') or 10
            r = api.call('/api/jobs', {'kind': 'video', 'clip': c, 'which': 'video', 'dry': a.dry, 'draft': a.draft, 'steps': steps}, timeout=120)
            if r.get('ok'):
                print(f"{cid}: 出した {r.get('id')} → {r.get('out')}" + (f"（{' / '.join(r.get('warnings') or [])}）" if r.get('warnings') else ''))
            else:
                print(f"{cid}: 出せなかった：{r.get('error')}"); bad += 1
        sys.exit(1 if bad else 0)

    # ---- 動画化予定のテイク・採用 ----
    if cmd == 'frame-take':
        need(3, 'frame-take <予定> start_frame|end_frame <テイク>')
        op('frame-take', {'clip': A[0], 'which': A[1], 'take': A[2]})
    if cmd == 'video-take':
        need(2, 'video-take <予定> <テイク>')
        op('video-take', {'clip': A[0], 'take': A[1]})
    if cmd == 'adopt':
        need(1, 'adopt <予定> [<テイク>]')
        op('adopt', {'clip': A[0], 'take': A[1] if len(A) > 1 else ''})
    if cmd == 'adopt-all':
        op('adopt-all', {'track': a.track, 'latest': a.latest})

    # ---- セリフ ----
    if cmd == 'tts':
        need(1, 'tts <セリフのクリップ>…')
        rs = []
        for cid in A:
            progress(f'PROGRESS セリフ {cid}')
            body = {'clip': cid}
            if a.tempo is not None:
                body['tempo'] = a.tempo
            rs.append(api.call('/api/tts/clip', body, timeout=330))
        r = rs[0] if len(rs) == 1 else {'ok': all(x.get('ok') for x in rs), 'results': rs, 'message': '\n'.join(f"{x.get('clip', '')}: {x.get('message') or x.get('error')}" for x in rs)}
        out(a, r)
    if cmd in ('tts-all', 'tts-status'):
        r = api.call('/api/tts/batch', {'mode': 'all' if a.regen else 'pending'}) if cmd == 'tts-all' else api.call('/api/tts/batch')
        if r.get('ok') is False:
            out(a, r)
        last = None
        while a.wait and r.get('running'):
            line = f"PROGRESS セリフ {r.get('done')}/{r.get('total')}" + (f"（{r.get('cur')}）" if r.get('cur') else '')
            if line != last:
                progress(line); last = line
            time.sleep(2)
            r = api.call('/api/tts/batch')
        r = dict(r, ok=not r.get('fails') or r.get('running', False))
        r['message'] = f"セリフ {r.get('done')}/{r.get('total')}：できた {len(r.get('made') or [])}・失敗 {len(r.get('fails') or [])}" + ('（まだ動いている）' if r.get('running') else '') + \
            (f"（最初の失敗：{r['fails'][0].get('clip')} {r['fails'][0].get('error')}）" if r.get('fails') else '')
        out(a, r)
    if cmd == 'tts-stop':
        out(a, api.call('/api/tts/batch/stop', {}), 'まとめての生成を止める（今の 1 本のあとで）')
    if cmd == 'tts-take':
        need(2, 'tts-take <セリフ> <テイク>')
        op('tts-take', {'clip': A[0], 'take': A[1]})
    if cmd == 'subs-from-lines':
        op('subs-from-lines', {'clips': A})

    # ---- 書き出し ----
    if cmd in ('export', 'master'):
        body = {'by': 'api'}
        if cmd == 'master':
            body.update(master=True, force=a.force, fresh=a.fresh)
            if a.upscale:
                body['upscale'] = a.upscale
        else:
            body.update(step=a.step, scale=a.scale if a.step > 1 else 1)
            if a.no_proxy:
                body['proxy'] = False
            if a.no_cache:
                body['nocache'] = True
        if a.frm is not None:
            body['from'] = a.frm
        if a.to is not None:
            body['to'] = a.to
        if a.name:
            body['name'] = a.name
        if a.jobs is not None:
            body['jobs'] = a.jobs
        r = api.call('/api/export', body)
        if not r.get('ok'):
            out(a, dict(r, ok=False))
        if a.wait:
            out(a, export_result(wait_export(api, a)))
        out(a, dict(r, message=f"始めた：{r.get('name')}.mp4" + (f"（画質 {r.get('upscale')}）" if r.get('master') else '') + '。進み具合は export-status [--wait]'))
    if cmd == 'export-status':
        j = wait_export(api, a) if a.wait else api.call('/api/export')
        r = export_result(j)
        if j.get('state') in EXPORT_BUSY:
            r['message'] = f"{j.get('state')} {j.get('phase') or ''} {j.get('done', 0)}/{j.get('total', 0)} コマ"
        out(a, r)
    if cmd == 'export-cancel':
        out(a, api.call('/api/export/cancel', {}), '止めるように頼んだ')
    if cmd == 'master-info':
        r = api.call('/api/master'); r['ok'] = True
        print(json.dumps(r, ensure_ascii=False, indent=None if a.json else 1)); return
    if cmd == 'master-cache-clear':
        r = api.call('/api/master/cache/clear', {})
        out(a, r, f"キャッシュを空にした：{r.get('files')} 本・{r.get('gb')} GB" if r.get('ok') else None)
    if cmd == 'still':
        t = a.at
        if t is None:
            try:
                t = json.loads((state_dir(proj) / 'state.json').read_text(encoding='utf-8'))['time']['t']
            except Exception:
                t = 0
        r = api.call('/api/still', {'t': t}, timeout=600)
        out(a, r, f"保存した：{r.get('path')}（{r.get('bytes', 0) / 1e6:.1f} MB）" if r.get('ok') else None)
    if cmd == 'proxy':
        need(1, 'proxy <output/…mp4>')
        progress('PROGRESS 再生用の動画を作っている')
        r = api.call('/api/proxy', {'src': A[0].replace('\\', '/')}, timeout=1900)
        out(a, r, f"プレビューに使う：{r.get('proxy')}" if r.get('ok') else None)

    # ---- 映像・音 ----
    if cmd == 'place-video':
        need(1, 'place-video <素材> [--at 秒] [--track <id>]')
        op('place-video', {'src': A[0].replace('\\', '/'), 'at': a.at or 0, 'track': a.track}, timeout=650)
    if cmd == 'stems-place':
        need(2, 'stems-place <音のクリップ> <WAV>…')
        op('stems-place', {'clip': A[0], 'stems': [{'src': s.replace('\\', '/'), 'name': Path(s).stem} for s in A[1:]]})
    if cmd == 'video-audio':
        need(1, 'video-audio <映像クリップ>…')
        op('video-audio', {'clips': A}, timeout=650)
    if cmd == 'onbeat':
        need(1, 'onbeat <映像クリップ> [--set 名前=値]… [--adv JSON]')
        fields = {}
        for kv in a.set:
            k, _, v = kv.partition('=')
            fields[k.strip()] = parse_val(v.strip())
        args = {'clip': A[0], 'fields': fields}
        if a.adv:
            args['adv'] = json.loads(a.adv)
        progress('PROGRESS 音ハメを計算している（動きを読む。長い素材は数分）')
        op('onbeat', args, timeout=650)

    # ---- カット編集の道具（cutedit.js・映像の欄の「伸ばす」と同じ計算）----
    if cmd == 'split':
        need(1, 'split <秒> [<クリップ>…] [--no-link]')
        op('split', {'t': float(A[0]), 'clips': A[1:], 'link': not a.no_link})
    if cmd in ('delete', 'ripple'):
        need(1, f'{cmd} <クリップ>… [--no-link]')
        op(cmd, {'clips': A, 'link': not a.no_link})
    if cmd == 'gaps':
        op('gaps', {'clips': A, 'tracks': [a.track] if a.track else [], 'link': not a.no_link})
    if cmd == 'stretch':
        need(1, 'stretch <映像クリップ>… [--len next|plan|<秒>] [--how hold|slow]')
        op('stretch', {'clips': A, 'to': a.to_len or 'next', 'how': a.how, 'link': not a.no_link})
    if cmd == 'job-cancel':
        need(1, 'job-cancel <ジョブの id>')
        r = api.call(f'/api/jobs/{A[0]}/cancel', {})
        out(a, r, f'止めるように頼んだ：{A[0]}' if r.get('ok') else None)
    if cmd == 'plan-resolve':
        need(2, 'plan-resolve <予定> start_frame|end_frame|video')
        r = api.call('/api/plan/resolve', {'clip': A[0], 'which': A[1]})
        r.setdefault('ok', not r.get('errors'))
        print(json.dumps(r, ensure_ascii=False, indent=None if a.json else 1)); sys.exit(0 if r['ok'] else 1)

    # ---- カットの段 ----
    if cmd == 'cut-first':
        op('cut-first', {})
    if cmd == 'cut-lane':
        need(1, 'cut-lane cuts|notes')
        op('cut-lane', {'kind': A[0]})
    if cmd == 'cut-split':
        need(1, 'cut-split <秒> [--label L]')
        op('cut-split', {'t': float(A[0]), 'label': a.label})
    if cmd == 'cut-join':
        need(2, 'cut-join <ラベル> prev|next')
        op('cut-join', {'label': A[0], 'dir': A[1]})
    if cmd == 'cut-remove':
        need(1, 'cut-remove <ラベル>')
        op('cut-remove', {'label': A[0]})
    if cmd == 'cut-rename':
        need(2, 'cut-rename <ラベル> <新しいラベル>')
        op('cut-rename', {'label': A[0], 'to': A[1]})
    if cmd == 'cut-edge':
        need(3, 'cut-edge <ラベル> start|end <秒>')
        op('cut-edge', {'label': A[0], 'side': A[1], 't': float(A[2])})
    if cmd == 'cut-align':
        op('cut-align', {'labels': A})
    if cmd == 'cut-from-clip':
        need(1, 'cut-from-clip <クリップ>')
        op('cut-from-clip', {'clip': A[0]})
    if cmd == 'cuts-on-adopt':
        need(1, 'cuts-on-adopt on|off')
        op('cuts-on-adopt', {'on': A[0] in ('on', 'true', '1')})

    # ---- 部品・キャラ・作品 ----
    if cmd == 'effects':
        fx, lib = api.call('/api/effects', timeout=120), api.call('/api/effects_lib', timeout=120)
        r = {'ok': True, 'project': {k: {'label': (v.get('meta') or {}).get('label'), 'doc': (v.get('doc') or '')[:200]} for k, v in fx.items()},
             'library': {k: {'pack': v.get('pack'), 'label': (v.get('meta') or {}).get('label'), 'doc': (v.get('doc') or '')[:200]} for k, v in lib.items()}}
        print(json.dumps(r, ensure_ascii=False, indent=None if a.json else 1)); return
    if cmd == 'effect-add':
        need(1, 'effect-add <名前>')
        r = api.call('/api/effects/add', {'name': A[0]})
        out(a, r, f"作品に入れた：{'・'.join(r.get('copied') or [])}" if r.get('ok') else None)
    if cmd == 'presets':
        r = api.call('/api/presets/characters'); r['ok'] = not r.get('error')
        print(json.dumps(r, ensure_ascii=False, indent=None if a.json else 1)); sys.exit(0 if r['ok'] else 1)
    if cmd == 'preset-add':
        need(1, 'preset-add <id> [--overwrite]')
        r = api.call('/api/presets/characters/add', {'id': A[0], 'overwrite': a.overwrite})
        out(a, r, f"作品に入れた：{r.get('name')}（{r.get('id')}）" if r.get('ok') else None)
    if cmd == 'blender-clear':
        need(1, 'blender-clear <クリップ>')
        r = api.call('/api/blender/clear', {'clip': A[0]})
        out(a, r, f"ためた絵を消した：{r.get('files')} ファイル" if r.get('ok') else None)
    if cmd == 'frame-cache':
        clear = bool(A) and A[0] == 'clear'
        r = api.call('/api/fcache', {'clear': clear})
        out(a, r, (f"ためたコマの絵を消した：{r.get('frames')} 枚" if clear else f"ためたコマの絵：{r.get('frames')} 枚・{(r.get('bytes') or 0) / (1 << 20):.0f} MB")
            if r.get('ok') else None)
    if cmd == 'new-project':
        need(2, 'new-project <置く親のフォルダ> <名前> [--title T] …')
        body = {'parent': str(Path(A[0]).resolve()), 'id': A[1], 'title': a.title, 'open': not a.no_open}
        for k in ('width', 'height', 'fps', 'duration'):
            if getattr(a, k) is not None:
                body[k] = getattr(a, k)
        if a.lang:
            body['lang'] = a.lang
        if a.no_git:
            body['git'] = False
        r = api.call('/api/new_project', body, timeout=180)
        out(a, r, f"作った：{r.get('timeline')}（git {r.get('git')}・開いた {r.get('opened')}）" if r.get('ok') else None)

    # ---- 画面の見える操作 ----
    if cmd == 'ui':
        need(1, 'ui <操作> [引数]（play・pause・seek 秒・step コマ・select クリップ…・pane・zoom・fit・scroll・lang・open-export・open-master・close-export・reload・undo・redo・follow・state）')
        u, rest = A[0], A[1:]
        args = {}
        if u == 'seek':
            need(2, 'ui seek <秒>'); args = {'t': float(rest[0])}
        elif u == 'step':
            args = {'n': int(rest[0]) if rest else 1}
        elif u == 'select':
            args = {'ids': [] if a.none else rest, 'seek': a.seek}
        elif u == 'select-track':
            need(2, 'ui select-track <トラック>'); u, args = 'select', {'track': rest[0]}
        elif u == 'pane':
            need(2, 'ui pane clip|color|meta'); args = {'name': rest[0]}
        elif u == 'zoom':
            need(2, 'ui zoom <px/秒>|fit'); args = {'fit': True} if rest[0] == 'fit' else {'pps': float(rest[0])}
        elif u == 'scroll':
            need(2, 'ui scroll <秒>'); args = {'t': float(rest[0])}
        elif u == 'lang':
            need(2, 'ui lang en|ja'); args = {'lang': rest[0]}
        elif u == 'follow':
            args = {'on': (rest[0] if rest else 'on') not in ('off', 'false', '0')}
        r = api.call('/api/ui', {'cmd': u, 'args': args}, timeout=40)
        out(a, r, (f"{u}：" + json.dumps(r.get('state'), ensure_ascii=False)) if r.get('ok') else None)

    die(f'知らないコマンド {cmd}（python {Path(__file__).name} -h で一覧）')


if __name__ == '__main__':
    main()
