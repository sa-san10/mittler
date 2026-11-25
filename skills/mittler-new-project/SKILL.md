---
name: mittler-new-project
description: Mittler（ミットラー。VS Code 拡張の動画エディタ。前の名前は claude-cut／クロードカット）で新しい作品・プロジェクトを始めるとき、いま開いているフォルダ（空のフォルダ）に空の作品（タイムライン・エフェクト・素材フォルダ・AGENTS.md と CLAUDE.md・git）を準備する。「Mittler で新しいプロジェクトを始めたい」「Mittler の作品を作って」「このフォルダを Mittler のプロジェクトにして」「Mittler で新しい動画（MV・紙芝居）を作りたい」「空のプロジェクトを準備して」「claude cut で新しいプロジェクトを始めたい」などで使う。
---

# Mittler で新しい作品を始める

手順の正本は Mittler リポジトリ内の説明書です。このファイルには探索先だけを記載します（手順を更新するときは説明書側を修正し、git の更新だけで反映させます）。

1. Mittler の場所（リポジトリまたは拡張のフォルダ）を次の順で探し、最初に見つかったものを `<mittler>` とします（`<mittler>\docs\新しい作品を始める（AI用）.md` の存在で確認）。
   - 環境変数 `MITTLER_DIR`（未設定なら古い名前の `CLAUDE_CUT_DIR`）
   - このスキルフォルダ内の `mittler_dir.txt` に書かれたパス（`python setup\mittler_setup.py --install-skill` 実行時に生成）
   - VS Code に導入された Mittler 拡張機能のフォルダ `%USERPROFILE%\.vscode\extensions\sa-san10.mittler-<版>\`（Remote-SSH 接続先は `~/.vscode-server/extensions/…`）。複数バージョンがある場合は最新版を参照します。フォルダ内に `loader.js` があれば開発版の入口なので、その中の `require("…\\extension.js")` が指すフォルダを使います（無ければ配布版のため、そのフォルダ自体を使用）。
   - いずれも見つからない場合は、Mittler の場所をユーザーに確認してください。
2. `<mittler>\docs\新しい作品を始める（AI用）.md` を読み、その手順どおりに進めます。作成コマンドにはユーザーと話している言語に合わせて `--lang` を付けてください（日本語なら `--lang ja`。省略するとトラック名が英語になります）。
3. 返答は日本語で、簡潔に書いてください。
