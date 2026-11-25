# Mittler の構造（どこに何があるか）

コードを直す人・エージェント向けの短い地図です。「どこに何があって、どうつながっているか」をまとめています。

- 使い方：[スターターガイド](スターターガイド.md)
- ファイル形式の正本：[タイムライン形式](タイムライン形式.md)・[エフェクトの書き方](エフェクトの書き方.md)
- 生成との受け渡しの正本：[H3受け渡し契約](H3受け渡し契約.md)・[Suno受け渡し契約](Suno受け渡し契約.md)

## ひとことで

- VS Code の拡張は「ローカルサーバーを起動して、その編集画面を iframe で表示する」だけの構成です。本体は **`server/server.js`（Node 標準モジュールのみ）**・**`pyengine/mittler/`（Python の描画エンジン）**・**`editor/`（素の HTML／JS）** で、npm の依存はありません。
- 正本は作品の **`*.cut.json`** と **`effects/*.py`** です。タイムラインを書き換えるのは編集画面とエージェントだけで、生成・解析・曲はファイルを置くだけです（タイムラインへの組み込みは編集画面が担います）。
- **すべて拡張が動いている PC 上で動作します**（別の PC で描く場合は、VS Code の Remote-SSH でその PC に接続します）。
- 絵は**時刻だけで決まります**（どのコマから描いても同じ絵になり、並列分割して書き出しても一致します）。描画時に機械学習は動かさず、マスクや拍はあらかじめ作成したファイルを参照します。

## プロセスの関係

```
VS Code ── extension.js ──（Webview の iframe）──▶ 編集画面 editor/（ブラウザで開いても同じ）
              │ 起動する                                  │ HTTP（127.0.0.1・起動ごとのトークン）・変更通知（SSE /api/events）
              ▼                                           ▼
        server/server.js ──────────────────────────────────┘      作品のフォルダ
              ├─ server/pyrender.js ─▶ 描画サーバー  python -m mittler serve（1コマを JPEG で。ポート 47900〜47989）
              ├─ 書き出し            ─▶ python -m mittler video ／ master（区間に分けて並列 → ffmpeg）
              ├─ セリフ              ─▶ tools/tts_gen.py（Gemini TTS／VOICEVOX）
              ├─ 生成のジョブ        ─▶ work/jobs/job_*.json ─▶ ジョブ係 tools/jobs.py ─▶ アダプタ（tools/engines.json が対応表）
              ├─ 解析                ─▶ 解析用の python で pyengine/mittler/analyze.py
              └─ 状態                ─▶ 作品の .mittler/（server.json＝ポートとトークン・state.json＝編集画面の今・
                                         env.json＝その PC の Mittler の場所・guide.md＝AI 用ガイドの写し・中継 hook.py／api.py／engine.py）
エージェント ── ファイルを直す（*.cut.json・effects/*.py）／.mittler/api.py → tools/mittler_api.py（.mittler/server.json を読んでサーバーに頼む）
             │      └─ /api/op（タイムラインの書きかえ。editor/ops.js）・/api/tts/*・/api/export・/api/proxy・/api/ui（見える操作 → 変更通知の 'ui' → 編集画面 → /api/ui/<id>/done）
             └─ フック（python -c が .mittler/hook.py を探す）→ tools/mittler_state.py（話しかけるたびに .mittler/state.json の要約をそえる。
                    いちばん最近さわった編集画面が別の作品なら、一時フォルダの mittler/recent.json からそちらの今）
```

### 補足

- **人の操作を API から呼べる仕組み**（2026-11-15）：編集画面のボタンだけにあった計算（セリフの頼み・テイク・セリフから字幕・動画化予定の採用・動画の音・音ハメの頼み・カットの段・分ける・リップル・隙間・伸ばす・書き出しの名前とマスターの画質・`change` の時刻の決まり）は、`editor/ops.js` の 1 か所に集約しています（ブラウザと Node で同じファイルを使う、`calc.js` と同じ形）。
  - ボタンは `change()` の中でこれを呼び、API はサーバー（`/api/op` ほか）がこれを呼んでファイルに書き込みます（1 つずつ順に処理し、編集画面の保存直後は少し待ちます）。
  - 編集画面は「外の直し」として読み直すため、Ctrl+Z で元に戻せます。ボタンと API の結果が一致することは `tools/smoke_api.py` が検証します。
- **見える操作（`/api/ui`）**：再生・飛ぶ・選ぶ・タブ・拡大・言葉・窓・取り消しなどは、サーバーが変更通知（SSE `/api/events`）の `ui` イベントで編集画面へ依頼し、`editor/remote.js` がボタンと同じ関数を実行して応答します。作品ファイルは変更しません。編集画面が開いていない場合は理由を返します。
- **AI を追う（オート、`editor/remote.js`）**：外の直しを読み直したとき、`ops.changedClips` で変化したクリップを特定し、その中央へ再生位置を移動・タイムラインをスクロールして数秒間ハイライトします。上のバーの「オート」で切り替え可能です（既定オン、編集画面が記憶）。
- **PC ごとの情報の分離**（2026-11-13 パッケージ化）：作品ファイルには Mittler の場所を書きません。PC ごとの情報（`.mittler/env.json` など）は、`server/project_env.js` が作品を開くたび・新規作成時に書き出します。
- **配布版と開発版**：配布版（`tools/build_vsix.py` の VSIX）は VS Code の拡張の置き場だけで完結し、置き場は読み取り専用です（`docs/配布.md`）。開発版は `tools/install_vscode.py` の入口がリポジトリの `extension.js` を読み込みます。
- **ライフサイクル**：作品を 1 つ開くとサーバー 1 つと描画サーバー 1 つが立ち上がります。閉じると、サーバーは描画サーバーと自分が起動した子プロセス（解析・TTS など）を終了します。
- **ジョブ係**：作品ごとに 1 つだけ動作します（`work/jobs/runner.lock` で排他制御）。15 分間何も無ければ自動終了します。

## データの流れ（クリップを動かして、そのコマが出るまで）

1. **タイムラインの保存**：編集画面でクリップを動かすと、`editor/editor.js` がタイムラインを更新し（コマに乗る時刻は `n / fps` にそろえる）、`PUT /api/timeline` を送信します。サーバーは一時ファイルへ書いてから置き換えます（`server/atomic.js`）。
2. **変更通知**：サーバーがファイルの変化を検知し、変更通知（`/api/events`）を配信します。エージェントが外部からファイルを書き換えたときも同じ経路で編集画面が読み直します。
3. **1 コマの要求**：編集画面が停止時刻の 1 コマを `GET /api/frame?t=…` で要求し、`server/pyrender.js` が描画サーバーの `/frame` に中継します。
4. **描画とキャッシュ**：描画サーバー（`pyengine/mittler/serve.py`）は、タイムライン・`effects/*.py`・使用中の素材が変わっていれば読み直し、`engine.py` で 1 コマを描いて JPEG で返します（先の 1 秒ぶんを先読みします）。
   - **ディスクキャッシュ**：描く前に、そのコマの鍵（`fcache.py`）の絵が作品の `work/cache/frames/` にあれば描かずに返します（`X-Mittler-Cache: disk`）。
   - **メモリキャッシュ**：保持する JPEG（`CACHE_N`）も同じ鍵で管理するため、修正した区間以外は破棄しません。`/cachemap` でコマごとの鍵（ためてあるもの）を返します。
   - **裏で描く（バックグラウンドベイク）**：オン（既定はオフ、プレビュー下の砂時計ボタンで切り替え）の場合、停止して手を離すと編集画面（`editor/cacheplay.js`）が `/api/bake` でサーバーに依頼し、`bake.py` が低優先度プロセスで再生位置から先を描いてためます。目盛りの下の緑の印がためた区間となり、ためた区間では ▶ で小さな JPEG（`/api/cframe`）を時計どおりに再生します。描いた絵は本番品質なら保存します。
5. **書き出し**：同じ `engine.py` を区間ごとの別プロセスで並列実行します（`__main__.py` の `video`。区間は並列数より細かく分割し、空いた枠から順次処理）。そのため、停止中の 1 コマと書き出し結果は完全に同じ絵になります。
   - ためた絵（劣化なしの PNG）があるコマは描かずに再利用します（差分書き出し。`--no-cache` で全コマを描き直し）。書き出しの各区間でも、描いたコマを `work/cache/frames/` にためます。

## エンジン（`pyengine/mittler/`）

| ファイル | 役目 |
|---|---|
| `engine.py` | タイムラインを読んで時刻 `t` の 1 コマを生成。映像・画像クリップ → エフェクトの段（`scene` → `v7`（float の絵）→ `post`（uint8 の絵））。字幕も `post` 段のエフェクト `effects/subtitle.py`（ASS の場合は `ass.py`） |
| `__main__.py` | CLI コマンド：`stills`（静止画）・`video`（書き出し）・`segment`・`serve`・`mix`・`master`・`enhance` |
| `serve.py` | 描画サーバー（`/frame`・`/effects`・`/warp`・`/info`・`/quit`。JPEG キャッシュと先読み） |
| `bake.py` | 裏で先に描いてためる処理（`python -m mittler bake`）。区間プロセス `bake-part` を優先度「通常以下」で実行し、`--stop` ファイルで停止。`<stop>.pause` がある間は子孫ごと一時停止（`procs.suspend_tree`）。サーバーがプレビュー要求・編集操作時に置き、2.5 秒静かになったら解除 |
| `fcache.py` | 描いたコマを作品の `work/cache/frames/`（`<鍵>.png`＝劣化なし、`<鍵>.p.jpg`＝プレビュー用）に保存・読み込み。鍵は前後 2 秒のクリップ・エフェクトコード・素材の更新時刻・`settings` などから計算（直した区間のみ再描画） |
| `mix.py`・`loudnorm.py` | 音声のミックス（ffmpeg）・書き出し最終段の音量そろえ |
| `ass.py` | 字幕を ASS で焼き込む（libass） |
| `warp.py`・`onbeat.py`・`beatwarp.py` | 映像クリップの時間の付け替え（速さ・音ハメ） |
| `master.py`・`enhance.py` | マスター書き出し（アップスケール・60fps 補間・大きなキャンバスで描画）・動画 1 本の高画質化 |
| `analyze.py`・`analyze_kinds.json` | 解析（拍・文字起こし・ボーカル分離・ポーズ・マスク・切り抜き）。種類一覧は JSON の 1 か所で管理 |
| `helpers.py`・`lib/` | エフェクト用の共通部品（`lib/` は作者の作品から取り込んだ色・曲線の部品） |
| `gl3d.py` | GPU 3D の土台（moderngl、2026-11-13）。GL コンテキストはプロセスに 1 つ・専用スレッドで管理。moderngl は使用時に初めて読み込み。3D エフェクト `effects_lib/common/gl_*.py` が使用 |
| `htmllayer.py`・`html_runtime.js` | HTML レイヤー（`effects_lib/common/html.py`）。プロセスに 1 つのヘッドレス Chromium（Playwright・専用スレッド）でクリップごとにページを開いたまま維持し、作品の `html/` と `assets/` のみを配る 127.0.0.1 のサーバー経由で、1 コマごとに `__mittlerRender(t)` を呼んで透過撮影・合成。`html_runtime.js` はページより先に読み込んで時刻と乱数を固定。ひな形は `templates/html/`（three.js は `templates/html/vendor/`） |
| `blender.py`・`blender_runner.py`・`blender_kit.py` | Blender 3D（`effects_lib/common/blender3d.py`）。作品の `work/3d/` にキャッシュし、プレビューは下描き・書き出しは区間を描く前にまとめて描画（`__main__.py` の `prepare`）。`runner` は Blender 内の実行係、`kit` は場面スクリプト用道具（`mittler_bpy`）。ひな形は `templates/3d/` |
| `names.py` | 環境変数・状態フォルダ・ヘッダなどの名前定義（Python 側の 1 か所） |
| `i18n.py` | 通知・理由メッセージの多言語化（`t('鍵')`）。辞書は `editor/i18n/*.json`、言語は環境変数 `MITTLER_LANG`（未設定時は日本語）。描く絵には影響しない |

## エフェクト

- **入口**：作品の `effects/<名前>.py` に `STAGE`（段）・`META`（編集画面に出す説明とパラメータ）・`apply(ctx, f, clip)` を定義します。書き方は [エフェクトの書き方](エフェクトの書き方.md) を参照してください。
- **`effects_lib/`（部品の置き場）**：
  - `common/`：字幕（`subtitle`）・重ね絵（`sprite`）・フェード（`fade`）・色（`grade`）。新しい作品に配るのはこの 4 本です（`tools/new_project.js` の `FIRST_EFFECTS`）。
  - `false_maria/`：偽マリアのエフェクト集（コードだけで描く 6 本。2026-11-13）。
  - `beatfx/`：拍の演出。
  - 作品の `effects/` は作成時の写しであり、`effects_lib/` を直しても既存作品には自動反映されません。
- **「部品の置き場」の一覧と追加**：編集画面の「部品の置き場」に出すフォルダは `effects_lib/library.json` の `packs` で指定します（現在は `common`・`false_maria`。見出しは辞書の `as.libPack.<フォルダ>`）。
  - 描画サーバーの `/effects_lib` が `pack` 付きで一覧を返し、サーバーの `POST /api/effects/add` が同じ順に探索して作品へコピーします。
  - エフェクト名はフォルダをまたいで重複しないようにします（偽マリアは `fm_` 接頭辞）。
- **3D エフェクト**（2026-11-13）：`common/` の `gl_cards3d`・`gl_particles3d`・`gl_lightrays`（GPU）と `blender3d`（Blender）があります。立体の文字は部品には入れず、作品ごとにその場で書きます（2026-11-16）。これらは新しい作品には最初から配らず、編集画面の「部品の置き場」→「作品に入れる」（`/api/effects_lib`＝描画サーバーの `/effects_lib`、`POST /api/effects/add`）で作品へ写します。
- **計算の一致**：色の卓の式と時間の付け替えは、編集画面（`editor/calc.js`）とエンジン（`effects_lib/common/grade.py`・`pyengine/mittler/warp.py`）で同一の計算を行います（`tools/smoke_same.py` で検証）。

## サーバー（`server/`）

| ファイル | 役目 |
|---|---|
| `server.js` | 編集画面の配信・`/api/*`・`/project/`（作品ファイル。`.git` と状態フォルダは配信しない）・変更通知。127.0.0.1 限定、Host 検証、書き込みと副作用のある GET にはトークンが必要（決まりは [インストールガイド](インストールガイド.md) の 11） |
| `pyrender.js` | 描く python の探索・検証、描画サーバーの起動・再起動・中継 |
| `main.js` | VS Code なしでの単体起動（`tools\mittler.cmd serve`） |
| `project_env.js` | 作品の状態フォルダへ PC ごとのファイル（`env.json`・`guide.md`・`templates/state/` の中継）を書き出し。配布版か開発版かの判定（印 `mittler_build.json`） |
| `defaults.js` | PC ごとの設定が無いときの既定値の 1 か所 |
| `names.js` | 設定・環境変数・状態フォルダ・ヘッダ・`format` の名前定義（JS 側の 1 か所） |
| `i18n.js` | 画面の言葉（`tr(言葉, 鍵, 値)`・鍵つき例外 `keyedError`＝内部メッセージは日本語、画面返却時に `errText` で現在の言語へ変換）。辞書は `editor/i18n/*.json`。拡張・`tools/new_project.js` も使用 |
| `music.js`・`plan_refs.js`・`atomic.js` | Suno の曲の受け取り・動画化予定のプロンプト参照（`@import`）・ファイルのアトミック置き換え |

### 主なエンドポイント

- **サーバー（`/api/`）**：`timeline`・`events`・`status`・`frame`・`still`・`export`・`master`・`tts`・`jobs`・`analyze`・`music`・`assets`・`thumb`・`wave`・`video_audio`・`effects`・`effects_lib`・`effects/add`・`blender/clear`・`file`・`state`・`annotate`・`presets/characters`・`new_project`・`warp/auto`・`lang`・`quit`
  - 2026-11-15 追加：`op`（タイムライン書き換え。名前一覧は `server.js` の `OP_TABLE`・`ASYNC_OPS`）・`tts/clip`・`tts/batch`（`/stop`）・`proxy`・`ui`（`/ui/<id>/done`）
- **描画サーバー（`serve.py`）**：`/frame`・`/effects`・`/effects_lib`・`/flush`・`/warp`・`/info`・`/quit`

## 画面の言葉（英語・日本語。2026-11-13〜）

- **辞書の統一**：`editor/i18n/en.json`・`ja.json` の 1 か所に集約しています（鍵 → 文。英語の複数形は `{one, other}`）。編集画面・サーバー（`server/i18n.js`）・拡張・`new_project.js`・エンジン（`pyengine/mittler/i18n.py`）がすべて同じ辞書を読みます。
- **言語の優先順位と保存**：PC の設定 `mittler.language`（単体起動は `--lang`、既定は `server/defaults.js` の `language`＝`en`）を使います。編集画面は URL の `&lang=` → 人が決めた設定 → このブラウザが覚えた言語 → 英語の順で決定します。
  - 上のバー右端（`#langSel`）で切り替えると `POST /api/lang` を呼び、サーバーの言語を変更します（VS Code 内なら拡張がユーザー設定に保存）。作品ファイルや `state.json` には書きません。
- **子プロセスへの伝播**：サーバーは子プロセス（エンジン・ジョブ係・TTS・アダプタ）へ環境変数 `MITTLER_LANG` で言語を渡します。描く絵・送信するプロンプト・ファイルの中身は言語によって変わりません。
- **VS Code 側の表示**：コマンド名と設定の説明は `package.nls.json`（英語）・`package.nls.ja.json`（日本語）にあり、VS Code の表示言語に応じて選択されます。
- **検証**：`tools/smoke_i18n.py` で検証します。その他の smoke は日本語画面で実行します（`--lang ja`・`&lang=ja`）。

## 編集画面（`editor/`。`index.html` が読む順）

| ファイル | 役目 |
|---|---|
| `i18n.js`・`i18n/*.json` | 画面の言葉（最初に読み込み）：`$t`・`$L`・`data-i18n`、上のバーの EN／日本語 切り替え。切り替え時は `MITTLER_I18N.onChange` で再構築 |
| `ui.js`・`editor.css` | UI の土台：VS Code テーマ色の反映・通知（右下）・押せない理由の表示・アイコン（`MITTLER_ICON`・辞書の `{icon:名前}` をアイコン化。`editor.css` の `.ic` 一覧） |
| `icons/` | アイコン（Lucide 1.65.0、ISC。使う SVG だけを改変せずに同梱。`LICENSE-lucide.txt`・`THIRD_PARTY_NOTICES.md`）。画面に絵文字は使わない |
| `calc.js` | エンジンと同一の計算（色の卓・時間の付け替え） |
| `ops.js` | ボタンと API で共通のタイムライン書き換え（サーバーからも `require`。上の「人の操作を API から呼べる仕組み」） |
| `editor.js` | タイムライン本体・選択・ドラッグ・キー操作・保存・取り消し・外部変更の再読み込み |
| `cutmeta.js`・`cutedit.js` | カットの段（メタデータ）の編集道具・カット編集の道具バー |
| `media.js`・`assets.js` | セリフ・字幕・音・トラック、左のアセット窓 |
| `plan.js`・`warp.js` | 動画化予定、映像の速さ・音ハメ・伸ばす |
| `annotate.js`・`state.js` | 書き込み機能、編集画面の現在状態をサーバーへ通知 |
| `export.js`・`analyze.js`・`music.js`・`newproject.js` | 書き出しとマスター窓、解析、Suno の曲（採用時に拍・構成・歌詞の時刻をメタデータへ登録）、「＋ 新規」 |
| `remote.js` | API の見える操作（`ui`）と AI を追う（オート）。最後に読み込み |

> 確認用の URL パラメータ：`&theme=light|dark`（テーマ固定）、`&lang=en|ja`（画面の言語。ブラウザ記憶・設定より優先）。

## 道具（`tools/`）と初期設定（`setup/`）

- **VS Code 拡張の入口**：`extension.js`（カスタムエディタ・コマンド）と `extension_setup.js`（コマンド「Mittler: 初期設定」：`setup/mittler_setup.py` で確認し、押されたときだけ globalStorage に描く python の venv を作成）。
- **起動・作成・配布ツール**：
  - `mittler.cmd`：VS Code 内蔵の Node で実行（引数は `%*` のまま `mittler_launch.js` へ渡す。2026-11-15）。
  - `new_project.js`：作品を作成（編集画面・コマンド・スキルすべて同じ `create()` を使用）。
  - `build_vsix.py`：配布版の VSIX を作成。
  - `install_vscode.py`：開発版の入口をインストール（`--vsix` で配布版をインストール）。
  - `fix_hooks.py`：以前の作品のフックを現行形式に更新。
- **`templates/state/`**：作品の `.mittler/` にコピーする中継スクリプト（`hook.py`・`api.py`・`engine.py`）。`.mittler/env.json` の Mittler の場所にある道具・エンジンを呼び出します。
- **エージェント・生成・音声・プロキシ用ツール**：
  - `mittler_api.py`：エージェントからの操作依頼（生成・解析・曲の納品・セリフ・書き出し・テイク・採用・カット編集・カットの段・見える操作 `ui`。一覧は AI 用ガイドの 7.53）。
  - `mittler_state.py`：フック本体。
  - `jobs.py`：ジョブ係。
  - `h3_jobs.py`／`codex_jobs.py`／`openai_image_jobs.py`／`gemini_image_jobs.py`：生成アダプタ。
  - `tts_gen.py`：TTS 生成。
  - `make_proxy.py`：再生用 WebM の作成。
- **検証スクリプト**：`smoke_*.py`（一覧は [AI 用ガイド](スターターガイド（AI用）.md) の 7）。
- **初期設定チェック**：`setup/mittler_setup.py`（詳細は `setup/README.md`）。

## 名前

設定 `mittler.*`・環境変数 `MITTLER_*`・状態フォルダ `.mittler/`・ヘッダ `X-Mittler-Token`・タイムラインの `format`（`mittler/py1`）は、`server/names.js` と `pyengine/mittler/names.py` の 2 か所で定義しています。一覧は [インストールガイド](インストールガイド.md) の 13 を参照してください。
