// Mittler を VS Code なしで起動する（確認・テスト用）。
//   tools\mittler.cmd serve <作品>\xxx.cut.json [--port 0] [--render-python <python.exe>] [--ffmpeg-dir <ffmpeg の bin>]
//     [--analysis-python <python.exe>] [--analysis-models <フォルダ>] [--voicevox-url <URL>] [--presets-dir <フォルダ>] [--tools-python <python.exe>]
//     [--codex-path <codex CLI>] [--codex-model <モデル>] [--image-engine codex|openai|nanobanana] [--openai-image-model <モデル>] [--openai-image-quality <品質>] [--gemini-image-model <モデル>] [--gemini-image-size 1K|2K|4K] [--lang en|ja]（画面の言葉。既定 en）[--blender <blender.exe>]（Blender の 3D）
//     [--esrgan <exe>] [--esrgan-model <モデル>] [--rife <exe>] [--master-scale 2] [--master-fps 60] [--master-out 1080] [--cache-gb 50]（🏆 マスター書き出し）
//   描くのはこのPC（python は --render-python、無ければタイムラインの render.python → 既定 → PATH の python から探す）。--local は前の書き方（付けても同じ）
//   オプションは VS Code の設定 mittler.* と同じもの（無ければ server/defaults.js の既定値。一覧は docs/インストールガイド.md の 12）
// 起動すると編集画面の URL（トークンつき）を1行目に出す。Ctrl+C か POST /api/quit（X-Mittler-Token が要る）で止まる。
// プロセスごと止める（taskkill など）と、描画サーバー（python）が残るので、/api/quit で止めること。
'use strict';
const { start } = require('./server');

const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : def; };
const timeline = args.find((a, i) => !a.startsWith('--') && (i === 0 || !args[i - 1].startsWith('--') || args[i - 1] === '--local'));
if (!timeline) { console.error('usage: main.js <timeline.cut.json> [--port N] [--render-python PY] [--ffmpeg-dir DIR] [--analysis-python PY] [--analysis-models DIR] [--voicevox-url URL] [--presets-dir DIR] [--tools-python PY] [--codex-path EXE] [--codex-model NAME] [--image-engine codex|openai|nanobanana] [--openai-image-model NAME] [--openai-image-quality Q] [--gemini-image-model NAME] [--gemini-image-size 1K|2K|4K] [--esrgan EXE] [--esrgan-model NAME] [--rife EXE] [--master-scale N] [--master-fps N] [--master-out N] [--cache-gb N]'); process.exit(2); }

let srv = null;
const quit = () => { if (srv) srv.close(); setTimeout(() => process.exit(0), 22000).unref(); };  // close() が描画サーバーに /quit を送ってから止める（起動の途中なら待つ）
Promise.resolve().then(() => start({ timeline, port: +opt('--port', 0), onQuit: quit,
  local: { python: opt('--render-python', ''), ffmpegDir: opt('--ffmpeg-dir', '') },
  analysisPython: opt('--analysis-python', ''), analysisModels: opt('--analysis-models', ''), voicevoxUrl: opt('--voicevox-url', ''),
  presetsDir: opt('--presets-dir', ''), python: opt('--tools-python', ''), codexPath: opt('--codex-path', ''), codexModel: opt('--codex-model', ''),
  imageEngine: opt('--image-engine', ''), openaiImageModel: opt('--openai-image-model', ''), openaiImageQuality: opt('--openai-image-quality', ''),
  geminiImageModel: opt('--gemini-image-model', ''), geminiImageSize: opt('--gemini-image-size', ''),
  blenderPath: opt('--blender', ''),
  cacheDir: opt('--cache-dir', ''),  // ためた絵などの置き場（無ければ環境変数 MITTLER_CACHE_DIR → 作品の work/）  // Blender の 3D の blender.exe（無ければ環境変数 MITTLER_BLENDER → 既定）
  bakeJobs: opt('--bake-jobs', ''),  // 裏で先に描く並列の数（空＝自動、0＝裏で描かない）
  lang: opt('--lang', ''),  // 画面の言葉（en・ja）。付けなければ既定（英語。編集画面が覚えた言葉があればそれ）
  master: { esrgan: opt('--esrgan', ''), esrganModel: opt('--esrgan-model', ''), rife: opt('--rife', ''), scale: opt('--master-scale', ''), fps: opt('--master-fps', ''),
    outHeight: opt('--master-out', ''), cacheGb: opt('--cache-gb', '') } })).then(s => {
  srv = s;
  console.log(s.url); console.log(`project ${s.project}`);
  process.on('SIGINT', quit); process.on('SIGTERM', quit);
}).catch(e => { console.error(e); process.exit(1); });
