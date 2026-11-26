# {{TITLE}}

Mittler の作品フォルダです（{{DATE}} 作成）。VS Code で `{{TIMELINE}}` を開くと編集画面が表示されます。

- **使い方**：Mittler の `docs/スターターガイド.md`（短い入口）と `docs/スターターガイド（人間用）.md`（画面構成・操作手順）を参照してください。Mittler 本体のドキュメント場所は、作品を開いた後に生成される `.mittler/env.json` の `docs_dir` で確認できます。
- **書き出し**：編集画面上部の「書き出し」ボタンから実行します。

## フォルダ構成

```
{{ID}}/
  {{TIMELINE}}      タイムライン（正本。編集画面で変更すると自動で保存）
  characters.json     登場キャラの設定（編集画面左の「キャラ」タブで編集可能）
  effects/            エフェクトのコード（字幕・重ね絵・フェード・色の手直し。追加は Claude Code に依頼するか自分で記述）
  assets/             素材（git 管理外）
    images/             画像（絵・背景・コマ）
    videos/             動画
    sfx/                効果音
    bgm/                音楽（BGM・曲）
    music/              Suno の曲（Claude Code が Suno で生成し、採用したテイクの音声とサイドカー *.suno.json が入る）
    voice/              セリフの音声（TTS で生成したテイクが入る）
    fonts/              フォントファイル（字幕の既定は fonts/NotoSerifJP-Regular.ttf。無ければ Windows の游ゴシック）
    characters/         キャラの立ち絵
    overlays/           重ね絵（フキダシ・スタンプなどの透過 PNG）
  work/               作業ファイル（git 管理外）
    proxy/              再生用の動画（MP4）
  output/             書き出した MP4（git 管理外）
  .mittler/           この PC 用のファイル（Mittler の場所・AI 用ガイドの写し・編集画面の現在状態。git 管理外。編集画面を開くたびに生成）
  pronunciation.json  セリフの読み辞書
  AGENTS.md           AI エージェント向けの説明とルール
  CLAUDE.md           Claude Code 向けの入口（AGENTS.md を読み込む）
```
