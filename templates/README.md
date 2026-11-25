# templates（新しい作品のひな形）

`tools/new_project.js` がこのフォルダのファイルをもとに新しい作品フォルダを作成します。編集画面の「＋ 新規」ボタン、VS Code のコマンド「Mittler: 新しい作品を作る」、スキル `mittler-new-project` もすべて同じ `create()` を呼び出します。

## ひな形ファイル一覧

| ファイル | 作品フォルダでの配置 | 内容 |
|---|---|---|
| `project/project.cut.json` | `<名前>.cut.json` | 空のタイムライン（そのまま読める見本）。字幕・映像・効果音・音楽のトラックと空のカット・ト書きを含む。名前・サイズ・長さは作成時に設定 |
| `project/characters.json` | `characters.json` | 空のキャラ設定 |
| `project/pronunciation.json` | `pronunciation.json` | 空の読み辞書 |
| `project/gitignore.txt` | `.gitignore` | 素材・作業・書き出し・状態フォルダ（`.mittler/`。古い名前の `.claude-cut/` も）を git 管理外にする設定（このリポジトリ自体に影響させないため、ひな形内では `.gitignore` にしない） |
| `project/AGENTS.md` | `AGENTS.md` | AI エージェント向けの作品説明とルール本体（`{{TITLE}}` などは作成時に展開） |
| `project/CLAUDE.md` | `CLAUDE.md` | Claude Code の入口（`@AGENTS.md` と AI 用ガイドを読み込むだけ） |
| `project/README.md` | `README.md` | 人向けのフォルダ説明 |
| （`../effects_lib/common/*.py`） | `effects/` | 初期エフェクト（字幕・重ね絵・フェード・色の手直し） |
| `3d/logo.py` | （作品にはコピーしない） | Blender シーンのひな形（ロゴの組み上がり）。3D を使うときに作品の `3d/` へコピー |
| `state/hook.py`・`api.py`・`engine.py` | `.mittler/` に同名で配置 | 中継スクリプト（Mittler 本体の場所は同階層の `env.json` を参照）。フック → `tools/mittler_state.py`、`python .mittler/api.py . <コマンド>` → `tools/mittler_api.py`、`python .mittler/engine.py …` → 描画用 Python で `python -m mittler …` を実行。作品作成時および拡張機能が作品を開くたびに `server/project_env.js` がコピー（`env.json`・`guide.md` も同様） |

## ひな形のルール

- 作品のファイル（`AGENTS.md`・`CLAUDE.md`・`README.md`・`.claude/settings.json`・タイムライン）には **Mittler の場所（絶対パス）を書きません**（2026-11-13 パッケージ化）。
- ひな形に入れてよいプレースホルダは `{{TITLE}}`・`{{ID}}`・`{{DATE}}`・`{{TIMELINE}}` の 4 つだけです。PC ごとの情報は `.mittler/`（git 管理外）に配置します。
- フックの記述形式は `tools/new_project.js` の `HOOK_CMD` を参照してください。

## 作成される作品フォルダの構成

```
<名前>/
  <名前>.cut.json  characters.json  pronunciation.json  AGENTS.md  CLAUDE.md  README.md  .gitignore
  effects/   subtitle.py sprite.py fade.py grade.py
  assets/    images/ videos/ sfx/ bgm/ music/ voice/ fonts/ characters/ overlays/   （git 管理外）
  work/      proxy/                                                           （git 管理外）
  output/                                                                     （git 管理外）
  .mittler/  env.json guide.md hook.py api.py engine.py（ほかに編集画面が書く state.json 等）  （git 管理外）
```

## 変更後の確認

ひな形を変更した場合は、以下の 2 つを実行して確認してください。

- `tools/smoke_new_project.py`：作成したばかりの作品を開き、描画・書き出しできるかを確認
- `tools/smoke_package.py`：作品のファイルに絶対パスが含まれていないかを確認
