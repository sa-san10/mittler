# Changelog

Notable changes to Mittler. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions before 0.9.0 were development builds used by the author and were not published; they are summarized here so the history of each feature is visible.

## [0.9.0] (alpha) - Unreleased

First version prepared for public release. It is an **alpha**: features, file formats, and settings may still change. The extension is marked as a preview in VS Code.

### Changed
- New projects are written with `"format": "mittler/py1"` and `"engine": "mittler"`.
- The current names are `mittler.*` (settings), `MITTLER_*` (environment variables), `.mittler/` (per-project state folder), and the Python package `mittler`.
- Projects and machine settings created with pre-release development builds (the earlier name "claude-cut": `"format": "claude-cut/py1"`, `from ccpy …`, `.claude-cut/`, `claudeCut.*`, `CC_*`) still open and render unchanged. These old names are kept for read-only compatibility; nothing new is written with them.

### Removed
- Leftovers of the earlier remote (SSH) rendering mode. Rendering now always runs on the machine running VS Code (use Remote-SSH to work on another machine).

### Added
- `CHANGELOG.md`, `CONTRIBUTING.md`, and a GitHub Actions workflow that runs checks requiring no browser, GPU, or media.
- `docs/技術集/`: production techniques from the author's earlier videos (person masks, face/hand/pose, beats, lyric timing, beat-matched retiming, H3 video generation and lip sync, image generation, voices, text motion, color, verification), rewritten as general guides.

## [0.8.x] - 2026-11-19

### Added
- Image engine "Nano Banana" (Gemini image generation) for planned shots, supporting up to 14 reference images.
- Any image engine can be called per request; the project setting `settings.image_engine` acts as the default, not a restriction.
- Production hints for agents: easing on every motion, OFL fonts for subtitles and lyrics, and guidance on which engine suits generation vs. partial edits.

## [0.7.x] - 2026-11-18

### Added
- HTML layers (effect `html`): a page in the project (Canvas, CSS, three.js) is rendered frame by frame with headless Chromium and composited. Templates: kinetic text, 3D particles, 3D shapes.
- Agent guide sections on writing prompts for image-to-video and music generation.

### Changed
- Background rendering is off by default.

## [0.6.x] - 2026-11-16

### Added
- Rendered frames are kept losslessly on disk (`work/cache/frames/`) and reused by preview, playback, and export; only the range around an edited clip is re-rendered.
- Incremental export, background pre-rendering with a toggle button, and playback from cached frames with markers on the ruler.

### Changed
- Export start and end times are entered as minutes:seconds, matching the playhead display.

## [0.5.x] - 2026-11-16

### Added
- Frame cache (first version) and in-preview playback of generated video takes.
- `stems-place` API to place separated music stems on tracks.

### Changed
- Normal exports are split into more segments than the number of parallel workers.

### Removed
- The bundled extruded-3D-text effect (projects write their own when needed).

### Fixed
- Blender frame cache keys no longer change when a number is saved as `3` instead of `3.0`.

## [0.4.x] - 2026-11-13

### Added
- MIT license, third-party notices, English README, icons (Lucide), and a notice after installation.
- "False Maria" effect pack: six code-only effects (light and tone map, edge neon, shutter flash, gamma and saturation, fade to black with credits, flying hearts).
- Everything a person can do in the editor is available to agents through `python .mittler/api.py`, including visible UI operations and an auto mode that follows the agent's edits.
- OpenAI image engine for planned shots; `tools/watchdog.py` to supervise heavy jobs (time, CPU, memory, swap, GPU).
- `docs/表現の一覧.md`, a catalog of what can be expressed and how.

## [0.3.0] - 2026-11-13

### Added
- Self-contained VSIX (`python tools/build_vsix.py`) and the command "Mittler: Setup".
- GPU 3D effects (moderngl) and Blender 3D clips.
- English and Japanese UI (default: English), VS Code theme colors, and a "+ New" project dialog.

### Changed
- Projects no longer store absolute paths; per-machine values live in the project's `.mittler/` folder.

## Earlier development - 2026-10

- Timeline editor as a VS Code custom editor for `*.cut.json`, with a Python rendering engine and per-project effect code in `effects/*.py`.
- Tracks for video, images, audio, music, text-to-speech dialogue, subtitles (including ASS), effects, metadata, and planned shots (start/end frame, image generation, video generation, takes, adoption).
- Speed curves and automatic beat matching, per-cut color desk and per-clip color, snapping, on-screen annotations handed to the agent, draft export, master export (upscaling and frame interpolation), and export with loudness normalization.
- Editor state (`.mittler/state.json`, current frame) shared with the agent through a prompt hook.
