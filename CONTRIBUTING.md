# Contributing to Mittler

Thank you for your interest. Mittler is a video editor inside VS Code, built to be edited by a person and an AI agent together. It is developed by one person in spare time, so replies may be slow. Small, focused changes are the easiest to review.

日本語の説明は下にあります（[日本語](#日本語)）。

## Before you start

- **Windows only.** The editor, setup checks, and tools assume Windows, Python 3.12+, and ffmpeg.
- **Opening a project runs code.** A project's `effects/*.py` is executed when it is rendered. Do not open projects you do not trust, and do not attach projects to an issue unless you wrote every file in them.
- Start with `AGENTS.md` (also the entry point for AI agents) and `docs/ARCHITECTURE.md`.
- No npm dependencies and no build step: the extension runs the JavaScript in the repository as is.

## Reporting a problem

Please include:

- The Mittler version (`package.json` or the Extensions view), Windows version, and Python and ffmpeg versions.
- The output of `python setup/mittler_setup.py --json`.
- The smallest timeline (`*.cut.json`) that reproduces the problem and the steps you took.
- What you expected and what actually happened (a still from `python -m mittler stills` helps for rendering issues).

**Documentation problems are bugs too.** Most documents here are written by and for AI agents and act like code in Japanese: a document that disagrees with the code, a procedure that does not work as written, or wording that makes an agent do the wrong thing is reported and fixed like any other bug. Please say which document and section, and what happened.

Remove API keys, personal paths, and material you may not share before posting. For a security issue, do not open a public issue with the details; contact the maintainer privately through their GitHub profile first.

## Making a change

1. Keep the change small and note what you verified.
2. Run the checks that require no browser, GPU, or media (the same ones run by the GitHub Actions workflow):
   ```
   python -X utf8 tools/smoke_text.py
   python -X utf8 tools/smoke_docs.py
   python -X utf8 tools/smoke_icons.py
   python -X utf8 tools/smoke_setup.py
   ```
   With the rendering Python (`setup/requirements-engine.txt`), also run:
   ```
   python -X utf8 tools/smoke_same.py
   python -X utf8 tools/smoke_bugs.py
   python -X utf8 tools/smoke_package.py
   ```
   The remaining `tools/smoke_*.py` scripts require a headless browser; see the table in `docs/スターターガイド（AI用）.md` (section 7) for what each one covers and how to run it.
3. **Rendering must stay bit-identical.** If you touch `pyengine/` or `effects_lib/`, render stills of the same project at the same timestamps before and after, and compare them byte for byte. Any change that alters existing output needs a clear reason and must be called out.
4. **Effects must be deterministic.** Effects depend only on time, frame number, parameters, and media—no state carried between frames, and random numbers must use a fixed seed.
5. **UI text goes through the dictionaries.** Add every string to both `editor/i18n/en.json` and `editor/i18n/ja.json`, then run `tools/smoke_i18n.py`. Do not use emoji in the UI; icons are Lucide SVGs in `editor/icons/`.
6. **Update the documentation.** Update the docs covering your change (README, guides, `docs/タイムライン形式.md`, `docs/ARCHITECTURE.md`) and add an entry to `CHANGELOG.md`. Treat documentation changes like code changes: keep them consistent with the code and run `tools/smoke_docs.py`.
7. **Keep projects portable.** Projects must not contain absolute paths to Mittler; per-machine values belong in the project's `.mittler/` folder.
8. **Protect secrets and rights.** Never commit API keys, personal paths, or media you do not own.

By contributing, you agree that your contribution is licensed under the MIT License (see `LICENSE`).

## 日本語

Mittler は 1 人が空いた時間で開発しているため、返事が遅れることがあります。小さく、目的が 1 つに絞られた変更がレビューしやすく助かります。

### はじめに

- **Windows 専用**です（Python 3.12 以上・ffmpeg が必要です）。
- **作品を開くとコードが実行されます**（`effects/*.py`）。知らない人の作品は開かないでください。また、Issue に添付するのはすべて自分で書いた作品だけにしてください。
- 開発を始める前に `AGENTS.md` と `docs/ARCHITECTURE.md` をご覧ください。npm 依存やビルド手順はなく、リポジトリ内の JavaScript がそのまま動作します。

### 不具合を報告するとき

以下の情報を添えてください。

- Mittler のバージョン（`package.json` または拡張機能ビュー）・Windows・Python・ffmpeg のバージョン
- `python setup/mittler_setup.py --json` の出力結果
- 再現できる最小のタイムライン（`*.cut.json`）と手順
- 期待した動作と実際に起きたこと（描画の不具合には `python -m mittler stills` の静止画があると助かります）

**文書の不具合もバグです。** ここの文書の多くは、AI エージェントが読むために AI が書いたもので、「日本語で書かれたコード」として扱っています。コードと食い違う・書いてある手順どおりに動かない・エージェントを誤らせる書き方は、ほかのバグと同じように報告・修正します。どの文書のどの節で、何が起きたかを書いてください。

> 投稿前に、API キー・個人のパス・配布できない素材は必ず取り除いてください。セキュリティに関わる問題は、公開 Issue に詳細を書かず、先に GitHub のプロフィールから作者へ直接ご連絡ください。

### 変更を送るとき

- **動作確認の実行**：修正後は、上の「Making a change」の手順 2 にある確認コマンドを実行してください（ブラウザが必要なテストは `docs/スターターガイド（AI用）.md` の 7 の表を参照）。
- **描画の一致**：`pyengine/`・`effects_lib/` を変更した場合は、同じ作品・同じ時刻の静止画を前後で比較し、**ビット単位で同じ**であることを確認してください。絵が変わる変更は理由を明記してお知らせください。
- **エフェクトの決定性**：エフェクトの描画は、時刻・コマ番号・パラメータ・素材だけで決めてください（前のコマの状態を持たせず、乱数は固定のシードを使います）。
- **UI 文言の辞書管理**：画面の文言は `editor/i18n/en.json` と `editor/i18n/ja.json` の両方の辞書に追加し、`tools/smoke_i18n.py` を実行してください。UI に絵文字は使いません。
- **文書の更新**：関連文書（README・ガイド・`docs/タイムライン形式.md`・`docs/ARCHITECTURE.md`）と `CHANGELOG.md` も合わせて更新してください。文書の変更もコードの変更と同じく、コードと合っているかを確かめ、`tools/smoke_docs.py` を実行してください。
- **絶対パス・機密情報の除外**：作品ファイルに Mittler の絶対パスを書かないでください（PC ごとの値は `.mittler/` に置きます）。鍵・個人のパス・自分のものでない素材はコミットしないでください。

送っていただいた変更は、MIT License（`LICENSE`）で配布することに同意いただいたものとします。
