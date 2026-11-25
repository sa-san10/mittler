# Suno 受け渡し契約（Mittler ⇔ Claude Code の Suno MCP）

> **AI（Claude Code）が手順を実行するときは、いちばん下の「Mittler 側の受け渡し」を読んでください**（この文書だけで手順を完了できるように書いてあります）。
> それより上の章は前提資料です（Suno MCP の道具定義、実機検証の結果、受け渡し形式の考え方、既存曲で取得できる情報。2026-10-30 時点の情報であり、Suno 側の仕様は変更されることがあります）。

Suno 連携は AI 主導とし、Mittler（拡張機能）は受け皿・倉庫に徹します。Suno を呼び出すのはエージェント側の Suno MCP であり、Mittler からは呼び出しません。
Suno MCP が使えない場合は、ブラウザ版の suno.com で手動生成し、音声ファイルを `assets/` に置いて使用します。
Mittler 側の受け渡し仕様（`music.takes`・`/api/music/take`・`mittler_api.py music-take`）は、末尾の「Mittler 側の受け渡し」にまとめています。

- **MCP サーバー**：`https://api.suno.com/mcp`（ユーザーの Claude Code 設定 `mcpServers.suno`、`type: http`）
- **認証**：suno.com アカウントでサインイン（OAuth は Claude Code 側が担当）
- **道具一覧（全 32 個・2026-10-30 の定義。MCP ツール名は `mcp__suno__<名前>`）**：
  `account-me`・`account-upgrade`・`account-usage`・`audio-analysis`・`audio-covers-create`・`audio-create`・`audio-download`・`audio-edit`・`audio-extensions-create`・`audio-full-song`・`audio-like`・`audio-lyrics-alignment`・`audio-mashups-create`・`audio-retrieve`・`audio-unlike`・`audio-upload-complete`・`audio-upload-create`・`audio-wait`・`library-liked`・`library-list`・`library-search`・`playlists-add-clips`・`playlists-create`・`playlists-list`・`playlists-list-clips`・`playlists-remove-clips`・`speech-create`・`voices-list`・`voices-start`・`workspaces-create`・`workspaces-list`・`workspaces-update-clips`

## Mittler に関わる道具（定義の原文から、要るところを全部写した）

### audio-create（曲を作る）

> Generates a new audio clip in one of two modes. **Simple:** `description` alone; the lyrics and style are written for you. **Custom:** `lyrics`, usually with `style` and `title`.
> Mixing the modes returns a `400`: `description` takes no `style`, and no `lyrics` unless `instrumental` is `true`. With `instrumental: true`, `lyrics` and `description` may both be omitted.
> Poll `GET /v0/audio/{id}` for the result: the clip is playable once `status` is `streaming`.

主な引数：

- `description`（≤3000）：自然文。Simple モード用（`lyrics`・`style` と同時指定不可）。
- `lyrics`（≤5000）：Custom モード用（`instrumental: true` の場合を除き `description` と同時指定不可）。
- `style`（≤1000）：ジャンル・スタイルの指定（例：`"jazz melancholic"`）。`description` と同時指定不可。
- `title`（≤256）：曲名。
- `instrumental`（既定 `false`）：ボーカルなし。`voice_id` が指定されている場合は `voice_id` が優先されます。
- `duration`（15〜360 秒）：目標の長さ（範囲外は `400`）。あくまで目標であり保証値ではありません。
  - `duration_guidance`（`duration` 指定時は既定で on）：AI が書く歌詞を目標の長さに合わせます。
  - `duration_strict`（`duration` 指定時は既定で on）：`duration` を超えないようにします（超えそうな場合は途中で切れる＝アウトロなしで終わることがあります）。`false` にすると柔らかい目標になります。
- `clip_count`（`1` または `2`）：
  - 2026-10-30 の定義：**suno.com のサインインで MCP から呼ぶと既定は `2`**（2 曲＝2 回分の生成としてカウント）。1 曲だけ欲しいときは `1` を明示する必要がありました（`2` の場合は `clip_ids` に 2 つ返ります）。
  - **2026-11-15 の定義には `clip_count` がありません**：1 回で必ず 2 本生成されます（下の「AI の手順（生成）」の 2 を参照）。
- `model`：省略時はプランの既定。使用可能なラベルは `account-usage` の `allowed_models` で確認できます。
- `negative_style`（≤1000）・`vocal_gender`（`male` / `female`）・`controls`（`style_influence`・`weirdness`・`audio_influence`、各 `0`〜`1`）：`advanced-controls` 権限が必要です（無いと `403`）。
- `voice_id`：`voices-list` で取得できる声の ID。
- `workspace_id`：suno.com の workspace に登録します。
- `idempotency_key`（1〜255 バイト、24 時間以上保持）：同じ鍵と同じ内容で再送すると初回の結果が返ります（再試行による二重生成を防止）。内容を変えて同じ鍵を送ると `409` が返ります。

### audio-wait（できるまで待つ）

> Call this after audio-create, … instead of polling audio-retrieve. It checks every few seconds and returns the clip as soon as `status` is `streaming` (the clip plays live and `song_url` works),
> `complete` or `error`, or after about 50 seconds with the clip still pending. If it is still pending, call audio-wait again. A creation that returned `clip_ids` made one song per id:
> call audio-wait once with all of them in `ids` … Once every one is settled it returns the first song's fields with every song, in order, under `clips` …

主な引数：

- `id` または `ids`（最大 4 件）
- `until`：`playable`（既定。`streaming` になった時点で返る）または `complete`（ファイルが完成するまで待つ）

### audio-retrieve（状態を見る）

> Retrieves the current state of an audio clip. … A generated clip is playable once `status` reaches `streaming` … Keep polling until `complete` or `error` only when you need the finished file or its duration.

### audio-download（ファイルの URL をもらう）

> Returns a URL for one of the signed-in suno.com user's own songs, as `mp3` (default) or `wav`, under suno.com's own download rules and download credits. Requires the `audio.download` feature.
> Only for a suno.com user whose token grants `download`; an API key gets 403.
> Call without `confirm` first. If the answer is `requires_credit`, the download would spend one of the user's download credits: **ask the user, and only with their approval call again with `confirm: true`.**
> Any format may answer `processing` while suno.com prepares the file … The `audio-download` MCP tool waits out `processing` itself for up to about 50 seconds: if it still answers `processing`, call audio-download again, never audio-wait.
> `url` saves the file under the song's title. … elsewhere, share or fetch `url`.
> Refusals … `reason`：`quota_exhausted`（402）、`no_permission`（403）、`plan_required`（403）、`invalid_asset`（404）、`format_unsupported` / `invalid_format`（400）、`rate_limited`（429）、`daily_limit_exceeded`（429）。

主な引数：`id`、`format`（`mp3` 既定 / `wav`）、`confirm`（既定 `false`）。

→ **返るのはファイル本体ではなく URL です。** Mittler の作品に配置するには、AI がその URL からファイルを取得し（外部通信のため事前にユーザーへ確認）、`assets/music/` に保存します。

### audio-analysis（拍・小節・テンポ・キー・構成・音の説明）

> Returns what the clip sounds like and its musical timing map. `terms` and `labels` describe the audio itself … The timing map has every beat with its position in the bar, the tempo, the meter,
> structural sections and the key. This is what syncing video to music needs, e.g. cutting on every downbeat (`bar_position: 1`) or changing scene where a section starts.
> Sections that share a `label` repeat the same material, so a recurring label is usually the chorus. …
> Analysis is a separate model run … The first request starts the run; it is not charged, and repeating it does not start a second one. The beats (with `bpm`, `time_signature` and `key`),
> the sections (with `duration_s`) and the description (`terms` and `labels`) are separate runs … `status` is `processing` while a run is expected … poll until it leaves `processing`, typically within a minute.
> It is then `complete` when at least one part succeeded, or `unavailable` when none did. … `key` can also be null …

→ Mittler の拍メタデータ（kind `beats`、`[秒, 小節の頭か, 強さ]`）およびカット・区間の目安へそのまま転記できます。ローカル解析（librosa の拍検出）より先に使える有力候補です。

### audio-lyrics-alignment（歌詞の単語ごとの時刻）

> Returns the clip's lyrics with the span of audio each word is sung over — what a karaoke or caption display needs. … Poll until `status` leaves `processing` …
> The first request … starts the run; it is not charged … `status` is `complete` once the words are in hand (`words` is legitimately empty for an instrumental), `processing` …, and `unavailable` …
> Word timings are best-effort: a word the aligner could not place carries `success: false` and a span inferred from its neighbour.

→ 歌詞のメタデータ（kind `lyrics`）や字幕タイミングに利用できます。

### account-usage（プランと使った量）

> Returns the account's plan and current usage against metered features. For a suno.com sign-in, `suno_account` reports song-generation credits: uploads, library reads and organizing spend none …

### そのほか（使うかもしれない）

- `audio-extensions-create`（`continue_at` 秒から続きを生成。新しいクリップは続きのみ）＋ `audio-full-song`（つないだ 1 曲を作成。無料）：曲を延長する用途。
- `audio-covers-create`（スタイル・声を変えたカバー）・`audio-mashups-create`（2 曲をミックス）。
- `library-list`・`library-search`（suno.com 上の自分の曲を検索。クレジット消費なし）：既存曲を作品に取り込む用途。
- `speech-create`（語り。`script` をそのまま読む、または `prompt` から生成）。
- `audio-upload-create`・`audio-upload-complete`（自分の音声を Suno へアップロード）。

## 押さえておくこと

1. **ステム（ボーカルと伴奏などに分離した音）は 2026-11-15 から Suno MCP で取得可能**（`audio-stems-create`＋`audio-stems-retrieve`）。
   取得方法と配置手順は下の「AI の手順（採用＝ダウンロード）」の 5 を参照してください。Suno MCP が無い環境やブラウザ版で作った既存曲では、ローカル解析の `stems`（demucs、解析用 Python、作品の `assets/analysis/…/` に出力）を使います。
2. **音声ファイルは URL として返る**（`audio-download`）。保存は AI が URL から取得して行います。ダウンロード用クレジットを消費する場合があります（`requires_credit` → ユーザーへ確認）。
3. **WAV も取得可能**（`format: "wav"`）。音質重視で WAV を優先できます。
4. **`clip_count` の仕様**：2026-10-30 時点の MCP 定義では既定が `2` のため、1 テイクずつ頼むには `1` を明示しないとクレジットが 2 倍かかりました（**2026-11-15 時点では `clip_count` パラメータ自体が廃止され、常に 2 本生成されます**。下の「AI の手順（生成）」の 2 を参照）。
5. **拍・構成・キー（`audio-analysis`）と歌詞の時刻（`audio-lyrics-alignment`）が無料で取得可能**：Mittler のローカル解析（`mittler_api analyze beats`）より先にこちらを活用できます。
6. **`duration` は 15〜360 秒の目標値**で、`duration_strict` が既定で on です（アウトロなしで途中で切れる場合があります）。

## 本物で試した結果（2026-10-30。suno.com の Pro Plan のアカウントで）

| 段階 | 呼んだもの | 消費したもの | 返ったもの |
|---|---|---|---|
| 生成を頼む | `audio-create`（`instrumental`・`style`・`title`・`duration` 30・`clip_count` 1・`idempotency_key`） | 依頼直後は 0 | `{id, status: "submitted", created_at}` |
| できるまで待つ | `audio-wait`（`until: "complete"`） | — | `status: "complete"`、`song_url`（suno.com の曲ページ）、`cover_image_url`、`metadata`（`duration` 30・`style`・`type` generate）。**音声ファイルの URL は含まれない** |
| できたあと | `account-usage` | **生成 5 クレジット**（30 秒・1 曲の値） | — |
| 解析 | `audio-analysis` | 0（無料） | 1 回目は `processing`、すぐ `complete`：拍 36（`time_s`・`bar_position` 1〜4）、`bpm` 72、`time_signature` 4、`key` `"A major"`、`sections` 5（`start_s`・`end_s`・`label` A〜E）、`labels`・`terms`（instrumental・piano・lo-fi） |
| ダウンロード（1 回目） | `audio-download`（`confirm` なし） | — | mp3 も wav も `requires_credit`（ダウンロード用クレジットを 1 つ消費するためユーザーに確認が必要） |
| ダウンロード（払う） | `audio-download`（mp3・`confirm: true`） | **ダウンロード用 1** | `{status: "ok", url, expires_at}`。`url` は署名付き S3 URL（`…/<id>_paid_wm.mp3?…`、**1 時間で失効**） |
| ファイルを取る | `curl` でその URL | — | mp3：30.0 秒・48kHz・2ch・約 184kbps、カバー画像（mjpeg）入り、690KB |
| 同じ曲の wav | `audio-download`（wav・`confirm` なし） | **0** | 即座に `status: "ok"`。**1 曲につき一度支払えば、別形式も追加消費なしで取得可能** |
| ファイルを取る | `curl` | — | wav：pcm_s16le・48kHz・2ch・30.0 秒、5.8MB |

確認できたこと：

- **課金は 2 種類**：**生成クレジット**（生成完了後に消費。30 秒・1 曲で 5）と、**ダウンロード用クレジット**（1 曲につき 1 回。月間上限あり。一度払えば形式をまたいで再消費なし）。
- **解析は無料**：拍・構成・キー・音の説明（`audio-analysis`）は無料。歌詞の時刻（`audio-lyrics-alignment`）も仕様上は無料（この検証はインスト曲のため未確認）。
- **試聴は suno.com のページを開くしかない**：MCP には音声ファイルを直接返すツールがありません（説明にある `GET /v0/audio/{id}/stream` は API エンドポイントであり、MCP ツールにはありません）。
- ダウンロード URL のファイル名に `_paid_wm` が付いていました（何の印かは未確認）。

## 決まったこと

テイクには URL を積んでブラウザで開くボタンを付け、ダウンロード用クレジットは採用時にのみ消費する方針とします。

- 生成したテイクには、まず **suno.com の URL**（`song_url`）、Suno の ID、プロンプト、解析結果（拍・構成・キー）だけを積みます。この段階ではダウンロード用クレジットを使いません。
- テイクに「suno.com で聞く」ボタンを設け、ユーザーが自分のブラウザで曲ページを開いて試聴します。
- **採用時にダウンロード用クレジットを 1 つ消費して**ファイルを取得し、`assets/music/` に配置します（配置後は通常の音声クリップと同様に扱います）。採用前に「ダウンロード用のクレジットを 1 つ使う」ことを必ず確認します（Suno の「使う前にユーザーに聞く」ルールにも合致）。
- 形式は、一度支払えば WAV も MP3 も取得できるため、採用時は **WAV（48kHz・16bit）** を取得するのが推奨です。

## 既存曲（ブラウザ版の suno.com で作った曲）で取れるもの（2026-10-30 に試した。どれもクレジットを使わない）

ブラウザ版で作成した約 40 秒の曲で検証した結果です。

| 呼んだもの | 結果 |
|---|---|
| `library-list`（ライブラリ一覧） | ○ ブラウザで作った曲も新しい順に並ぶ（`id`・曲名・`song_url`・`metadata` の `description`・`duration`・`style`・`type`。`lyrics` は MCP の一覧には入らない） |
| `audio-retrieve`（曲の情報） | ○ 取得可能。曲名・長さ・`style`・`description` に加え、**`lyrics`（`[Intro: …]` `[Section A: …]` のような構成メモ付き）**も返る |
| `audio-analysis`（拍・テンポ・キー・構成・音の説明） | × `{"error":"audio not found","code":"not_found"}` |
| `audio-lyrics-alignment`（歌詞の単語ごとの時刻） | × `{"error":"audio not found","code":"not_found"}` |

確認できたこと：

- **解析と歌詞の時刻は MCP（API）から作った曲にしか使えません**（MCP で作った検証曲では取得できましたが、ブラウザ作成曲は `not_found` になります）。
- 既存曲から MCP で取得できるのは、曲情報と歌詞（構成メモ）までです。構成メモは作品メモやカットの目安に活用できます。
- 既存曲の拍・文字起こし・ボーカルと伴奏の分離は、従来どおりブラウザ版からダウンロードして作品の `assets/` に置き、Mittler の解析機能（音声クリップを右クリック。解析用 Python のある PC で実行）で取得します。
- **未検証**：既存曲の音声ファイルを Suno にアップロード（`audio-upload-create`。仕様上はクレジット消費なし）したあとに解析が効くかは未確認です。音声ファイルを外部へ送信することになるため、試す場合は必ずユーザーの許可が必要です。

## Mittler 側の受け渡し（2026-10-30 実装。機能追加案02 v2）

### 分担（だれが何をするか）

| 役割 | すること | しないこと |
|---|---|---|
| **Claude Code（AI）** | クリップにプロンプトを書く・ユーザーへ確認する・Suno MCP で生成と解析を行う・サイドカー JSON を書く・`mittler_api.py music-take` で納品する・採用時に `audio-download` でファイルを取得する | タイムラインのテイクを手書きする（反映は編集画面の役目） |
| **編集画面のサーバー**（`server/music.js`） | 納品を検証して受け取る（作品の状態フォルダ `.mittler/music.json` に積み、編集画面へ通知する）・サイドカーを `assets/music/` に書く・「suno.com で聞く」で曲ページをユーザーのブラウザで開く | **Suno を呼び出す**（OAuth も MCP クライアントも持たない）・AI を起こす |
| **編集画面**（`editor/music.js`） | プロンプト欄・テイク一覧・「suno.com で聞く」・採用（クレジット確認 → 採用待ちマーク付与）・届いた納品をテイクへ反映・採用ファイルをクリップの音声に設定し拍と構成をメタデータへ登録 | — |
| **ユーザー** | プロンプトを確認する・suno.com で試聴する（試聴は suno.com ページのみ）・「採用」を押してダウンロード用クレジット消費を OK する・AI に「取ってきて」と伝える | — |

> サーバーから AI を自動で起こす仕組みはありません。採用待ちの曲があることは、次のいずれかで AI が検知します。
> - ユーザーが次に話しかけた際、フック（`tools/mittler_state.py`、作品の `.claude/settings.json`）が `.mittler/state.json` の `music`（編集画面が書き込み）を読み取り、先頭に「【🎵 採用待ちの曲…】」を添える。
> - AI が `mittler_api.py <作品> music --pending` を実行して確認する。

### 置き場所と名前

- **タイムライン**：音声クリップ（通常は音楽トラック `role: "bgm"`）の `music` フィールド。構造は `docs/タイムライン形式.md` の「Suno の曲」を参照してください。
- **テイク名**：`t<n>`（サーバーが決定。クリップの既存テイク・未反映の納品・`assets/music/<クリップ>_t<n>.*` と重複しない最小の次番号）。`<クリップ>` はクリップ ID の英数字・`_`・`-` 以外を `_` に置換した名前です。
- **サイドカー**：`assets/music/<クリップ>_t<n>.suno.json`（**サーバーが生成**。AI が渡したサイドカーの内容に `clip`・`take`・`delivered` を加え、音声ファイル到着時に `src`・`format`・`dur_file`・`downloaded` を追記します）。
- **音声ファイル**：`assets/music/<クリップ>_t<n>.wav`（採用時に AI が配置。WAV を優先しますが MP3 も受け付けます）。
- **パス制約**：パスはすべて**素材ルート（タイムラインの `root`）からの相対パス**です。作品外（`..` や絶対パス）・`.git`・`.mittler` 配下は拒否されます。

### AI が渡すサイドカー（Suno の情報の JSON）

配置場所は素材ルート内であればどこでも構いません（推奨は `work/suno/<クリップ>_<Suno の id の頭8字>.json`。`work/` は git 管理外かつ変更通知も発生しません）。

| キー | 必須 | 中身 |
|---|---|---|
| `source` | 必須 | `"suno-mcp"` |
| `suno_id` | 必須 | Suno の ID（UUID。`audio-create` の `id`／`clip_ids` の 1 つ） |
| `song_url` | 必須 | `https://suno.com/song/<suno_id>`（`audio-wait` の `song_url`。**この形式でない場合、または URL の中の ID が `suno_id` と違う場合は拒否**） |
| `title`・`style`・`model`・`instrumental` | 任意 | 生成時の値（`model` は返り値または `account-usage` の既定値） |
| `prompt` | 任意 | **生成時に送信したプロンプトの全文**（`description` または `lyrics`） |
| `lyrics` | 任意 | 歌詞（Custom モード時、または `audio-retrieve` の `lyrics`） |
| `dur` | 任意 | 曲の長さ（秒。`audio-wait`（`until: "complete"`）の `metadata.duration`） |
| `credits` | 任意 | 消費した生成クレジット（`account-usage` の実行前後の差。不明なら省略） |
| `created` | 任意 | 作成時刻（同一生成の 2 本は同じ時刻＝`audio-create` の返り値 `created_at` を入れる） |
| `create_args` | **必ず入れる**（2026-11-15〜。無ければ `music-take` が注意を出す） | `audio-create` に渡した引数そのまま（リテイク時に同一条件で再送できるようにするため、および 1 回の生成で何本できたか判定するため） |
| `analysis` | 任意 | **`audio-analysis` の返り値をそのまま**格納。サーバーが扱いやすい形へ正規化してテイクに格納（下参照） |
| `lyrics_alignment` | 歌のある曲は入れる（2026-11-15〜） | **`audio-lyrics-alignment` の返り値をそのまま**格納（`{status, words: [{word, start_s, end_s, success, …}]}`）。サーバーが単語・行の時刻へ変換してテイクへ入れ（`server/music.js` の `normAlignment`）、採用時に編集画面が kind `lyrics` のメタデータへ登録 |

**`analysis` の読み方**（サーバー `server/music.js` の `normAnalysis`。返り値のネスト構造は確かめきれていないため、キー名で探索します）：

- `bpm`・`key`（文字列または `null`）・`time_signature`・`status`
- `beats`（配列。各要素は `{time_s, bar_position}` または `[秒, 位置]`）→ `[[曲の秒, 小節の中の位置 1〜]]` に変換
- `sections`（配列。各要素は `{start_s, end_s | duration_s, label}`）→ `[{start, end, label}]` に変換
- `terms`・`labels`（配列のまま保持）

### サーバーの口（`tools/mittler_api.py` が呼ぶ。トークンは `.mittler/server.json`）

| エンドポイント | 内容 |
|---|---|
| `POST /api/music/take` `{clip, sidecar[, src]}` | 新しいテイクを登録。サイドカー（`source`・`suno_id`・`song_url`）を検証し、`t<n>` を採番してサイドカーを保存、納品キューに積む。返り値：`{ok, take, sidecar, file: "assets/music/<クリップ>_t<n>.wav", analysis: {status, bpm, beats 数, sections 数}, lyrics_alignment: {status, words, lines, uncertain}, warnings}`。`warnings`（受け取り自体は拒否しない）：`create_args` が無い・`clip_count` が 1 でない・同一生成の 2 本目（同じ `created` かつ同じ `create_args`）。 |
| `POST /api/music/take` `{clip, take, src}` | 採用した音声ファイルを登録。`.wav`／`.mp3` であること、ffprobe で長さが取得できること、対象テイクが存在することを検証。返り値：`{ok, src, dur, note}`。採用待ちのテイクであれば編集画面がクリップの音声に設定する。 |
| `GET /api/music` | 納品の一覧を取得（`applied` は編集画面が反映済みの印）。 |
| `POST /api/music/<id>/applied` | 編集画面が反映済みの印を付ける。 |
| `POST /api/music/open` `{url}` | 「suno.com で聞く」の実行口。`https://suno.com/song/<UUID>` 形式のみ許可（それ以外は拒否）。VS Code 内では `vscode.env.openExternal`（未信頼ドメインなら VS Code が確認）、単体実行時は OS 既定のブラウザで開く。テスト時は環境変数 `MITTLER_OPEN_LOG` を指定すると開かずにログファイルへ記録する。 |

拒否されるケース（クリップが存在しない、音声クリップでない、サイドカーが無い／作品外／実体がない／JSON でない、`source`・`suno_id`・`song_url` が不正、同じ曲の二重納品、存在しないテイク、音声ではないファイル）では `{ok: false, error}` を返します（`mittler_api.py` は終了コード `1` で出力します）。

### AI の手順（生成）

0. **前提を確認する**
   - 対象作品の編集画面（`*.cut.json`）が開いていること（`mittler_api.py` が編集画面のサーバーへ依頼するため。開いていなければユーザーに開いてもらいます）。
   - Suno MCP のツール（`mcp__suno__*`）が利用可能であること（無ければ「Claude Code の設定に Suno の MCP（`https://api.suno.com/mcp`）を足してサインインして」とユーザーへ案内します）。
   - 作品の作業ごとにコミットします（プッシュは頼まれたときのみ。AI 用ガイドの 4.5 を参照）。

1. **プロンプトをクリップに書き、ユーザーの OK をもらう**
   - ユーザーの要望（雰囲気・長さ・BPM・歌の有無）をもとに、タイムラインの音声クリップの `music` を記述します（クリップが無ければ音楽トラックに `{"type": "audio", "src": null, "start", "dur", "in": 0, "gain": -6, "fade_in": 0, "fade_out": 1, "label", "music": {...}}` を追加します）。
   - 設定項目：`prompt`（曲の説明）または `lyrics`（歌詞）、`style`・`title`・`instrumental`・`duration`。
   - ユーザーに「このプロンプトで作っていい？（生成のクレジットを使う。30 秒・1 曲で 5 ほど。今の残りは `account-usage`）」と確認します。ユーザーは編集画面の入力欄で直接修正できます。
   - **OK が出るまで生成しないでください。** ユーザーが編集画面で修正した場合は、タイムラインの `music` を読み直してから生成します。
   - **書き方のコツ**：
     - `prompt`・`style` はタグの羅列（`j-pop, female vocal, 128bpm, …`）にせず、**曲のイメージを自然な文でシンプルに**書きます（2〜4 文：どんな場面のどんな曲か・感じ・音の手ざわり・展開）。
     - **ボーカルありの曲では、歌の明瞭さを優先する一文を入れます**（歌声がはっきり前に出て、言葉が聞き取れるようにする）。詳しくは `docs/スターターガイド（AI用）.md` の 7.56 を参照してください。

2. **生成する（`audio-create`）**
   - **1 回の生成本数に関する注意**：
     - 望ましいのは 1 回の生成で 1 本です。**呼び出す前に必ずツール定義を確認し、`clip_count` がある場合は `clip_count: 1` を渡してください。**
     - **2026-11-15 時点の定義では `clip_count` が削除されており**（`additionalProperties: false`）、説明に「Through MCP, a suno.com sign-in gets 2 songs per call, charged to their credits」と明記されています。つまり **1 回で必ず 2 本生成され（2 本分のクレジットを消費）、1 本だけの指定はできません**。
     - この仕様の場合は、使用量を「1 回＝2 本」で数えてユーザーへ伝え、1 曲のために何回も呼ばず、生成された 2 本を両方ともテイクとして納品して**ユーザーが聞き比べる候補**にします。サイドカーには `create_args` を必ず入れてください（`music-take` が 2 本目と判定できるようにするため）。
     - （参考：以前あった「MCP から呼ぶと既定は 2＝クレジット 2 倍、`clip_count: 1` で 1 本」という記述は 2026-10-30 時点の定義です。2026-11-14 に作成した作品では `clip_count` を渡さず、2 回の生成で 2 本ずつ計 4 本が生成されました。）
   **クリップの `music` から `audio-create` 引数への対応**：

   | クリップの `music` | `audio-create` に渡す引数 |
   |---|---|
   | `lyrics` がある | Custom：`lyrics`・`style`・`title`（`description` は送らない） |
   | `instrumental` で `lyrics` が無く、`style` がある | `instrumental: true`・`style`・`title`（`description` は送らない。2026-10-30 の検証形式） |
   | それ以外 | Simple：`description`＝`prompt`（`style`・`lyrics` は送らない）、`instrumental` |

   - **`duration`**：`music.duration`、無ければクリップの `dur`（15〜360 の範囲に収めます。`duration_strict` が既定で on のため、アウトロまで入れたい場合は少し長めにするか `duration_strict: false` を指定します）。
   - **`idempotency_key`**：`cc-<作品のフォルダ名>-<クリップ>-<n>`（頭の `cc-` は前からの決まりのまま。再試行による二重生成を防ぎます。リテイク時は `n` を変えます）。
   - `400` が返った場合はツール定義に合わせて引数を修正します（タイムラインの `music` 自体は書いたままにします）。

3. **完了を待つ（`audio-wait`）**
   - `ids` と `until: "complete"` を指定して呼び出します。`pending` のまま返ったら再度呼び出します。
   - `song_url`（suno.com の曲ページ）と `metadata.duration` を取得します。
   - **この時点では音声ファイルを取得しません**（ダウンロード用クレジットを消費しないため）。

4. **解析する（無料）**
   - **`audio-analysis`**：`processing` の場合は少し待って再呼び出しします（通常 1 分以内）。`complete`（一部以上成功）または `unavailable` になったら、返り値をそのままサイドカーの `analysis` に格納します。
   - **歌がある曲は `audio-lyrics-alignment`（無料）も実行（2026-11-15〜）**：`processing` の場合は少し待って再呼び出しします（生成直後はまだ処理中のことがあります）。`complete` または `unavailable` になったら、返り値をそのままサイドカーの `lyrics_alignment` に格納します。
   - 採用時、編集画面が kind `lyrics` のメタデータ「歌詞の時刻（Suno・…）」に反映します（行ごとに `{start, end, text, words: [[始め, 終わり, 字, 置けたか]], uncertain?}`、`from_music`・`from_suno` を付与。入れ直すと上書きされます）。インスト曲では何も追加されません。

5. **サイドカーを書いて納品する**
   - 実行コマンド：
     ```
     python <mittler>/tools/mittler_api.py <作品> music-take <クリップ> --sidecar work/suno/<…>.json
     ```
   - 実行すると編集画面にテイクが表示されます。
   - ユーザーに「テイク `t<n>` ができた。suno.com で聞いて、よければ『採用』を押して（ダウンロード用のクレジットを 1 つ使う）」と伝えます。

6. **リテイク（別テイクを追加するとき）**
   - 同じクリップの `music` で手順 2〜5 を繰り返します（`idempotency_key` の `n` を変えます）。テイクは既存のものに積み上がります。

### AI の手順（採用＝ダウンロード）

ユーザーが編集画面で「採用」を押し、クレジット確認に OK すると、クリップに `music.adopt`（採用待ち）が記録されます。**この OK がユーザーの明確な了解**（Suno の「使う前にユーザーに聞く」要件を満たす確認）になります。

1. **採用待ちを知る**
   - フックの「【🎵 採用待ちの曲…】」または `mittler_api.py <作品> music --pending`（`--json` 可）で確認します。対象テイク・Suno ID・配置先パス（`assets/music/<クリップ>_t<n>.wav`）が表示されます。
   - ユーザーの現在の依頼が別の内容であれば、そちらを優先しつつ、採用待ちの曲があることも伝えます。

2. **ファイルの URL を取得する（`audio-download`）**
   - `id`＝Suno の ID、`format: "wav"` で、**まず `confirm` なし**で呼び出します。
   - 返り値ごとの対応：
     - `ok`：そのまま次へ進みます（その曲は支払い済みです）。
     - `requires_credit`：採用待ちマークがある＝ユーザーが OK 済みのため、`confirm: true` で再呼び出しします（ダウンロード用クレジットを 1 つ消費）。
     - `processing`：`audio-download` を再度呼び出します（`audio-wait` は使いません）。
     - 拒否（`quota_exhausted`・`no_permission`・`plan_required`・`rate_limited`・`daily_limit_exceeded` など）：理由をユーザーへ伝えて停止します（採用待ちマークは残します）。

3. **URL からすぐダウンロードする**
   - 返された署名付き URL は **1 時間で失効**するため、取得したらすぐブラウザを使わずに保存します。
     ```
     curl -sSfL -o "<素材の根>/assets/music/<クリップ>_t<n>.wav" "<url>"
     ```
   - 外部通信にあたるため、その PC の運用ルール（外部通信は事前に許可を得る等）に従います。URL が失効していた場合は手順 2 からやり直します（一度支払った曲は 2 回目以降無料）。
   - ダウンロード後、ffprobe で内容を確認します（2026-10-30 の検証では `pcm_s16le`・48 kHz・2ch）。
   - **素材は上書きしません**（同名ファイルがすでにある場合は停止してユーザーに確認します）。

4. **音声ファイルを納品する**
   - 実行コマンド：
     ```
     python <mittler>/tools/mittler_api.py <作品> music-take <クリップ> --take t<n> --src assets/music/<クリップ>_t<n>.wav
     ```
   - 編集画面がクリップの `src` をそのファイルに差し替え（`in: 0`、テイクのほうが短ければ `dur` も調整）、採用待ちマークを消去し、解析結果の拍（kind `beats`）と構成（kind `song_sections`）をメタデータへ登録します。
   - 既存の音ハメ・スナップ機能がそのまま効きます（ほかのビートメタデータが先に存在する場合は、エフェクトの `ctx.beats` と音ハメは既存のほうを使用します）。
   - ユーザーに「入れた（戻すなら Ctrl+Z）」と伝えます。

5. **ステム（歌・伴奏・楽器ごと）が必要なとき（2026-11-15 検証済み）**
   - **`audio-stems-create`**（`id`＝Suno の ID）：
     - `two`：歌と伴奏の 2 パート（**10 クレジット**）
     - `twelve`：歌・鍵盤・ドラム・ストリングスなど 12 パート（**50 クレジット**）
     - 生成クレジットを消費するため、**必ず事前にユーザーへどちらにするかと OK をもらいます**。
   - **`audio-stems-retrieve`** で WAV の URL を取得します（WAV の取り出しではダウンロード用クレジットを消費しませんでした）。
   - 取得した URL は手順 3 と同様にすぐダウンロードします（**素材は上書きしません**）：
     `assets/music/<クリップ>_t<n>_stems/<パートの名前>.wav`
   - タイムラインへ配置するコマンド：
     ```
     python <mittler>/tools/mittler_api.py <作品> stems-place <音のクリップ> assets/music/<クリップ>_t<n>_stems/<パート>.wav …
     ```
     パートごとにミュート済みの音声トラック（「<パート>（ステム・<クリップ>）」）が、元のクリップと同じ時刻・長さ・`in`・音量で配置されます（ローカル解析の「ボーカルと伴奏に分ける」と同じ形式）。必要なトラックだけミュートを解除して使います。
   - Suno MCP が無い場合は、クリップを右クリック → 解析の「ボーカルと伴奏に分ける」（demucs。`mittler_api.py analyze <クリップ> stems`）を使用します。

### 既存曲（ブラウザ版の suno.com で作った曲）

- 解析（`audio-analysis`）と歌詞の時刻（`audio-lyrics-alignment`）は `not_found` になります（上の節を参照）。**音声ファイルは従来どおりユーザーが suno.com からダウンロードして `assets/` に配置します。** 拍・文字起こしは Mittler の解析機能で行い、ステムは Suno の ID が分かれば上の手順 5（`audio-stems-create`）、分からなければローカル解析で行います。
- suno.com のページで聞けるようにテイクとして残したい場合は、`library-search`／`audio-retrieve` で ID と `song_url` を取得し、サイドカー（`analysis` なし）と配置済みファイルの `--src` を渡して `music-take` できます（ファイルがすでにあるテイクは「採用」時にダウンロード用クレジットを消費しません）。

### 権利・記録

- 生成した曲の商用利用可否は契約プラン（2026-10-30 時点の検証アカウントは Pro Plan）および Suno の利用規約に依存します。作品を公開する前に必ず確認してください。
- 消費した生成クレジットはサイドカーの `credits` に記録します（把握できる場合）。ダウンロード用クレジットは 1 曲につき 1 回です。

### テスト（本物の Suno を動かさない）

本物の Suno MCP を呼ばずに一通り検証する手順（2026-10-30 実施済み）：

- **準備**：テスト用作品に偽のサイドカー（`source: "suno-mcp"`・偽の解析データ）と偽の WAV（ffmpeg の `lavfi` で生成）を配置し、環境変数 `MITTLER_OPEN_LOG=<ファイル>` を指定してサーバーを起動します。
- **検証項目**：
  - 納品エンドポイントのスモーク（テイク登録・採用ファイル登録・サイドカー出力・`music` 一覧）。
  - 不正リクエストの拒否（作品外パス・存在しないファイル・サイドカー無し・不正な URL ほか）。
  - 外部ブラウザ起動口（正しい URL だけがログファイルへ記録されること）。
  - 編集画面の連携（テイク表示 → suno.com で聞く → 採用確認 → 採用待ちマークとフック表示 → 偽 WAV の納品 → `src` 差し替え・拍と構成のメタデータ反映・取り消し）。
  - `mittler mix` に採用曲が含まれること。
  - `music` を使わない作品の静止画および書き出し結果が、変更前とビット単位で同一であること。
