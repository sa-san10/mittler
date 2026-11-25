# setup（Mittler の導入・再設定用ファイル）

導入手順は **[docs/スターターガイド.md](../docs/スターターガイド.md)**（短い入口）と **[docs/インストールガイド.md](../docs/インストールガイド.md)**（詳しい説明）を参照してください。このフォルダには、そこで使用するファイルをまとめています。

## ファイル一覧

| ファイル | 内容 |
|---|---|
| `mittler_setup.py` | **初期設定の確認ツール**。必要な環境（VS Code・Python・ffmpeg・描画用パッケージ）を調べ、不足分の導入手順と設定値、および試しの作品で 1 枚描画できるかを確認します。既定では何も変更せず、`--install-venv`・`--install-extension` などを付けた場合のみ導入を行います（使い方は下記） |
| `requirements-engine.txt` | 描画用 Python エンジンのパッケージ一覧 |
| `requirements-av-ai.txt`・`av_ai_cuda12_path.pth` | 動画・音声解析 AI 用のパッケージ一覧と、faster-whisper に CUDA 12 の部品を認識させる設定（インストールガイドの 9。任意） |
| `check-gemini-key.py` | Gemini の API キーが Windows の資格情報マネージャーに登録されているかを確認（キーの値は出力しません） |
| `claude/install-claude-home.ps1` | Claude Code にスキル（`skills/` の中身）を `~/.claude/skills/` へ導入。何度実行しても問題ありません |

## 初期設定の確認（`mittler_setup.py`）

Python の標準ライブラリだけで動作します（Python 3.9 以上であればどの Python でも実行可能）。

```
python setup\mittler_setup.py                                                     確認のみ（何も変更しない。--check と同じ）
python setup\mittler_setup.py --json                                              同じ結果を JSON で出力（エージェント向け）
python setup\mittler_setup.py --python <描く python>                              指定した Python で描画できるかを確認
python setup\mittler_setup.py --no-render                                         試しの 1 枚描画を省略（高速）
python setup\mittler_setup.py --install-venv <フォルダ>                           描画用 venv を作成し requirements-engine.txt を導入（パッケージを取得する）
python setup\mittler_setup.py --install-venv <フォルダ> --with-3d                 同じ venv に requirements-3d.txt（GPU の 3D）も導入
python setup\mittler_setup.py --install-extension                                 VS Code に Mittler を導入（開発版：tools\install_vscode.py を呼び出し。配布版の中から実行したときは導入しない）
python setup\mittler_setup.py --install-venv <フォルダ> --install-extension --dry-run  実行内容のみ確認
```

- **確認項目**：VS Code（`code`・Code.exe）、Git、ffmpeg・ffprobe、描画用 Python（numpy・opencv・Pillow の有無とバージョン）、Mittler 拡張機能の導入状況、前の名前の拡張機能が残っていないか、Claude Code スキルの導入状況、一時フォルダに試しの作品を作って静止画を 1 枚描画できるか。
- **出力と終了コード**：「OK／注意／足りない」の一覧と、次に実行すべきこと（導入コマンドや VS Code の設定 `mittler.render.python` などに書く値）を表示します。不足がある場合は終了コード 1 を返します。
- **VS Code 設定の扱い**：設定ファイル自体は書き換えません（書くべき値を提示するだけです）。既定の場所（`server/defaults.js`）で見つかった項目は「見つかった（設定は要らない）」と表示します。
- **配布版（VSIX）との連携**：VS Code のコマンド「Mittler: 初期設定」が同じ確認を実行し、描画用 Python を導入するときは拡張機能の保存場所（globalStorage）へ `--install-venv` を実行します（`docs/インストールガイド.md` の 3）。出力 JSON の `kind`（`vsix`・`dev`）や `render_python` もここで使われます。
- **動作確認テスト**：`tools/smoke_setup.py` で検証します。

## 作品ごとの Claude Code 設定

作品ごとの Claude Code 設定（`.claude/settings.json` のフック・`AGENTS.md`・`CLAUDE.md`）は、作品作成時に `tools/new_project.js` が `templates/project/` から生成します（Mittler の場所は書かず、その PC 固有の情報は作品の `.mittler/` に置きます）。

以前からある作品のフックを最新の形式に更新する場合は、`python tools/fix_hooks.py <作品の親のフォルダ>` を実行してください（`docs/インストールガイド.md` の 15）。
