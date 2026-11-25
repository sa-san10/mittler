# Third-party notices

Mittler itself is licensed under the MIT License (see `LICENSE`).

The VSIX bundles only one third-party work: the Lucide icons listed below (ISC License).
**Mittler does not bundle any of the other software listed below.**
The Python packages are installed into a separate Python environment by the user (or via the "Mittler: Setup" command), and ffmpeg and Blender are separate programs that Mittler launches as external processes. Each is distributed under its own license by its respective authors.

## Bundled: Lucide icons

| Work | Version | License | Used for |
|---|---|---|---|
| [Lucide](https://lucide.dev) (`lucide-static` on npm, GitHub `lucide-icons/lucide`) | 1.65.0 | ISC License — Copyright (c) 2026 Lucide Icons and Contributors. Some icons derived from Feather: MIT License — Copyright (c) 2013-present Cole Bemis | the editor's icons (buttons, track headers, menus, notices) |

- Only the icons used by the editor are included, unchanged, in `editor/icons/*.svg` (each file retains its `@license lucide-static v1.65.0 - ISC` line).
- The full license text from the package (ISC, and the MIT notice for the Feather-derived icons) is provided in `editor/icons/LICENSE-lucide.txt`.
- Source: the npm registry tarball `https://registry.npmjs.org/lucide-static/-/lucide-static-1.65.0.tgz` (SHA-256 `d775e4778eb625d20335c38dffc9fedb9c47b03f1c9893c685087c9f592ba630`; verified against the registry's sha512 integrity value).

## Python packages (installed separately, imported by the render engine)

| Package | Version tested | License (as reported by the installed package) | Used for |
|---|---|---|---|
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | image arrays, all rendering |
| opencv-python-headless (OpenCV) | 5.0.0.93 | Apache 2.0 | video/image I/O, filters, transforms |
| Pillow | 12.3.0 | MIT-CMU | text and image drawing |
| moderngl (optional, GPU 3D effects only) | 5.13.0 | MIT | OpenGL rendering for 3D effects |
| glcontext (optional, installed with moderngl) | 3.1.0 | MIT | OpenGL context for moderngl |

These versions match `setup/requirements-engine.txt` and `setup/requirements-3d.txt`. Versions and license names were recorded from `pip show` of the installed packages on the author's PCs (2026-11-13).

## External programs (not bundled, started as separate processes)

| Program | Version tested | License | Used for |
|---|---|---|---|
| FFmpeg | 9.0.2 (gyan.dev "full" build) | LGPL 2.1 or later; builds configured with `--enable-gpl --enable-version3` (such as the gyan.dev full build) are GPL 3.0 or later | decoding, encoding, audio mixing, subtitles |
| Blender (optional, Blender 3D effect only) | 5.2.4 | GNU GPL (version 2 or later, per its `copyright.txt`; bundled libraries are GPL 3 compatible) | rendering 3D scenes for the `blender3d` effect |

Mittler only runs user-installed executables (`ffmpeg.exe`, `blender.exe`); it does not link to them or include any of their code.

---

# サードパーティの表示（日本語）

Mittler 本体のライセンスは MIT（`LICENSE`）です。

VSIX に同梱されているサードパーティ作品は、編集画面のアイコン **Lucide**（版 1.65.0、ISC ライセンス。Feather 由来のアイコンの分は MIT）の 1 点だけです。

- 使用するアイコンだけを内容を変えずに `editor/icons/*.svg` に収め、配布物に含まれるライセンス本文を `editor/icons/LICENSE-lucide.txt` としてそのまま同梱しています。
- 取得元は npm registry の `lucide-static-1.65.0.tgz` です（SHA-256 は上記の英語セクションに記載のとおりで、registry の sha512 と一致することを確認済みです）。

**上記以外のソフトウェアは、いずれも Mittler の VSIX に同梱していません。**

- Python パッケージは、ユーザーが別の Python 環境へインストールします（コマンド「Mittler: 初期設定」からも導入できます）。
- ffmpeg と Blender は別のプログラムであり、Mittler は外部プロセスとして起動するのみです。
- いずれも、それぞれの作者によって各自のライセンスで配布されています。

バージョンとライセンス名は、作者の PC にインストールされているパッケージの `pip show`（2026-11-13）、`ffmpeg -version`（構成の `--enable-gpl --enable-version3`）、および Blender の `copyright.txt` から記載しています。
