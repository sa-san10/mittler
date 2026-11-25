// Mittler：PC ごとの設定が無いときの既定値（ここが1か所）。設定の一覧（項目／設定名／既定値）と決まりは docs/インストールガイド.md の「12. 設定の一覧」。
// 既定は「空＝PATH で探す・設定で指定する」。ほかの PC では VS Code の設定（mittler.*。古い名前の claudeCut も読む：names.js）で決める。
// 隣に defaults.author.json（作者の PC の置き場）があれば、その値を既定にする（作者の PC は設定ゼロで今までと同じに動く＝後方互換。公開用の書き出しには入らない）。
// Python の側の既定値（解析のモデルの置き場 AV_AI_MODELS、H3 の受け渡しの MITTLER_MYDRIVE・MITTLER_H3_ROOT、Codex の場所・モデル MITTLER_CODEX・MITTLER_CODEX_MODEL）は、
// それを使う Python のファイルの頭にある（pyengine/mittler/analyze.py・tools/h3_jobs.py・tools/gen/codex_image.py。作者の PC の値は同じ defaults.author.json から読む）。
'use strict';
const fs = require('fs');
const path = require('path');

// 作者の PC の既定値（無ければ {}。読めなくても動く）
const AUTHOR = (() => { try { return JSON.parse(fs.readFileSync(path.join(__dirname, 'defaults.author.json'), 'utf8')); } catch (e) { return {}; } })();
const AM = AUTHOR.master || {};

module.exports = {
  // 描く python（numpy・opencv・Pillow）。PC の設定 mittler.render.python → タイムラインの render.python → これ（空なら飛ばす）→ PATH の python
  renderPython: AUTHOR.renderPython || '',
  // ffmpeg・ffprobe のフォルダの候補。PC の設定 mittler.render.ffmpegDir → これ（あれば）→ PATH
  ffmpegDirs: AUTHOR.ffmpegDirs || [],
  // 🔬 解析の python。PC の設定 mittler.analysis.python → タイムラインの settings.analysis_python → これ（空なら「解析の python が無い」）
  analysisPython: AUTHOR.analysisPython || '',
  // VOICEVOX のエンジン。PC の設定 mittler.voicevox.url → これ（クリップの voicevox.url があればそれが勝つ）
  voicevoxUrl: 'http://127.0.0.1:50021',
  // 画面の言葉（'en'・'ja'）。PC の設定 mittler.language（単体は --lang）→ これ（既定は英語）
  language: 'en',
  // 補助の道具（ジョブ係 tools/jobs.py・TTS tools/tts_gen.py・H3 のアダプタ tools/h3_jobs.py）を動かす python。PC の設定 mittler.tools.python → これ（PATH）
  toolsPython: 'python',
  // キャラ設定のプリセット。PC の設定 mittler.presetsDir → 環境変数 MITTLER_PRESETS → この候補のうち characters.json があるもの → 無し（「＋プリセットから」は理由つきで出ない）。
  // 候補：開発版（リポジトリから動かす）ならリポジトリの隣の presets/characters（前からの既定）、作者の PC の置き場（defaults.author.json）。
  // 配布版（VSIX。拡張の置き場に mittler_build.json がある）は、拡張の置き場の隣を見ない（拡張のフォルダの隣は VS Code の拡張の一覧の中なので。2026-11-13 パッケージ化）
  presetsDirs: [
    ...(fs.existsSync(path.join(__dirname, '..', 'mittler_build.json')) ? [] : [path.resolve(__dirname, '..', '..', 'presets', 'characters')]),
    ...(AUTHOR.presetsDirs || []),
  ],
  // Blender の 3D（effects_lib/common/blender3d.py）で使う blender.exe。PC の設定 mittler.blender.path（単体は --blender）→ 環境変数 MITTLER_BLENDER → これ（あれば）→ PATH の blender。
  // 描くプロセスには環境変数 MITTLER_BLENDER で渡す（Python の側の既定は pyengine/mittler/blender.py の BLENDER_DEFAULT。同じ値）
  blenderPath: AUTHOR.blenderPath || '',
  // 🏆 マスター書き出し（機能追加案03 v2：4K キャンバスでエフェクトも描く・ネイティブ 60fps）。PC の設定 mittler.master.* → これ。
  // 同じ値は単体の mittler master の既定（pyengine/mittler/master.py の DEFAULTS）にもある。道具の exe は空なら「設定で指定」
  master: {
    esrgan: AM.esrgan || '',                                   // アプスケ（Real-ESRGAN ncnn-vulkan）の exe
    esrganModel: 'realesr-animevideov3',                      // アプスケのモデル
    rife: AM.rife || '',                                       // 補間（RIFE ncnn-vulkan）の exe
    scale: 2,                                                  // キャンバスの倍率（ctx.scale）
    fps: 60,                                                   // 出力の fps（エフェクトはこの fps で描く）
    outHeight: 1080,                                           // 書き出しの高さ（0 なら縮めずに 4K のまま納品）
    cacheGb: 50,                                               // アプスケ・補間のキャッシュの上限（GB）
    jobs: 0,                                                   // ③ 描くの並列の既定。0＝自動（mittler master が CPU の数の半分と空いているメモリ（1本 2.5 GB）から。論理 CPU 24 の作者の PC で 12。master.py の render_jobs）
  },
  // 🏆 アップスケールの名前 → Real-ESRGAN のモデル（作品の settings.master.upscale・クリップの upscale。PC の設定ではない）。決まりの正本は pyengine/mittler/master.py の
  // UPSCALE_KINDS（モデルの倍率も）。ここは編集画面の表示と /api/master のため（同じことは tools/smoke_same.py が確かめる）
  masterUpscale: { anime: 'realesr-animevideov3', real: 'realesrgan-x4plus' },
  // 🏆 アップスケールなし（60fps だけ。2026-10-31）の名前：作品の settings.master.upscale・窓の選択がこれなら、1 倍のキャンバスで 60fps に（アプスケしない・縮めない）。
  // 正本は pyengine/mittler/master.py の UPSCALE_NONE（同じことは tools/smoke_same.py が確かめる）。クリップの upscale には書けない
  masterNoUpscale: 'none',
};
