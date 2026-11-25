// Mittler: ローカルサーバー（編集画面・描画ページ・タイムラインAPI・変更通知）
// VS Code 拡張の中（extension.js）からも、単体（main.js）からも同じものを起動する。外部依存なし（Node 標準だけ）。
// 127.0.0.1 だけで待ち受け、Host を確かめ（DNS リバインディング対策）、書き込みは起動ごとのトークンが必要。
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..');
const DEF = require('./defaults');  // PC ごとの設定が無いときの既定値（1か所。docs/インストールガイド.md の 12）
const NAMES = require('./names');
const ENV0_CACHE_DIR = process.env.MITTLER_CACHE_DIR || '';  // 起動したときの環境変数（設定を消したら、これに戻す）   // 名前と、古い名前（claude-cut）の互換（1か所）
const ATOMIC = require('./atomic');  // ファイルの置きかえ（rename）：開かれていて失敗したら短く待ってやり直す
const I18N = require('./i18n');     // 画面の言葉（英語・日本語。辞書は editor/i18n/*.json）
const OPS = require('../editor/ops');  // 編集画面のボタンと API で同じタイムラインの書きかえ（1か所。2026-11-15）
// 🎬 生成のエンジン → アダプタの対応表（1か所。ジョブ係 tools/jobs.py も同じものを読む。エンジンの足し方は docs/H3受け渡し契約.md の「エンジンを足すには」）
const ENGINES = JSON.parse(fs.readFileSync(path.join(ROOT, 'tools', 'engines.json'), 'utf8'));
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
  '.gif': 'image/gif', '.svg': 'image/svg+xml', '.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime',
  '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.ogg': 'audio/ogg', '.ttf': 'font/ttf', '.otf': 'font/otf', '.woff2': 'font/woff2',
};

const CHUNK = 2 << 20;
const { execFile } = require('child_process');

// 映像クリップのスタートフレーム（タイムラインに出す小さな絵）。ffmpeg で1コマ切り出して <プロジェクト>/.mittler/thumbs/ にためる（.mittler＝作品の状態フォルダ。古い作品は .claude-cut。names.js）。
// 同時に動かす ffmpeg は4本まで。
const THUMB_H = 96;
let thumbRunning = 0; const thumbQueue = [];
function thumbJob(fn) { return new Promise((ok, ng) => { thumbQueue.push({ fn, ok, ng }); pumpThumbs(); }); }
function pumpThumbs() {
  while (thumbRunning < 4 && thumbQueue.length) {
    const j = thumbQueue.shift(); thumbRunning++;
    j.fn().then(j.ok, j.ng).finally(() => { thumbRunning--; pumpThumbs(); });
  }
}
const run = (cmd, args) => new Promise((ok, ng) => execFile(cmd, args, { timeout: 60000, windowsHide: true }, (e, out) => e ? ng(e) : ok(String(out))));
async function probeDur(file) { return parseFloat(await run('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file])) || 0; }
const IGNORE = new Set(['.git', 'work', 'output', ...NAMES.STATE_DIRS, 'node_modules']);
const MEDIA_EXT = /\.(png|jpe?g|webp|gif|bmp|mp4|mov|mkv|webm|avi)$/i;  // 変わったら 'media' も知らせる（編集画面が絵を読み直す）
// GET でも副作用があるもの（描画サーバーを起動する・ffmpeg／ffprobe を動かす・ファイルを書く）：トークンが要る（X-Mittler-Token か ?token=。古い名前の X-CC-Token も受ける：names.js の tokenOf）
const TOKEN_GET = new Set(['/api/status', '/api/thumb', '/api/takethumb', '/api/cachemap', '/api/cframe', '/api/wave', '/api/frame', '/api/effects', '/api/effects_lib', '/api/assets', '/api/new_project']);
let lastNewProject = '';  // 🆕 編集画面の「新規」で直前に作った作品のフォルダ（/api/new_project/reveal が開けるのはここだけ）
// /project/ で配らないフォルダ：.git と状態フォルダ .mittler・.claude-cut（server.json のトークン・state.json など。古い名前のほうも配らない）。書き込みの記録（annotations）は /api/annotation から
const HIDDEN_DIRS = new Set(['.git', ...NAMES.STATE_DIRS]);
// Windows は大文字小文字・名前の終わりの . と空白・短い名前（8.3）でも同じ場所を指すので、名前を正規化して比べ、実在すれば本当の場所（realpath）でも比べる
function hiddenIn(base, f) {
  const segs = (b, x) => { const r = path.relative(b, x); return r && !r.startsWith('..') && !path.isAbsolute(r) ? r.split(/[\\/]/) : []; };
  const bad = s => HIDDEN_DIRS.has(s.split(':')[0].toLowerCase().replace(/[. ]+$/, ''));  // ':' の後ろ（NTFS の代替データストリーム）も外して比べる
  if (segs(base, f).some(bad)) return true;
  let rb, rf; try { rb = fs.realpathSync.native(base); rf = fs.realpathSync.native(f); } catch (e) { return false; }
  return segs(rb, rf).some(bad);
}

// base の中だけを返す（.. や絶対パスで外に出さない）
function inside(base, rel) {
  const p = path.resolve(base, '.' + path.sep + rel);
  return p === base || p.startsWith(base + path.sep) ? p : null;
}

// 静止ファイル。音声・動画のシークのため Range（206）に対応する
function sendFile(req, res, file, cache) {
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) { res.writeHead(404); res.end('not found'); return; }
    const type = MIME[path.extname(file).toLowerCase()] || 'application/octet-stream';
    const head = { 'Content-Type': type, 'Accept-Ranges': 'bytes', 'Cache-Control': cache || 'no-store' };
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
    if (m && (m[1] || m[2])) {
      // 終わりが開いた要求（bytes=N-）は 2MB で区切る。音声・動画が接続を握りっぱなしにすると、
      // ブラウザの同時接続（1ホスト6本）が埋まってシークの読み込みが止まるため
      let a = m[1] ? +m[1] : st.size - +m[2], b = m[1] && m[2] ? +m[2] : (m[1] ? Math.min(st.size - 1, a + CHUNK - 1) : st.size - 1);
      if (a < 0) a = 0; if (b >= st.size) b = st.size - 1;
      if (a > b) { res.writeHead(416, { 'Content-Range': `bytes */${st.size}` }); res.end(); return; }
      res.writeHead(206, Object.assign(head, { 'Content-Range': `bytes ${a}-${b}/${st.size}`, 'Content-Length': b - a + 1 }));
      if (req.method === 'HEAD') return res.end();
      pipeFile(fs.createReadStream(file, { start: a, end: b }), res); return;
    }
    res.writeHead(200, Object.assign(head, { 'Content-Length': st.size }));
    if (req.method === 'HEAD') return res.end();
    pipeFile(fs.createReadStream(file), res);
  });
}
// ファイルを読む途中の失敗（ほかのプロセスが開いていて読めない・読んでいる間に消えた）：その返事だけを切る。
// 前は error の受けが無く、Node のプロセスごと（VS Code の中なら拡張のプロセスごと）落ちた（2026-11-12）
function pipeFile(stream, res) {
  stream.on('error', e => { console.error('[mittler] ファイルを読めない:', e.message); res.destroy(); });
  stream.pipe(res);
}

function readBody(req, limit = 32 << 20) {
  return new Promise((ok, ng) => {
    const bufs = []; let n = 0;
    req.on('data', b => { n += b.length; if (n > limit) { ng(new Error('too large')); req.destroy(); } else bufs.push(b); });
    req.on('end', () => ok(Buffer.concat(bufs))); req.on('error', ng);
  });
}

// opts: { timeline: タイムラインのファイル, port: 0 で空きポート,
//         openFile: (絶対パス) => void（VS Code でファイルを開く。拡張から渡す）,
//         local: { python, ffmpegDir }（描く python・ffmpeg のフォルダ。PC ごとの設定。空なら探す。pyrender.js）,
//         python: 補助の道具（ジョブ係・TTS・H3 のアダプタ）を動かす python（無ければ PATH の python）,
//         analysisPython: 🔬 解析の python、analysisModels: 解析のモデルの置き場（解析のプロセスの AV_AI_MODELS）,
//         voicevoxUrl: VOICEVOX のエンジン、presetsDir: キャラ設定のプリセットのフォルダ,
//         codexPath・codexModel: 🎬 の絵の Codex CLI の場所とモデル（ジョブ係に環境変数 MITTLER_CODEX・MITTLER_CODEX_MODEL で渡す）,
//         imageEngine: 🎬 の絵の既定のエンジン（codex・openai・nanobanana。空なら tools/engines.json の既定）, openaiImageModel・openaiImageQuality: OpenAI の絵のモデル・品質（空なら tools/openai_image_jobs.py の既定）, geminiImageModel・geminiImageSize: Nano Banana の絵のモデル・解像度（空なら tools/gemini_image_jobs.py の既定）,
//         blenderPath: Blender の 3D の blender.exe（描くプロセスに環境変数 MITTLER_BLENDER で渡す）,
//         master: { esrgan, esrganModel, rife, scale, fps, outHeight, cacheGb }（🏆 マスター書き出し。空の項目は既定）,
//         openExternal: (URL) => void（🎵 suno.com の曲のページをユーザーの既定のブラウザで開く。拡張から渡す。無ければこの PC の既定のブラウザ） }
// どれも PC ごとの設定（VS Code の mittler.*、単体は main.js のオプション）。空なら server/defaults.js の既定値（設定ゼロで今までと同じ）
// タイムラインの format は "mittler/py…"（Python エンジン。このPCの描画サーバー、pyrender.js で描く）。前の名前の "claude-cut/py…" も同じ形として開く（names.js の formatOk）。
// 描くのはいつもこのPC。ほかの PC で描くときは VS Code の Remote-SSH でその PC に接続して開く（ssh のモードは 2026-10-30 に外した）。
const WHERE = 'このPC';  // 描くPC（/api/status の where・state.json の render_on。いつもこのPC）
const warnedSsh = new Set();  // ssh のモードの設定（render.host・render.remote）が残っている作品：ログに1度だけ知らせる
function start(opts) {
  const timelineFile = path.resolve(opts.timeline);
  const project = path.dirname(timelineFile);
  const token = crypto.randomBytes(16).toString('hex');
  const clients = new Set();
  let port = 0;
  // 画面の言葉（'en'・'ja'。既定は英語）：PC の設定（VS Code の mittler.language・単体は --lang）→ server/defaults.js。編集画面で切り替えると POST /api/lang で変わる。
  // サーバーが画面に返す文（エラー・ジョブの知らせ）と、子のプロセス（エンジン・ジョブ係・TTS）の文（環境変数 MITTLER_LANG）がこの言葉になる。ログ（VS Code の出力）は日本語のまま
  let lang = I18N.norm(opts.lang || DEF.language);
  let langSource = opts.lang && opts.langExplicit !== false ? 'setting' : 'default';  // 'setting'：人が決めた（編集画面はこれに従う）・'default'：決めていない（編集画面が覚えた言葉があればそれ）
  let langSetting = lang;  // 人が決めた言葉（設定・切り替え）。URL の &lang= で開いた画面が伝える一時の言葉（save: false）では変えない
  process.env.MITTLER_LANG = lang;
  // 子のプロセス（描画サーバー・書き出しの区間・ジョブ係・TTS・アダプタ・解析）は、Mittler の置き場に __pycache__ を書かない（2026-11-13 パッケージ化）。
  // 配布版（VSIX）の拡張の置き場は、拡張を更新すると入れかわる「読むだけ」の場所として扱うため。エンジンを呼ぶ所の -B は書き出しの区間など孫には届かないので、環境変数で渡す
  process.env.PYTHONDONTWRITEBYTECODE = '1';
  // Blender の 3D（effects_lib/common/blender3d.py）：blender.exe の場所を、子のプロセス（描画サーバー・書き出し）に環境変数 MITTLER_BLENDER で渡す。
  // PC の設定 mittler.blender.path（単体は --blender）→ 環境変数 MITTLER_BLENDER → 既定（server/defaults.js の blenderPath。あれば）。無ければ渡さない（Python の側が探して、無ければ理由つきで止まる）
  const blenderPath = opts.blenderPath || NAMES.env('BLENDER') || (fs.existsSync(DEF.blenderPath) ? DEF.blenderPath : '');
  if (blenderPath) process.env.MITTLER_BLENDER = blenderPath;
  // ためた絵などの置き場（作り直せる大きなもの）：PC の設定 mittler.cache.dir（単体は --cache-dir）→ 起動したときの環境変数 MITTLER_CACHE_DIR → 無し（作品の work/）。
  // 子のプロセス（描画サーバー・書き出し・マスター・裏で描く係）にも環境変数 MITTLER_CACHE_DIR で渡す（2026-11-22。作品を同期していても、ためた絵を送らないため）
  const cacheDirSet = opts.cacheDir || ENV0_CACHE_DIR;
  if (cacheDirSet) process.env.MITTLER_CACHE_DIR = cacheDirSet; else delete process.env.MITTLER_CACHE_DIR;
  const cacheRoot = () => NAMES.cacheRoot(project);
  const $t = (k, v) => I18N.tr(lang, k, v);  // 画面に返す文（名前は編集画面と同じ $t。tr はトラックの変数の名前に使っているので避けた）
  const KE = I18N.keyedError;                 // 鍵つきの例外（メッセージは日本語。画面に返すときに E で今の言葉に）
  const E = e => I18N.errText(lang, e);       // 例外 → 画面に返す文（鍵があれば訳す。無ければ生の文：Python の例外の文などはそのまま）

  const readTimeline = () => JSON.parse(fs.readFileSync(timelineFile, 'utf8'));
  // このサーバーが起動した、時間のかかる子のプロセス（🔬 解析・TTS・再生用の動画・動画の音の取り出し）。サーバーを止めるとき（ウィンドウの再読み込み・/api/quit）に一緒に止める。
  // 前は止めていなかったので、解析の途中で画面を閉じると解析の python が走り続け（結果は取り込まれない）、もう一度頼むと GPU を取り合った（2026-11-12）。
  // 子の子（venv の python は起動用の python.exe が本体を起こす・解析が起こす ffmpeg）も止めるため、Windows は taskkill /T
  // （ジョブ係 tools/jobs.py は入れない：わざと切り離して動かしている。書き出しは <出力>.cancel で止める）
  // taskkill が断られる（終わりの番号が 0 でない）ときは、子孫を数えて1つずつ TerminateProcess（process.kill）。作者の PC のサービス用の
  // アカウントでは、taskkill が自分のプロセスにも 5 秒ほど待ってから「Access denied」になり、解析の python が止まらなかった。
  // 起動用の python.exe（venv）だけを止めても、本体の python と孫は残った（2026-11-13 に作者の PC で測った）
  const ttsOut = new Set();  // 生成している途中の TTS の出力の名前（/api/tts）
  const kids = new Set();
  const track = pr => { kids.add(pr); const off = () => kids.delete(pr); pr.once('exit', off); pr.once('error', off); return pr; };
  function killDescendants(pid) {
    const cp = require('child_process');
    let rows = '';
    // 親子の一覧は WMI（Get-CimInstance）でなく Toolhelp で取る（作者の PC のサービス用のアカウントでは WMI も Access denied だった）
    try { rows = cp.spawnSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(__dirname, 'proctree.ps1')], { encoding: 'utf8', windowsHide: true, timeout: 20000 }).stdout || ''; } catch (e) { }
    const parent = new Map();
    for (const ln of rows.split(/\r?\n/)) { const m = ln.trim().match(/^(\d+) (\d+)$/); if (m) parent.set(+m[1], +m[2]); }
    const all = [pid];
    for (let grew = true; grew;) { grew = false; for (const [c, p] of parent) if (all.includes(p) && !all.includes(c)) { all.push(c); grew = true; } }
    for (const p of all) { try { process.kill(p); } catch (e) { } }
  }
  function killTree(pr) {
    if (!pr || !pr.pid || pr.exitCode !== null) return;
    if (process.platform !== 'win32') { try { pr.kill(); } catch (e) { } return; }
    const hard = () => { if (pr.exitCode === null) killDescendants(pr.pid); };
    try { require('child_process').spawn('taskkill', ['/T', '/F', '/PID', String(pr.pid)], { windowsHide: true, stdio: 'ignore' }).on('error', hard).on('exit', code => { if (code !== 0) hard(); }); } catch (e) { hard(); }
  }
  // アセットの一覧（素材の根 root の assets/。無ければ root ごと）。音・動画の長さは ffprobe で測ってためる
  const durCache = new Map();
  async function listAssets() {
    const tl = readTimeline(); const root = path.resolve(project, tl.root || '.');
    const top = fs.existsSync(path.join(root, 'assets')) ? path.join(root, 'assets') : root;
    const out = { images: [], videos: [], audio: [], bgm: [], voice: [], fonts: [], effects: [] };
    const walk = (d, depth) => {
      if (depth > 6) return;
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        if (e.name.startsWith('.') || e.name === '__pycache__' || e.name === 'rejected') continue;
        const f = path.join(d, e.name);
        if (e.isDirectory()) { walk(f, depth + 1); continue; }
        const ext = path.extname(e.name).toLowerCase(), rel = path.relative(root, f).split(path.sep).join('/');
        const it = { path: rel, name: e.name, bytes: fs.statSync(f).size };
        if (['.png', '.jpg', '.jpeg', '.webp'].includes(ext)) out.images.push(it);
        else if (['.mp4', '.mov', '.webm', '.mkv'].includes(ext)) out.videos.push(it);
        else if (['.wav', '.mp3', '.m4a', '.ogg', '.flac'].includes(ext)) (/(^|\/)(bgm|music)\//.test(rel) ? out.bgm : /(^|\/)voice\//.test(rel) ? out.voice : out.audio).push(it);  // music/：🎵 Suno の曲（assets/music）
        else if (['.ttf', '.otf', '.ttc'].includes(ext)) out.fonts.push(it);
      }
    };
    walk(top, 0);
    const probes = [...out.videos, ...out.audio, ...out.bgm, ...out.voice].slice(0, 400);
    await Promise.all(probes.map(async it => {
      const f = path.join(root, it.path); const k = `${f}|${it.bytes}`;
      if (!durCache.has(k)) durCache.set(k, await thumbJob(() => probeDur(f)).catch(() => 0));  // 同時に動かす ffprobe は 4 本まで（前は、最初の 1 回で 400 本まで一度に起動した）
      it.dur = durCache.get(k);
    }));
    try { out.effects = fs.readdirSync(path.join(project, 'effects')).filter(n => n.endsWith('.py')).map(n => ({ name: n.replace(/\.py$/, ''), path: `effects/${n}` })); } catch (e) { }
    return out;
  }
  // 🎬 予定クリップのまわり（参照の読み取り・生成のジョブ）：素材の根・タイムライン・キャラ設定・そのクリップ
  function planCtx(clipId, which) {
    const tl = readTimeline(), root = path.resolve(project, tl.root || '.');
    let chars = { characters: [] };
    try { chars = JSON.parse(fs.readFileSync(path.join(project, tl.characters || 'characters.json'), 'utf8')); } catch (e) { }
    const clip = (tl.tracks || []).flatMap(t => t.clips || []).find(c => c.id === clipId && c.type === 'plan');
    return { root, project, tl, chars, clip, which, lang };  // lang：参照のまちがいの文の言葉（送るプロンプトの文は変えない）
  }
  // ---- キャラ設定のプリセット（presets/characters/characters.json＋images・profiles・thumbs。作り方は importers/char_presets/build.py）----
  // 置き場：PC の設定 → 環境変数 MITTLER_PRESETS（古い名前 CC_PRESETS も）→ 既定の候補のうち characters.json があるもの（server/defaults.js）→ 無し（''）
  const presetsDir = () => opts.presetsDir || NAMES.env('PRESETS') || DEF.presetsDirs.find(d => fs.existsSync(path.join(d, 'characters.json'))) || '';
  function readPresets() {
    if (!presetsDir()) throw KE('srv.noPresetsDir');  // 置き場が決まっていない（配布版の既定）。前は「リポジトリの隣」を読んだ
    return JSON.parse(fs.readFileSync(path.join(presetsDir(), 'characters.json'), 'utf8'));
  }
  function projectChars() {
    const tl = readTimeline(), f = path.join(project, tl.characters || 'characters.json');
    let d = { characters: [] }; try { d = JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { }
    if (!d.characters) d.characters = [];
    return { tl, f, d };
  }
  function listCharPresets() {
    let pr; try { pr = readPresets(); } catch (e) { return { dir: presetsDir(), characters: [], error: presetsDir() ? $t('srv.noPresets', { dir: presetsDir() }) : E(e) }; }
    const have = new Set(projectChars().d.characters.map(c => c.id));
    return { dir: presetsDir(), characters: pr.characters.map(c => ({ id: c.id, name: c.name, color: c.color, profile: String(c.profile || '').slice(0, 120),
      variants: Object.keys(c.images || {}), thumb: fs.existsSync(path.join(presetsDir(), 'thumbs', c.id + '.jpg')), voice: ((c.tts || {}).gemini || {}).voice || '', notes: c.notes || [], in_project: have.has(c.id) })) };
  }
  // 作品に写す：立ち絵 → <素材の根>/assets/characters/<id>/、設定の文書 → <作品>/characters/、characters.json に1人足す（パスは写した先に）
  function addCharPreset(id, overwrite) {
    const pr = readPresets(), c = pr.characters.find(x => x.id === id);
    if (!c) throw KE('srv.presetMissing', { id });
    const { tl, f, d } = projectChars(), root = path.resolve(project, tl.root || '.');
    const i = d.characters.findIndex(x => x.id === id);
    if (i >= 0 && !overwrite) throw KE('srv.presetExists', { name: c.name, id });
    const copy = rel => {
      if (!rel) return '';
      const dst = `assets/characters/${id}/${path.basename(rel)}`;
      fs.mkdirSync(path.join(root, 'assets', 'characters', id), { recursive: true });
      fs.copyFileSync(path.join(presetsDir(), rel), path.join(root, dst));
      return dst;
    };
    const docs = (c.profile_doc || []).map(rel => {
      const dst = `characters/${path.basename(rel)}`;
      fs.mkdirSync(path.join(project, 'characters'), { recursive: true });
      fs.copyFileSync(path.join(presetsDir(), rel), path.join(project, dst));
      return dst;
    });
    const ent = { id: c.id, name: c.name, color: c.color, image: copy(c.image), profile: c.profile || '', look: c.look || '', tts: JSON.parse(JSON.stringify(c.tts || {})) };
    const imgs = Object.fromEntries(Object.entries(c.images || {}).map(([k, v]) => [k, copy(v)]));
    if (Object.keys(imgs).length) ent.images = imgs;
    if (docs.length) ent.profile_doc = docs;
    if ((c.notes || []).length) ent.notes = c.notes;
    ent.from_preset = { id: c.id, built: pr.built || '' };
    if (i >= 0) d.characters[i] = ent; else d.characters.push(ent);
    fs.writeFileSync(f, JSON.stringify(d, null, 1) + '\n');
    log(`キャラのプリセットを写した：${c.name}（${id}）`);
    return { ok: true, id, name: c.name };
  }
  // ---- 編集画面の状態を Claude に（状態フォルダの state.json と、止めたときの1コマ current_frame.jpg）----
  let lastFrame = null;
  const FRAME_HEADERS = ['x-mittler-t', 'x-mittler-ms', 'x-mittler-loads', 'x-mittler-prof', 'x-mittler-cache'];  // 描画サーバーの応答ヘッダのうち、編集画面へそのまま渡すもの（x-mittler-prof は prof=1 の計測のときだけ。x-mittler-cache はディスクにためた絵のとき）
  const live = { busy: false, wait: null };  // プレビューの絵（/api/frame?live=1）：描いている1枚と、待っている最新の1枚
  async function runLive(job) {
    live.busy = true;
    try {
      if (job.gone) return;
      await renderer.waitReady();
      if (job.gone) return;
      const r = await renderer.frame(job.t, job.q, null, { prof: job.prof, scale: job.scale, draft: job.draft });
      if (r.status === 200 && (job.q == null || +job.q >= 80) && !job.draft) lastFrame = { t: +job.t, body: r.body };  // ドラフトの絵は Claude に見せる1コマにしない
      if (job.gone) return;
      const h = { 'Content-Type': r.headers['content-type'] || 'application/octet-stream', 'Cache-Control': 'no-store' };
      for (const k of FRAME_HEADERS) if (r.headers[k]) h[k] = r.headers[k];
      job.res.writeHead(r.status, h); job.res.end(r.body);
    } catch (e) { if (!job.gone && !job.res.headersSent) send(job.res, 500, { error: String(e.message || e) }); }
    finally {
      live.busy = false;
      const next = live.wait; live.wait = null;
      if (next) runLive(next);
    }
  }
  // 作品の状態フォルダ：.mittler/（今までの作品は .claude-cut/ のまま。決まりは names.js の stateDirName。サーバーが動いているあいだは変えない）
  const STATE_NAME = NAMES.stateDirName(project);
  const stateDir = () => path.join(project, STATE_NAME);
  const serverInfo = () => path.join(stateDir(), 'server.json');
  function writeState(st) {
    fs.mkdirSync(stateDir(), { recursive: true });
    st.open = true; st.saved = new Date().toISOString(); st.project_dir = project; st.timeline_file = timelineFile;
    st.render_on = WHERE;
    if (st.frame_t != null && lastFrame && Math.abs(lastFrame.t - st.frame_t) < 1e-6) {
      const f = path.join(stateDir(), 'current_frame.jpg'), tmp = f + '.part';
      fs.writeFileSync(tmp, lastFrame.body); ATOMIC.replace(tmp, f);
      st.frame_image = STATE_NAME + '/current_frame.jpg'; st.frame_image_t = lastFrame.t;
    } else {
      try { const o = JSON.parse(fs.readFileSync(path.join(stateDir(), 'state.json'), 'utf8')); if (o.frame_image) { st.frame_image = o.frame_image; st.frame_image_t = o.frame_image_t; st.frame_image_old = true; } } catch (e) { }
    }
    const pend = pendingAnnotations(); if (pend.length) st.annotations_pending = pend; else delete st.annotations_pending;
    const f = path.join(stateDir(), 'state.json'), tmp = f + '.part';
    fs.writeFileSync(tmp, JSON.stringify(st, null, 1)); ATOMIC.replace(tmp, f);
    // いちばん最近さわった編集画面（作品をまたいで 1 つ）：一時フォルダの mittler/recent.json。フック（tools/mittler_state.py）が、会話している作品と
    // 別の作品の編集画面を触っていたら、そちらの今をそえる（2026-11-14 使ってみた知らせ：別のタブの作品を触っていても、会話の作品の古い今がそえられた）
    try {
      const rd = path.join(require('os').tmpdir(), 'mittler'); fs.mkdirSync(rd, { recursive: true });
      const rf = path.join(rd, 'recent.json'), rt = rf + '.' + process.pid + '.part';
      fs.writeFileSync(rt, JSON.stringify({ project_dir: project, state_file: f, timeline_file: timelineFile, saved: st.saved })); ATOMIC.replace(rt, rf);
    } catch (e) { }
  }
  // まだ AI に渡していない ✏️ 書き込み（annotation.json の delivered が false。新しい順に 3 つまで）：state.json の annotations_pending に載せる（2026-11-22）。
  // Claude Code はフック（tools/mittler_state.py）が添えて delivered にする。フックの無い AI は state.json でこれを見つけ、見たら delivered を true にする（AGENTS.md）
  function pendingAnnotations() {
    const d = path.join(stateDir(), 'annotations'), out = [];
    let names = []; try { names = fs.readdirSync(d); } catch (e) { return out; }
    for (const n of names) {
      try {
        const a = JSON.parse(fs.readFileSync(path.join(d, n, 'annotation.json'), 'utf8'));
        if (!a.delivered) out.push({ id: a.id, created: a.created, t: a.t, frame: a.frame, image: path.join(project, a.image), annotation: path.join(d, n, 'annotation.json') });
      } catch (e) { }
    }
    return out.sort((x, y) => String(y.created).localeCompare(String(x.created))).slice(0, 3);
  }
  // 書き込みを保存したら、state.json の annotations_pending をすぐ書き直す（編集画面の状態が変わらなくても AI が見つけられるように）
  function refreshStatePending() {
    try {
      const f = path.join(stateDir(), 'state.json'); const st = JSON.parse(fs.readFileSync(f, 'utf8'));
      const pend = pendingAnnotations(); if (pend.length) st.annotations_pending = pend; else delete st.annotations_pending;
      const tmp = f + '.part'; fs.writeFileSync(tmp, JSON.stringify(st, null, 1)); ATOMIC.replace(tmp, f);
    } catch (e) { }
  }
  // ✏️ 書き込み（editor/annotate.js）：状態フォルダの annotations/<id>/ に after.jpg（書き込んだ画面）・before.jpg・annotation.json。
  // Claude Code へは、次に話しかけたときフック（tools/mittler_state.py）が添える（添えたら annotation.json の delivered を true に）
  function saveAnnotation(o) {
    const d = new Date(), z = n => String(n).padStart(2, '0');
    const id = `ann_${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}`;
    const dir = path.join(stateDir(), 'annotations', id); fs.mkdirSync(dir, { recursive: true });
    const img = (name, url) => {
      const m = /^data:image\/(jpeg|png);base64,(.+)$/.exec(String(url || '')); if (!m) return null;
      fs.writeFileSync(path.join(dir, name), Buffer.from(m[2], 'base64')); return `${STATE_NAME}/annotations/${id}/${name}`;
    };
    const after = img('after.jpg', o.after); if (!after) throw KE('srv.annNoImage');
    const before = img('before.jpg', o.before);
    const meta = { id, created: d.toISOString(), timeline_file: timelineFile, t: o.t, frame: o.frame, width: o.width, height: o.height,
      image: after, image_before: before, bbox: o.bbox, strokes: (o.strokes || []).map(s => ({ tool: s.tool, color: s.color, width: s.width, n: (s.pts || []).length,
        from: (s.pts || [])[0], to: (s.pts || []).slice(-1)[0] })), clips_at_time: o.clips || [], selection: o.selection || null, delivered: false };
    fs.writeFileSync(path.join(dir, 'annotation.json'), JSON.stringify(meta, null, 1));
    return meta;
  }
  function markStateClosed() {  // 編集画面を閉じた（サーバーを止めた）：state.json に open:false
    try { const f = path.join(stateDir(), 'state.json'); const o = JSON.parse(fs.readFileSync(f, 'utf8')); o.open = false; o.closed = new Date().toISOString(); fs.writeFileSync(f, JSON.stringify(o, null, 1)); } catch (e) { }
  }
  // 補助の道具（ジョブ係・TTS・H3 のアダプタ）を動かす python：PC の設定（mittler.tools.python・--tools-python）か既定（PATH の python）
  const toolsPython = () => opts.python || DEF.toolsPython;
  // VOICEVOX のエンジン：PC の設定（mittler.voicevox.url・--voicevox-url）か既定（このPCの 127.0.0.1:50021）。TTS にも渡す（クリップの voicevox.url があればそちらが勝つ）
  const voicevoxUrl = () => String(opts.voicevoxUrl || DEF.voicevoxUrl).replace(/\/+$/, '');
  // 🏆 マスター書き出し（機能追加案03 v2）の設定：PC の設定（VS Code の mittler.master.*・単体の --esrgan など）→ 既定（server/defaults.js の master）。
  // 空（''・null）だけを「設定なし」とみなす（outHeight の 0＝4K のまま納品 は設定として使う）
  function masterCfg() {
    const o = opts.master || {}, d = DEF.master, out = {};
    for (const k of Object.keys(d)) { const v = o[k]; out[k] = v === undefined || v === null || v === '' ? d[k] : v; }
    for (const k of ['scale', 'fps', 'outHeight', 'cacheGb', 'jobs']) out[k] = +out[k];
    return out;
  }
  // アプスケ・補間のキャッシュ（mittler master が作品の work/master/upscale・interp に置く。再マスターで使い回す）：大きさ・空にする
  const masterCacheDirs = () => ['upscale', 'interp'].map(n => path.join(cacheRoot(), 'master', n));
  function masterCache() {
    let bytes = 0, files = 0;
    for (const d of masterCacheDirs()) {
      let names = []; try { names = fs.readdirSync(d); } catch (e) { }
      for (const n of names) if (/\.mkv$/i.test(n)) { try { bytes += fs.statSync(path.join(d, n)).size; files++; } catch (e) { } }
    }
    return { bytes, gb: +(bytes / 1e9).toFixed(2), files };
  }
  function clearMasterCache() {  // キャッシュの *.mkv だけを消す（書き出しの途中は消さない）
    let freed = 0, n = 0;
    for (const d of masterCacheDirs()) {
      let names = []; try { names = fs.readdirSync(d); } catch (e) { }
      for (const nm of names) if (/\.mkv$/i.test(nm)) { const f = path.join(d, nm); try { const sz = fs.statSync(f).size; fs.unlinkSync(f); freed += sz; n++; } catch (e) { } }
    }
    log(`マスターのキャッシュを空にした：${n} 本・${(freed / 1e9).toFixed(2)} GB`);
    return { ok: true, files: n, gb: +(freed / 1e9).toFixed(2) };
  }
  // ---- 🎬 生成のジョブ（tools/jobs.py が流す。生成は常にこのPC）----
  const jobsDir = () => path.join(project, 'work', 'jobs');
  function writeJob(f, j) { const tmp = f + '.part'; fs.writeFileSync(tmp, JSON.stringify(j, null, 1)); ATOMIC.replace(tmp, f); }  // ジョブ係（Python）が読んでいる瞬間でも通るように
  function listJobs() {
    let names = []; try { names = fs.readdirSync(jobsDir()).filter(n => /^job_.*\.json$/.test(n)); } catch (e) { }
    const jobs = names.map(n => { try { return JSON.parse(fs.readFileSync(path.join(jobsDir(), n), 'utf8')); } catch (e) { return null; } }).filter(Boolean)
      .map(j => { const o = Object.assign({}, j); if (o.image) o.image = { out: o.image.out, refs: (o.image.refs || []).length, engine: o.image.engine, model: o.image.model }; if (o.video) o.video = { out: o.video.out, seconds: o.video.seconds, engine: o.video.engine }; return o; });
    let runner = null; try { runner = JSON.parse(fs.readFileSync(path.join(jobsDir(), 'runner.json'), 'utf8')); } catch (e) { }
    return { jobs, runner: runner && Date.now() / 1000 - runner.heartbeat < 15 ? runner : null };
  }
  // ジョブ係が動いていなければ起動する（このサーバーと切り離して動かす：ウィンドウを再読み込みしても生成は止まらない）
  function ensureRunner() {
    try { const r = JSON.parse(fs.readFileSync(path.join(jobsDir(), 'runner.json'), 'utf8')); if (Date.now() / 1000 - r.heartbeat < 15) return; } catch (e) { }
    // Codex の場所・モデル（PC の設定 mittler.codex.path・mittler.codex.model）は環境変数でジョブ係に渡す（tools/gen/codex_image.py が読む。無ければ PATH の codex・gpt-6.1-sol）
    // 新しい名前 MITTLER_* で渡す（読む側は MITTLER_* が先。この PC の環境に古い CC_CODEX があっても、設定のほうが勝つ）
    const env = Object.assign({}, process.env);
    if (opts.codexPath) env.MITTLER_CODEX = opts.codexPath;
    if (opts.codexModel) env.MITTLER_CODEX_MODEL = opts.codexModel;
    const pr = require('child_process').spawn(toolsPython(), ['-X', 'utf8', path.join(ROOT, 'tools', 'jobs.py'), project],
      { detached: true, stdio: 'ignore', windowsHide: true, cwd: project, env });
    pr.on('error', e => log('ジョブ係を起動できない: ' + e.message)); pr.unref();
    log('ジョブ係を起動した');
  }
  // 生成のアダプタ（エンジンの決まりを持つところ）：ジョブの engine から tools/engines.json でアダプタを引き、エンジンに依らない依頼を
  // python tools/<adapter>.py build の標準入力に渡して、ジョブの中身（動画は video・sent、絵は image・sent）と warnings を受け取る。
  // H3 の決まりは tools/h3_jobs.py（docs/H3受け渡し契約.md）、Codex の決まりは tools/codex_jobs.py
  function adapterBuild(kind, engine, request) {
    const ent = ENGINES.engines[engine];
    if (!ent || ent.kind !== kind) return Promise.resolve({ ok: false, error: $t('srv.unknownEngine', { engine, what: $t(kind === 'video' ? 'srv.what.video' : 'srv.what.image') }) });
    const what = $t(kind === 'video' ? 'srv.what.video' : 'srv.what.gen');
    return new Promise(ok => {
      const p = execFile(toolsPython(), ['-X', 'utf8', path.join(ROOT, 'tools', ent.adapter + '.py'), 'build'],
        { timeout: 60000, windowsHide: true, maxBuffer: 16 << 20 }, (e, stdout, stderr) => {
          try { ok(JSON.parse(String(stdout).trim().split(/\r?\n/).pop())); } catch (err) { ok({ ok: false, error: $t('srv.buildFail', { what, err: String(stderr || (e && e.message) || stdout).slice(-800) }) }); }
        });
      p.stdin.end(JSON.stringify(request));
    });
  }
  // 動画化のジョブ：開始・終了の絵＋動画のプロンプト（参照を開く）→ アダプタ（H3 なら tools/h3_jobs.py build）でエンジンの決まりを当てる → ジョブ係がエンジンのキューに置く
  // ここに残すのはエンジンに依らないこと：参照を開く・声の参照の場所と長さ・出力の名前（_t<n>）・シード・ジョブの id と状態（applied は /api/jobs/<id>/applied）
  async function createVideoJob(o) {
    const c = o.clip, v = c.video || {}, engine = v.engine || ENGINES.default.video;
    const ctx = planCtx(c.id, 'video'); ctx.clip = c;
    const r = require('./plan_refs').resolve(v.prompt || '', ctx);
    if (r.errors.length) throw KE('srv.refErrors', { list: r.errors.join(' / ') });
    const start = (c.start_frame || {}).src, end = (c.end_frame || {}).src, abs = x => (x ? path.join(ctx.root, x) : null);
    // 声の参照：audio(here)＝このクリップの時間に鳴っている TTS（ミュート・非表示でないトラック）、ほかは音声ファイルの区間
    const ttsHere = () => (ctx.tl.tracks || []).filter(t => t.kind === 'tts' && !t.muted && !t.hidden);
    const audio = r.audio.map(a => (a.here
      ? { here: true, t0: c.start, t1: c.start + c.dur, seconds: +c.dur.toFixed(3),
          empty: !ttsHere().some(t => (t.clips || []).some(x => !x.disabled && x.start < c.start + c.dur && x.start + x.dur > c.start)) }
      : { src: a.src, src_abs: path.join(ctx.root, a.src), in: a.in, out: a.out, seconds: +(a.out - a.in).toFixed(3) }));
    let n = (v.takes || []).length + 1, out;
    do { out = `assets/videos/gen/${c.id}_t${n}.mp4`; n++; } while (fs.existsSync(path.join(ctx.root, out)));
    // シード：クリップの video.seed。決めていなければ、作品とクリップの id から毎回同じ値（どこから頼んでも、下書きと本番が同じシードになる。🎲 で変えたら video.seed）
    const fromClip = v.seed != null && isFinite(+v.seed);
    const seed = fromClip ? Math.trunc(+v.seed) : 1 + (parseInt(crypto.createHash('sha1').update(path.basename(project) + '|' + c.id).digest('hex').slice(0, 8), 16) % 2147483646);
    const tl = ctx.tl;
    const built = await adapterBuild('video', engine, { engine, body: r.body, imports: r.imports.map(im => (im.image ? Object.assign({}, im, { image_abs: abs(im.image) }) : im)),
      start, end, start_abs: abs(start), end_abs: abs(end), audio, dur: c.dur, width: tl.width, height: tl.height,
      seed, seed_from_clip: fromClip, h3: v.h3, draft: !!o.draft, steps: o.steps, out, root: ctx.root, project_dir: project, clip: c.id, dry: !!o.dry });
    if (!built.ok) throw new Error(built.error);
    const warnings = [...r.warnings, ...built.warnings];
    // 長さ：H3 は長いほど生成の時間が跳ね上がる。基本は 2〜6 秒に区切る（AI 用ガイド 7.52）。止めはしない
    if (c.dur > H3_MAX_SEC + 1e-6) warnings.push($t('pl.longVideo', { s: c.dur.toFixed(2), max: H3_MAX_SEC }));
    if (built.video.audio && built.video.audio.here) {  // 混ぜる元のタイムライン（素材の根は絶対パス。work/jobs に置くので）→ ジョブ係が mix.py で声の wav にする
      const vtl = Object.assign({}, ctx.tl, { root: ctx.root });
      vtl.tracks = ttsHere();
      fs.mkdirSync(jobsDir(), { recursive: true });
      const vf = path.join(jobsDir(), `voice_${c.id}_${Date.now()}.cut.json`);
      fs.writeFileSync(vf, JSON.stringify(vtl));
      built.video.audio.timeline = vf;
    }
    const id = 'job_' + new Date().toISOString().replace(/[-:T.Z]/g, '').slice(0, 14) + '_' + crypto.randomBytes(3).toString('hex');
    const job = { id, kind: 'video', clip: c.id, which: 'video', state: 'queued', created: new Date().toISOString(), video: built.video, sent: built.sent, warnings };
    fs.mkdirSync(jobsDir(), { recursive: true });
    writeJob(path.join(jobsDir(), id + '.json'), job);
    ensureRunner();
    return { ok: true, id, out, warnings };
  }
  // 絵のエンジン：絵の欄の engine（この絵だけ。API の --engine もここ）→ 作品の settings.image_engine（作品の既定）→ PC の設定 mittler.image.engine（opts.imageEngine）→ tools/engines.json の既定。
  // OpenAI（GPT Image）は 2026-11-15〜、Nano Banana（Gemini）は 2026-11-19〜。作品の既定は、作品ごとに最初にユーザーに聞いて決めるもの。
  // 作品の既定のほかも断らない：生成と直しでエンジンを使い分けるので、どのエンジンも呼べる
  const projectImageEngine = tl => { const e = ((tl && tl.settings) || {}).image_engine; return e && ENGINES.engines[e] && ENGINES.engines[e].kind === 'image' ? e : ''; };
  const imageEngine = (fr, tl) => (fr && ENGINES.engines[fr.engine] ? fr.engine : '') || projectImageEngine(tl) || (ENGINES.engines[opts.imageEngine] ? opts.imageEngine : '') || ENGINES.default.image;
  // 絵のジョブ：参照を開いた全文（server/plan_refs.js）→ アダプタ（Codex なら tools/codex_jobs.py build）でエンジンの決まりを当てる → work/jobs/job_*.json（動画化は createVideoJob）
  // ここに残すのはエンジンに依らないこと：参照を開く・本文が空なら止める・同じ絵を生成中なら止める・出力の名前（_t<n>）・ジョブの id と状態
  const H3_MAX_SEC = 6;  // 動画化の長さの目安の上限（秒。これをこえると注意。AI 用ガイド 7.52）
  async function createJob(o) {
    const which = o.which, c = o.clip;
    if (o.kind === 'video') return createVideoJob(o);
    if (o.kind !== 'image' || !['start_frame', 'end_frame'].includes(which)) throw KE('srv.jobKind');
    const ctx = planCtx(c.id, which); ctx.clip = c;
    const fr = c[which] || {}, engine = imageEngine(fr, ctx.tl);
    const r = require('./plan_refs').resolve(fr.prompt || '', ctx);
    if (r.errors.length) throw KE('srv.refErrors', { list: r.errors.join(' / ') });
    if (!r.body) throw KE('srv.emptyPrompt');
    const tl = ctx.tl;
    const built = await adapterBuild('image', engine, { engine, prompt: r.prompt, body: r.body, refs: r.refs, width: tl.width, height: tl.height,
      root: ctx.root, project_dir: project, clip: c.id, which,
      model: fr.model || '', quality: fr.quality || '',
      // PC の設定の既定（エンジンごと）：OpenAI は mittler.openai.imageModel・imageQuality、Nano Banana は mittler.gemini.imageModel・imageSize（2026-11-19）
      default_model: (engine === 'nanobanana' ? opts.geminiImageModel : opts.openaiImageModel) || '',
      default_quality: (engine === 'nanobanana' ? opts.geminiImageSize : opts.openaiImageQuality) || '' });
    if (!built.ok) throw new Error(built.error);
    fs.mkdirSync(jobsDir(), { recursive: true });
    const tag = which === 'start_frame' ? 'start' : 'end';
    const busy = listJobs().jobs.filter(j => j.clip === c.id && j.which === which && ['queued', 'running'].includes(j.state));
    if (busy.length) throw KE('srv.alreadyGen');
    // 出力の名前：まだ無い _t<n>（アダプタが出力の横に書くファイル sidecars とも重ならないように）
    const side = built.sidecars || [];
    let n = (fr.takes || []).length + 1, out;
    do { out = `assets/frames/${c.id}_${tag}_t${n}.png`; n++; } while (fs.existsSync(path.join(ctx.root, out)) || side.some(s => fs.existsSync(path.join(ctx.root, out + s))));
    built.image.out = out;
    if (engine !== ENGINES.default.image) built.image.engine = engine;  // 既定でないエンジンだけジョブに書く（ジョブ係が engines.json で引く）
    const id = 'job_' + new Date().toISOString().replace(/[-:T.Z]/g, '').slice(0, 14) + '_' + crypto.randomBytes(3).toString('hex');
    const job = { id, kind: 'image', clip: c.id, which, state: 'queued', created: new Date().toISOString(), image: built.image, sent: built.sent };
    writeJob(path.join(jobsDir(), id + '.json'), job);
    ensureRunner();
    return { ok: true, id, out, warnings: [...r.warnings, ...(built.warnings || [])] };
  }
  function runTts(request) {
    return new Promise(ok => {
      const p = track(require('child_process').execFile(toolsPython(), ['-X', 'utf8', path.join(ROOT, 'tools', 'tts_gen.py')],
        { timeout: 300000, windowsHide: true, maxBuffer: 1 << 20 }, (e, stdout) => {
          try { ok(JSON.parse(String(stdout).trim().split(/\r?\n/).pop())); } catch (err) { ok({ ok: false, error: String((e && e.message) || stdout).slice(-800) }); }
        }));
      p.stdin.end(JSON.stringify(request));
    });
  }
  // 時間の付け替えの点 {points, smooth} → クリップの頭から t 秒の動画の秒：editor/calc.js の warpMap（編集画面と同じもの。pyengine/mittler/warp.py と同じ式は tools/smoke_same.py）
  const warpAt = require('../editor/calc').warpMap;
  // 同じものを作る頼みが同時に来たら、作っている 1 つを待つ（鍵＝できあがるファイル）。前は、同じ素材の波形・サムネ・動画の音の頼みが重なると、
  // 同じ名前の一時ファイルを 2 つの ffmpeg が書いて、片方が失敗した（波形を同時に 4 つ頼むと 2 つが失敗。2026-11-12）
  const making = new Map();
  function once(key, fn) {
    let p = making.get(key);
    if (!p) { p = Promise.resolve().then(fn).finally(() => making.delete(key)); making.set(key, p); }
    return p;
  }
  // 映像クリップの最初に画面に出るコマ（Python エンジンと同じ：時間の付け替え表 warp か速さ、着地合わせの頭の切り落とし）の絵
  async function thumbFor(id) {
    let tl = readTimeline(), clip = (tl.tracks || []).flatMap(t => t.clips || []).find(c => c.id === id);
    // 置いたばかりのクリップ：編集画面の保存（約0.35秒あと）がまだ届いていない。少し待って読み直す
    for (let i = 0; !clip && i < 8; i++) { await new Promise(r => setTimeout(r, 500)); tl = readTimeline(); clip = (tl.tracks || []).flatMap(t => t.clips || []).find(c => c.id === id); }
    const fps = tl.fps || 30;
    if (!clip) throw new Error('no clip');
    const base = path.resolve(project, tl.root || '.');
    const src = Array.isArray(clip.src) ? clip.src[0] : clip.src; if (!src) throw new Error('no src');
    const file = inside(base, src); if (!file || !fs.existsSync(file)) throw new Error('no file');
    let t = clip.in || 0;
    if (clip.warp && typeof clip.warp === 'object' && Array.isArray(clip.warp.points)) t = warpAt(clip.warp, 0);  // 編集画面で作った点（動画の秒そのもの）
    else if (clip.warp) {  // 時間の付け替え表：クリップの頭（0 秒）の動画の秒（np.interp と同じく、表の外は端の値）
      try {
        const tab = JSON.parse(fs.readFileSync(inside(base, clip.warp), 'utf8')).table;
        const i = tab.findIndex(r => r[0] >= 0);
        t = i <= 0 ? tab[Math.max(i, 0)][1] : tab[i - 1][1] + (tab[i][1] - tab[i - 1][1]) * (0 - tab[i - 1][0]) / (tab[i][0] - tab[i - 1][0]);
        if (i < 0) t = tab[tab.length - 1][1];
      } catch (e) { }
    }
    if (clip.land && (!Array.isArray(clip.src) || clip.src.length === 1) && !clip.warp && (clip.speed || 1) === 1) {
      const over = (await probeDur(file)) - clip.dur; if (over > 0.5 / fps) t += over;
    }
    const st = fs.statSync(file);
    const key = crypto.createHash('sha1').update(`${file}|${st.size}|${st.mtimeMs}|${t.toFixed(4)}|${THUMB_H}`).digest('hex').slice(0, 16);
    const out = path.join(stateDir(), 'thumbs', key + '.jpg');
    if (!fs.existsSync(out)) await once(out, async () => {
      if (fs.existsSync(out)) return;
      fs.mkdirSync(path.dirname(out), { recursive: true });
      const tmp = out + '.tmp.jpg';
      await thumbJob(() => run('ffmpeg', ['-v', 'error', '-y', '-ss', t.toFixed(4), '-i', file, '-frames:v', '1', '-vf', `scale=-2:${THUMB_H}`, '-q:v', '4', tmp]));
      ATOMIC.replace(tmp, out);
    });
    return out;
  }
  const tl0 = readTimeline();
  if (!NAMES.formatOk(tl0.format)) throw KE('srv.badFormat', { f: tl0.format || $t('srv.none') });
  const log = m => console.error('[mittler]', m);
  // ssh のモードの設定が残っている作品（render.host・render.remote）：使わずに、このPCで描く。止めずに、ログに1度だけ知らせる
  const r0 = tl0.render || {};
  if ((r0.host || r0.remote) && !warnedSsh.has(timelineFile)) {
    warnedSsh.add(timelineFile);
    log('タイムラインの render.host・render.remote は使わない（このPCで描く）。ssh のモードは 2026-10-30 に廃止した：ほかの PC で描くときは、VS Code の Remote-SSH でその PC に接続して作品を開く');
  }
  // 描くのはこのPC。python は PC ごとの設定（VS Code の mittler.render.*、単体なら --render-python・--ffmpeg-dir）か、タイムラインの render.python（pyrender.js）
  // タイムラインの render.python は確かめてから使う（pyrender.js の checkPython）。PC の設定と違えばログで知らせる
  const renderer = require('./pyrender').start({
    project, timelineName: path.basename(timelineFile), log, local: opts.local,
    render: { python: r0.python || '' }, defaultPython: DEF.renderPython, defaultFfmpegDirs: DEF.ffmpegDirs,
  });
  // 作品の状態フォルダに、この PC 用のファイル（env.json・AI 用ガイドの写し guide.md・中継 hook.py／api.py／engine.py）を書く（server/project_env.js。2026-11-13 パッケージ化）。
  // 作品のファイルに Mittler の絶対パスを書かないため。開いたときと、描く python が決まったとき（env.json の render_python）。書けなくても作品は開く
  const writeProjectEnv = () => {
    try {
      const l = renderer.local || {};
      const r = require('./project_env').write(project, { stateName: STATE_NAME, renderPython: l.python, ffmpegDir: l.ffmpegDir, blender: blenderPath, language: lang, by: 'server' });
      if (r.written.length) log(`作品の ${STATE_NAME}/ に書いた：${r.written.join('・')}`);
    } catch (e) { log(`作品の ${STATE_NAME}/ に env.json などを書けない：${e.message}`); }
  };
  writeProjectEnv();
  renderer.ready.then(ok => { if (ok) writeProjectEnv(); });
  // ---- 🎵 Suno の曲（機能追加案02 v2）：受け取り口だけ（server/music.js）。Suno を呼ぶのは Claude Code（AI）で、このサーバーは呼ばない ----
  // 外の URL をユーザーの既定のブラウザで開く（suno.com の曲のページだけ。music.js が形を確かめてから呼ぶ）。VS Code の中なら vscode.env.openExternal（extension.js）、
  // 単体ならこの PC の既定のブラウザ。テストは環境変数 MITTLER_OPEN_LOG（開かずに、そのファイルに URL を1行書く。古い名前 CC_OPEN_LOG も）
  function openExternal(url) {
    const openLog = NAMES.env('OPEN_LOG');
    if (openLog) { fs.appendFileSync(openLog, url + '\n'); return 'log'; }
    if (opts.openExternal) { opts.openExternal(url); return 'vscode'; }
    const [exe, args] = process.platform === 'win32' ? ['rundll32.exe', ['url.dll,FileProtocolHandler', url]] : process.platform === 'darwin' ? ['open', [url]] : ['xdg-open', [url]];
    const pr = require('child_process').spawn(exe, args, { detached: true, stdio: 'ignore', windowsHide: true });
    pr.on('error', e => log('ブラウザを開けない: ' + e.message)); pr.unref();
    return 'browser';
  }
  const music = require('./music').create({ project, readTimeline, inside, hiddenIn, probeDur, notify: k => notify(k), log: m => log(m), stateDir, openExternal, lang: () => lang });
  // ---- 書き出し：このPCで `mittler video`（区間に分けて並列）→ <プロジェクト>/output/<名前>.mp4
  //      → 頼まれたら再生用の WebM（make_proxy.py --no-timeline。preview.proxy は編集画面が入れる）
  const EXPORT_BUSY = ['preparing', 'rendering', 'muxing', 'proxy', 'cancelling'];
  const exportJob = { state: 'idle' };
  function runLines(exe, args, spawnOpts, onLine) {  // 1行ずつ onLine に渡す。終わったら { code, out, err }
    return new Promise((ok, ng) => {
      const pr = require('child_process').spawn(exe, args, Object.assign({ windowsHide: true }, spawnOpts));
      let err = '', buf = '', out = '';
      pr.stdout.on('data', d => {
        buf += d; let i;
        while ((i = buf.indexOf('\n')) >= 0) { const ln = buf.slice(0, i).trim(); buf = buf.slice(i + 1); out = (out + ln + '\n').slice(-4000); if (ln && onLine) onLine(ln); }
      });
      pr.stderr.on('data', d => { err = (err + d).slice(-3000); });
      pr.on('exit', code => ok({ code, out: out + buf, err }));
      pr.on('error', ng);
      if (onLine) exportJob.proc = pr;
    });
  }
  // ---- 裏で先に描いてためる（2026-11-16。pyengine/mittler/bake.py・fcache.py）----
  // 編集画面が、止まって手が離れたときに POST /api/bake {from}。動いていなければ、再生位置から先のコマを優先度「通常以下」の区間のプロセスで描いて、
  // 作品の work/cache/frames/ にためる。止める：タイムライン・エフェクト・素材が変わった（notify）・書き出しを始めた・サーバーを閉じた・POST /api/bake/stop。
  // 並列の数は設定 mittler.bake.jobs（空＝自動：bake.default_jobs、0＝裏で描かない）
  const bake = { state: 'idle', done: 0, total: 0, from: 0, proc: null, stopFile: path.join(cacheRoot(), 'cache', 'bake.stop') };
  const bakeJobs = () => { const v = opts.bakeJobs; return v === '' || v == null || !isFinite(+v) ? null : Math.max(0, Math.round(+v)); };
  const bakeState = () => ({ state: bake.state, done: bake.done, total: bake.total, from: bake.from, jobs: bakeJobs(), off: bakeJobs() === 0, paused: !!bake.paused, workersPaused: !!bake.workersPaused });
  // シーク・操作しているあいだは一時停止（<止める印>.pause を置くと bake.py が区間のプロセスを子孫ごと止める。描きかけのコマから続く）。
  // プレビューの絵の頼み（/api/frame）と編集画面の操作（POST /api/bake/pause）のたびに呼び、PAUSE_MS 静かになったら続ける。
  // 裏で描いているとシークの描画がとても遅くなるので、シークした瞬間にためるのを止める
  const PAUSE_MS = 2500;
  bake.pauseFile = bake.stopFile + '.pause';
  function bakePause() {
    if (!bake.proc) return false;
    if (!bake.paused) { try { fs.writeFileSync(bake.pauseFile, 'pause'); } catch (e) { } bake.paused = true; }
    clearTimeout(bake.resumeTimer);
    bake.resumeTimer = setTimeout(bakeResume, PAUSE_MS);
    return true;
  }
  function bakeResume() {
    clearTimeout(bake.resumeTimer);
    try { fs.unlinkSync(bake.pauseFile); } catch (e) { }
    bake.paused = false;
  }
  async function bakeStart(from) {
    if (bakeJobs() === 0) return Object.assign({ ok: false, why: 'off' }, bakeState());
    if (bake.proc) return Object.assign({ ok: true, already: true }, bakeState());
    if (EXPORT_BUSY.includes(exportJob.state)) return Object.assign({ ok: false, why: 'export' }, bakeState());
    const local = await renderer.ensure();
    if (bake.proc || EXPORT_BUSY.includes(exportJob.state)) return Object.assign({ ok: false, why: 'busy' }, bakeState());
    fs.mkdirSync(path.dirname(bake.stopFile), { recursive: true });
    try { fs.unlinkSync(bake.stopFile); } catch (e) { }
    bakeResume();  // 前の一時停止の印が残っていたら外す
    const j = bakeJobs(), t = Math.max(0, +from || 0);
    Object.assign(bake, { state: 'running', done: 0, total: 0, from: t, started: Date.now() });
    const pr = track(require('child_process').spawn(local.python, ['-X', 'utf8', '-B', '-m', 'mittler', 'bake', timelineFile, '--from', String(t), '--stop', bake.stopFile, ...(j ? ['--jobs', String(j)] : [])],
      { cwd: path.join(ROOT, 'pyengine'), windowsHide: true, env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1' }) }));
    bake.proc = pr;
    let buf = '';
    pr.stdout.on('data', d => {
      buf += d; let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const ln = buf.slice(0, i).trim(); buf = buf.slice(i + 1); const m = /^BAKE (\d+) (\d+)/.exec(ln);
        if (m) { bake.done = +m[1]; bake.total = +m[2]; }
        else if (ln === 'BAKE_PAUSED' || ln === 'BAKE_RESUMED') bake.workersPaused = ln === 'BAKE_PAUSED';  // bake.py が区間のプロセスを止めた・続けた
      }
    });
    pr.stderr.on('data', () => { });
    pr.on('exit', code => { if (bake.proc === pr) { bake.proc = null; bakeResume(); bake.state = code === 0 ? 'done' : 'stopped'; log(`裏で描く: 終わり（${bake.done} / ${bake.total} コマ）`); } });
    pr.on('error', () => { if (bake.proc === pr) { bake.proc = null; bake.state = 'stopped'; } });
    log(`裏で描く: ${t.toFixed(2)} 秒から（並列 ${j || '自動'}）`);
    return Object.assign({ ok: true }, bakeState());
  }
  function bakeStop(why) {
    const pr = bake.proc; if (!pr) return false;
    try { fs.writeFileSync(bake.stopFile, String(why || 'stop')); } catch (e) { }
    bakeResume();  // 一時停止のままだと止める印を見られない（bake.py も止める前に続けさせる）
    bake.proc = null; bake.state = 'stopped';
    setTimeout(() => { if (pr.exitCode === null) killTree(pr); }, 20000);  // 区間のプロセスはコマの区切りで止まる。止まらなければ止める
    log(`裏で描く: 止めた（${why || ''}）`);
    return true;
  }
  const sha256 = f => new Promise((ok, ng) => { const h = crypto.createHash('sha256'); fs.createReadStream(f).on('data', d => h.update(d)).on('end', () => ok(h.digest('hex'))).on('error', ng); });
  // ---- 🔬 クリップの解析（編集画面の右クリック・tools/mittler_api.py の analyze）----
  // このPCの解析用の python（PC の設定 mittler.analysis.python → タイムラインの settings.analysis_python → 既定 server/defaults.js）で pyengine/mittler/analyze.py を動かし、
  // 作品の <素材の根>/assets/analysis/<クリップ>_<種類>_<日時>/ に書く。タイムラインに入れるのは編集画面（analyze.js）。1つずつ順に（GPU は1枚）。
  // 解析の種類の一覧は pyengine/mittler/analyze_kinds.json の1か所（クリップの種類ごと・メニューの名前。編集画面には GET /api/analyze の kinds・labels で渡す）
  const AK = JSON.parse(fs.readFileSync(path.join(ROOT, 'pyengine', 'mittler', 'analyze_kinds.json'), 'utf8'));
  const ANALYZE_KINDS = AK.by_type;
  const anJobs = []; let anBusy = false, anWarned = false;
  const anFile = () => path.join(stateDir(), 'analyze.json');
  function anSave() { try { fs.mkdirSync(stateDir(), { recursive: true }); fs.writeFileSync(anFile(), JSON.stringify(anJobs.slice(-60), null, 1)); } catch (e) { } }
  try {  // 前のサーバーのとき頼んだもの（終わって、まだタイムラインに入れていないものを編集画面が入れる）
    anJobs.push(...JSON.parse(fs.readFileSync(anFile(), 'utf8')));
    for (const j of anJobs) if (j.state === 'queued' || j.state === 'running') { j.state = 'failed'; j.error = $t('srv.anStopped'); }
  } catch (e) { }
  const spawnCollect = (exe, args, o) => new Promise(ok => {
    const pr = track(require('child_process').spawn(exe, args, Object.assign({ windowsHide: true }, o || {}))); let out = '', err = '';
    pr.stdout.on('data', d => { out = (out + d).slice(-8000); }); pr.stderr.on('data', d => { err = (err + d).slice(-8000); });
    pr.on('exit', code => ok({ code, out, err })); pr.on('error', e => ok({ code: -1, out, err: String(e.message || e) }));
  });
  function anInput(c, tl) {  // 解析する素材と区間（素材の秒）
    const root = path.resolve(project, tl.root || '.');
    let src = null, t0 = null, t1 = null;
    if (c.type === 'tts') { const k = (c.takes || []).find(x => x.id === c.activeTake); src = k && k.src; t0 = c.in || 0; t1 = t0 + c.dur; }
    else if (c.type === 'audio') { src = c.src; t0 = c.in || 0; t1 = t0 + c.dur; }
    else if (c.type === 'video') {
      src = Array.isArray(c.src) ? (c.src.length === 1 ? c.src[0] : null) : c.src;
      if (c.warp && typeof c.warp === 'object' && Array.isArray(c.warp.points)) { t0 = warpAt(c.warp, 0); t1 = warpAt(c.warp, c.dur); }
      else if (typeof c.warp !== 'string') { t0 = c.in || 0; t1 = t0 + c.dur * (c.speed || 1); }
    } else if (c.type === 'image') src = c.src;
    if (!src) throw KE('srv.anNoSrc');
    const file = inside(root, src); if (!file || !fs.existsSync(file)) throw KE('srv.anNotFound', { src });
    return { rel: src, t0: t0 != null ? +Math.max(0, t0).toFixed(4) : null, t1: t1 != null ? +Math.max(t1, (t0 || 0) + 0.05).toFixed(4) : null };
  }
  function createAnalyze(o) {
    const c = o.clip; if (!c || !c.id) throw KE('srv.anNoClip');
    const kinds = ANALYZE_KINDS[c.type] || [];
    if (!kinds.includes(o.kind)) throw KE('srv.anKind', { type: c.type, kind: o.kind, list: { toString: () => kinds.join($t('sep.list')) || $t('srv.nashi') } });
    const inp = anInput(c, readTimeline());
    const stamp = new Date().toISOString().replace(/[-:T.Z]/g, '').slice(0, 14);
    const id = 'an_' + stamp + '_' + crypto.randomBytes(2).toString('hex');
    const job = { id, kind: o.kind, clip: c.id, clipType: c.type, clipStart: c.start, clipDur: c.dur, label: c.label || '', state: 'queued', created: new Date().toISOString(),
      input: inp.rel, from: inp.t0, to: inp.t1, out: `assets/analysis/${String(c.id).replace(/[^A-Za-z0-9_-]/g, '_')}_${o.kind}_${stamp}`, by: o.by || 'editor' };
    anJobs.push(job); anSave(); notify('analyze'); pumpAnalyze();
    return { ok: true, id, out: job.out };
  }
  async function pumpAnalyze() {
    if (anBusy) return; const j = anJobs.find(x => x.state === 'queued'); if (!j) return;
    anBusy = true; j.state = 'running'; j.started = new Date().toISOString(); anSave(); notify('analyze');
    log(`解析: ${j.kind} ${j.clip}（${j.input}）`);
    try { await runAnalyze(j); } catch (e) { j.state = 'failed'; j.error = E(e).slice(-1500); log('解析: 失敗 ' + String(e.message || e).slice(-1500)); }
    j.finished = new Date().toISOString(); anSave(); notify('analyze'); anBusy = false; pumpAnalyze();
  }
  async function runAnalyze(j) {
    const tl = readTimeline(), root = path.resolve(project, tl.root || '.'), outLocal = path.join(root, ...j.out.split('/'));
    // 解析の python：PC の設定（mittler.analysis.python・--analysis-python）→ タイムラインの settings.analysis_python → 既定（server/defaults.js）。
    // タイムラインの値は確かめてから使う（pyrender.js の checkPython。通らなければ解析しない）。PC の設定と違えば、ログに1度知らせる
    const fromTl = tl.settings && tl.settings.analysis_python;
    let avpy;
    if (opts.analysisPython) {
      avpy = opts.analysisPython;
      if (fromTl && fromTl !== avpy && !anWarned) { anWarned = true; log(`タイムラインの settings.analysis_python（${fromTl}）は使わない：この PC の設定の python（${avpy}）で解析する`); }
    } else if (fromTl) {
      const why = require('./pyrender').checkPython(fromTl);
      if (why) throw KE('srv.anTlPy', { why });
      avpy = fromTl;
      if (!anWarned) { anWarned = true; log(`解析の python：タイムラインの settings.analysis_python（${fromTl}）`); }
    } else avpy = DEF.analysisPython;
    const range = [...(j.from != null ? ['--from', String(j.from)] : []), ...(j.to != null ? ['--to', String(j.to)] : [])];
    const local = await renderer.ensure();  // ffmpeg のフォルダは描くときと同じ
    if (!fs.existsSync(avpy)) throw KE('srv.anNoPy', { py: avpy });
    fs.mkdirSync(outLocal, { recursive: true });
    const env = Object.assign({}, process.env, { PYTHONUNBUFFERED: '1' }); if (local.ffmpegDir) env.PATH = local.ffmpegDir + path.delimiter + env.PATH;
    if (opts.analysisModels) env.AV_AI_MODELS = opts.analysisModels;  // 解析のモデルの置き場（PC の設定 mittler.analysis.modelsDir。無ければ環境変数 AV_AI_MODELS → analyze.py の既定）
    const r = await spawnCollect(avpy, ['-X', 'utf8', '-B', '-m', 'mittler.analyze', j.kind, path.join(root, ...j.input.split('/')), outLocal, ...range], { cwd: path.join(ROOT, 'pyengine'), env });
    let res = null; try { res = JSON.parse(fs.readFileSync(path.join(outLocal, 'result.json'), 'utf8')); } catch (e) { }
    if (!res) throw KE('srv.anNoResult', { code: r.code, err: (r.err || r.out).slice(-800) });
    if (!res.ok) { if (res.error) throw new Error(res.error); throw KE('srv.anFail'); }  // res.error はエンジン（analyze.py）が今の言葉で書く（環境変数 MITTLER_LANG）
    j.state = 'done';
    j.result = { summary: res.summary, data: res.data, sec: res.sec, where: WHERE, files: Object.fromEntries(Object.entries(res.files || {}).map(([k, f]) => [k, `${j.out}/${f}`])) };
    log(`解析: できた ${j.kind} ${j.clip} → ${j.out}（${res.summary}・${res.sec}秒）`); notify('asset');
  }
  async function runExport(o) {
    if (o.master) return runMaster(o);
    const tl = readTimeline(), fps = tl.fps || 30;
    const t0 = Math.max(0, +o.from || 0), t1 = Math.min(tl.duration, o.to != null && o.to !== '' ? +o.to : tl.duration);
    if (!(t1 > t0)) throw KE('srv.badRange');
    const name = String(o.name || 'export').replace(/[\\/:*?"<>|]/g, '_').replace(/\.mp4$/i, '').trim() + '.mp4';
    const jobs = Math.max(1, Math.min(32, Math.round(+o.jobs || 16)));
    const scale = [0.5, 0.25].includes(+o.scale) ? +o.scale : 1;  // ドラフト：大きさ（1/2・1/4）。本番は 1
    const step = [2, 3, 4].includes(+o.step) ? +o.step : 1;        // ドラフト：コマを間引く（2＝2コマに1コマ）。本番は 1
    const draft = scale < 1 || step > 1;
    const dargs = (draft ? ['--draft', '--step', String(step), '--scale', String(scale)] : []).concat(o.nocache ? ['--no-cache'] : []);  // nocache：ためた絵を使わずに全部描く（fcache）
    for (const k of Object.keys(exportJob)) delete exportJob[k];
    bakeStop('export');  // 書き出しの CPU を取らない
    Object.assign(exportJob, { state: 'preparing', name, from: t0, to: t1, jobs, scale, step, draft, done: 0, total: Math.ceil(Math.round((t1 - t0) * fps) / step), sec: 0, started: Date.now(), wantProxy: !!o.proxy, cached: 0 });
    log(`書き出し: ${name}（${+t0.toFixed(3)}〜${+t1.toFixed(3)}秒・${jobs}並列${draft ? `・ドラフト ${+(fps / step).toFixed(2)}fps${scale < 1 ? `・大きさ 1/${Math.round(1 / scale)}` : ''}` : ''}）`);
    const local = await renderer.ensure();  // 描く python（プレビューと同じ）
    const rOut = path.join(project, 'output', name);
    Object.assign(exportJob, { rOut, where: WHERE });
    if (exportJob.state === 'cancelling') { exportJob.state = 'cancelled'; log('書き出し: 止めた'); return; }
    exportJob.state = 'rendering';
    const onLine = ln => {
      const m = /^PROGRESS (\d+) (\d+) (\d+)/.exec(ln);
      let ph;
      if (m) { exportJob.done = +m[1]; exportJob.total = +m[2]; exportJob.sec = +m[3]; }
      // Blender の 3D：区間に分ける前に、範囲のコマを Blender でまとめて描く段（PHASE blender できた数 全部 → PHASE render）
      else if ((ph = /^PHASE (\w+)(?: (\d+) (\d+))?/.exec(ln))) { exportJob.phase = ph[1] === 'render' ? '' : ph[1]; exportJob.phaseDone = +(ph[2] || 0); exportJob.phaseTotal = +(ph[3] || 0); }
      else if (ln === 'MUXING') { if (exportJob.state === 'rendering') exportJob.state = 'muxing'; }
      else if ((ph = /^CACHED (\d+) (\d+)/.exec(ln))) { exportJob.cached = +ph[1]; log(`書き出し: ためた絵を使ったコマ ${ph[1]} / ${ph[2]}`); }  // 差分書き出し（fcache）
      else if (ln === 'CANCELLED') exportJob.cancelled = true;
      else if (/^(mix|wrote) /.test(ln)) log('書き出し: ' + ln.slice(0, 300));
      else if (ln.startsWith('LOUDNORM_WARN ')) { exportJob.warning = ln.slice(14); log('書き出し: 注意 ' + exportJob.warning); }
    };
    fs.mkdirSync(path.dirname(rOut), { recursive: true });
    const r = await runLines(local.python, ['-X', 'utf8', '-B', '-m', 'mittler', 'video', timelineFile, rOut, '--jobs', String(jobs), '--from', String(t0), '--to', String(t1), ...dargs],
      { cwd: path.join(ROOT, 'pyengine'), env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1' }) }, onLine);
    exportJob.proc = null;
    if (!cancelMissed(r) && (exportJob.cancelled || r.code === 3 || exportJob.state === 'cancelling')) { exportJob.state = 'cancelled'; log('書き出し: 止めた'); return; }
    if (r.code) throw KE('srv.exportFail', { where: I18N.L('ex.thisPC'), code: r.code, err: (r.err || r.out).slice(-1200) });
    const outFile = rOut;
    const sha = await sha256(outFile);
    exportJob.result = { path: path.relative(project, outFile).split(path.sep).join('/'), bytes: fs.statSync(outFile).size, sha256: sha, dur: await probeDur(outFile).catch(() => 0), where: WHERE,
      scale, step, draft, fps: +(fps / step).toFixed(3),
      size: scale < 1 ? `${2 * Math.trunc((tl.width || 1920) * scale / 2)}×${2 * Math.trunc((tl.height || 1080) * scale / 2)}` : `${tl.width || 1920}×${tl.height || 1080}` };
    if (o.proxy) {
      exportJob.state = 'proxy';
      const pr = await new Promise(ok => { exportJob.proxyProc = track(require('child_process').execFile(local.python, ['-X', 'utf8', path.join(ROOT, 'tools', 'make_proxy.py'), timelineFile, outFile, '--no-timeline'],
        { timeout: 1800000, windowsHide: true }, (e, so) => { try { ok(JSON.parse(String(so).trim().split(/\r?\n/).pop())); } catch (err) { ok({ ok: false, error: String((e && e.message) || so).slice(-600) }); } })); });
      exportJob.proxyProc = null;
      if (exportJob.proxyStopped) { pr.ok = false; pr.error = $t('srv.proxyStopped'); }
      if (pr.ok) exportJob.result.proxy = pr.proxy; else exportJob.proxyError = pr.error;
      // API（mittler_api.py の export）で始めた書き出し：プレビューに使う（preview.proxy）のもサーバーが（編集画面が見ていなくても入る。editor/ops.js の applyProxy＝窓のときと同じ）
      if (pr.ok && o.by === 'api') { await withTimeline(tl => { OPS.applyProxy(tl, pr.proxy, $t('ex.proxyNote', { name: path.basename(outFile) })); }); exportJob.proxyApplied = true; }
    }
    exportJob.state = 'done'; exportJob.finished = Date.now();
    log(`書き出し: できた ${exportJob.result.path}（${(exportJob.result.bytes / 1e6).toFixed(1)}MB・${exportJob.result.dur.toFixed(2)}秒・SHA ${sha.slice(0, 12)}…）`);
  }
  // 🏆 マスター書き出し（機能追加案03 v2）：このPCで `mittler master`（書き出し前チェック → ① アプスケ → ② 補間 → ③ 4K・60fps で描く → ④ 縮めてエンコード・音 → ⑤ 片付け）。
  // 書き出しと同じ枠（exportJob）で動く（同時に1つ・止めるも同じ）。進み具合は PHASE の行（check・upscale i n・interp i n・render）と PROGRESS。
  // 止めた理由（scale 未対応のエフェクト・道具が無い）は MASTER_STOP の行 → exportJob.error（名指しの一覧）・exportJob.stop
  async function runMaster(o) {
    const tl = readTimeline(), M = masterCfg();
    const t0 = Math.max(0, +o.from || 0), t1 = Math.min(tl.duration, o.to != null && o.to !== '' ? +o.to : tl.duration);
    if (!(t1 > t0)) throw KE('srv.badRange');
    const name = String(o.name || 'master').replace(/[\\/:*?"<>|]/g, '_').replace(/\.mp4$/i, '').trim() + '.mp4';
    const jn = Math.round(+o.jobs || M.jobs || 0), jobs = jn > 0 ? Math.min(32, jn) : 0;  // 0＝自動（mittler master が CPU の数と空いているメモリから決める。master.py の render_jobs）
    // 書き出しの大きさ：outHeight は短い辺（縦長の作品は幅。mittler の master_size と同じ。2026-10-31）
    const W = tl.width || 1920, H = tl.height || 1080, port = W < H;
    // アップスケールのモデル：mittler master がタイムライン（作品の settings.master.upscale・クリップの upscale）から決める。ここは記録と表示だけ
    // ただし 🏆 の窓から始めたときは、窓で選んでいるもの（o.upscale）を --upscale で渡す（作品の設定より強い。クリップの upscale はさらに強い）。
    // 窓で「実写」を選んだのに、タイムラインに入っていなくてアニメで書き出された（2026-10-31 に直した）
    // 「なし（60fps だけ）」（DEF.masterNoUpscale。アップスケールせず 60fps にするだけの版）：mittler master が
    // キャンバスを 1 倍・縮めないにする（--master-scale・--master-out は使わない）。クリップの upscale（アニメ・実写）は使わない
    const NONE = DEF.masterNoUpscale, UP = { anime: 'srv.up.anime', real: 'srv.up.real', [NONE]: 'srv.up.none' };  // 値 → 表示の鍵（cfg.upscale は窓のツールチップに出す）
    const ov = Object.prototype.hasOwnProperty.call(UP, o.upscale) ? o.upscale : null, wup = ov || ((tl.settings || {}).master || {}).upscale, noUp = wup === NONE;
    const scale = noUp ? 1 : M.scale, outH = noUp ? 0 : M.outHeight;
    // 書き出しの大きさ：outHeight は短い辺（縦長の作品は幅。mittler の master_size と同じ。2026-10-31）。なしなら縮めない（タイムラインの大きさ）
    const oh = outH > 0 ? (port ? 2 * Math.round(H * outH / W / 2) : outH) : Math.round(H * scale);
    const ow = outH > 0 ? (port ? outH : 2 * Math.round(W * outH / H / 2)) : Math.round(W * scale);
    const nOver = (tl.tracks || []).reduce((n, tr) => n + (tr.hidden ? 0 : (tr.clips || []).filter(c => !c.disabled && c.upscale && c.upscale !== wup).length), 0);
    // 画質の表示（l の言葉で。窓には今の言葉、ログには日本語）
    const upTextIn = l => {
      const pcUp = M.esrganModel === DEF.masterUpscale.anime ? I18N.tr(l, 'srv.up.pcDefault') : I18N.tr(l, 'srv.up.pc', { model: M.esrganModel });
      return (UP[wup] ? I18N.tr(l, UP[wup]) : (wup ? String(wup) : pcUp)) + (nOver ? I18N.tr(l, noUp ? 'srv.up.overUnused' : 'srv.up.over', { n: nOver }) : '');
    };
    const upText = upTextIn(lang);
    for (const k of Object.keys(exportJob)) delete exportJob[k];
    bakeStop('export');
    Object.assign(exportJob, { state: 'preparing', master: true, fresh: !!o.fresh, name, from: t0, to: t1, jobs, scale: 1, step: 1, draft: false, done: 0, total: Math.ceil(Math.round((t1 - t0) * M.fps)),
      sec: 0, started: Date.now(), wantProxy: false, phase: 'check', phaseDone: 0, phaseTotal: 0, cfg: { scale, fps: M.fps, outHeight: outH, size: `${ow}×${oh}`, upscale: upText, kind: wup || '' } });  // kind：画質の値（anime・real・none。空＝選んでいない）。窓の表示用
    log(`マスター書き出し: ${name}（${+t0.toFixed(3)}〜${+t1.toFixed(3)}秒・${jobs || '自動の数の'}並列・${scale}倍のキャンバス・${M.fps}fps → ${ow}×${oh}・アップスケール ${upTextIn('ja')}${o.force ? '・scale 未対応も承知で' : ''}${o.fresh ? '・キャッシュを捨てて新規で' : ''}）`);
    const local = await renderer.ensure();
    const rOut = path.join(project, 'output', name);
    Object.assign(exportJob, { rOut, where: WHERE });
    if (exportJob.state === 'cancelling') { exportJob.state = 'cancelled'; log('マスター書き出し: 止めた'); return; }
    exportJob.state = 'rendering';
    const onLine = ln => {
      let m;
      if ((m = /^PHASE (\w+)(?: (\d+) (\d+))?/.exec(ln))) { exportJob.phase = m[1]; exportJob.phaseDone = +(m[2] || 0); exportJob.phaseTotal = +(m[3] || 0); }
      else if ((m = /^PROGRESS (\d+) (\d+) (\d+)/.exec(ln))) { exportJob.done = +m[1]; exportJob.total = +m[2]; exportJob.sec = +m[3]; }
      else if (ln === 'MUXING') { exportJob.phase = 'encode'; if (exportJob.state === 'rendering') exportJob.state = 'muxing'; }
      else if (ln === 'CANCELLED') exportJob.cancelled = true;
      else if (ln.startsWith('MASTER_STOP ')) { try { exportJob.stop = JSON.parse(ln.slice(12)); } catch (e) { exportJob.stop = { kind: 'other', message: ln.slice(12) }; } }
      else if (ln.startsWith('MASTER_WARN ')) { exportJob.warning = ln.slice(12); log('マスター書き出し: 注意 ' + exportJob.warning); }
      else if (ln.startsWith('LOUDNORM_WARN ')) { exportJob.warning = ln.slice(14); log('マスター書き出し: 注意 ' + exportJob.warning); }
      else if ((m = /^render (\d+) 並列/.exec(ln))) { exportJob.jobs = +m[1]; log('マスター書き出し: ' + ln.slice(0, 300)); }  // 自動で決まった並列の数
      else if (/^(mix|wrote|cache|upscale|interp|fresh) /.test(ln)) log('マスター書き出し: ' + ln.slice(0, 300));  // upscale の行にはモデルも（「upscale モデル：…」・キャッシュの名前）
    };
    fs.mkdirSync(path.dirname(rOut), { recursive: true });
    const args = ['-X', 'utf8', '-B', '-m', 'mittler', 'master', timelineFile, rOut, ...(jobs ? ['--jobs', String(jobs)] : []), '--from', String(t0), '--to', String(t1),
      '--master-scale', String(M.scale), '--master-fps', String(M.fps), '--master-out', String(M.outHeight),
      '--esrgan', String(M.esrgan), '--esrgan-model', String(M.esrganModel), '--rife', String(M.rife), '--cache-gb', String(M.cacheGb), ...(ov ? ['--upscale', ov] : []), ...(o.force ? ['--force'] : []),
      ...(o.fresh ? ['--fresh'] : [])];  // キャッシュを捨てて新規で：この作品の work/master の upscale・interp を、チェックが通ったあとに全部捨ててから作る
    const r = await runLines(local.python, args, { cwd: path.join(ROOT, 'pyengine'), env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1' }) }, onLine);
    exportJob.proc = null;
    if (!cancelMissed(r) && (exportJob.cancelled || r.code === 3 || exportJob.state === 'cancelling')) { exportJob.state = 'cancelled'; log('マスター書き出し: 止めた'); return; }
    if (exportJob.stop) throw new Error(exportJob.stop.message);  // 書き出し前チェック・道具が無い：名指しの理由（描き始めていない）
    if (r.code) throw KE('srv.mExportFail', { where: I18N.L('ex.thisPC'), code: r.code, err: (r.err || r.out).slice(-1200) });
    const sha = await sha256(rOut);
    exportJob.result = { path: path.relative(project, rOut).split(path.sep).join('/'), bytes: fs.statSync(rOut).size, sha256: sha, dur: await probeDur(rOut).catch(() => 0), where: WHERE,
      scale: 1, step: 1, draft: false, master: true, fps: M.fps, size: `${ow}×${oh}` };
    exportJob.state = 'done'; exportJob.finished = Date.now();
    log(`マスター書き出し: できた ${exportJob.result.path}（${(exportJob.result.bytes / 1e6).toFixed(1)}MB・${exportJob.result.dur.toFixed(2)}秒・SHA ${sha.slice(0, 12)}…）`);
  }
  // 止める：<出力>.cancel を作る（mittler video が見て区間のプロセスを止める）。準備の途中なら、描き始める前に止める
  // 再生用の動画を作っている途中（state 'proxy'）は、その作る処理だけを止める（書き出した MP4 はもうできているので、書き出しは「できた」になる。前は止められなかった）
  function cancelExport() {
    if (exportJob.state === 'proxy') { exportJob.proxyStopped = true; killTree(exportJob.proxyProc); return; }
    if (!['preparing', 'rendering', 'muxing'].includes(exportJob.state)) return;
    const was = exportJob.state; exportJob.state = 'cancelling';
    if (was === 'preparing') return;
    try { fs.writeFileSync(exportJob.rOut + '.cancel', ''); } catch (e) { }
  }
  // 止めるのが間に合わなかった（音を混ぜる・つなぐ段に入ってからの「止める」は届かない）：書き出しは最後まで終わっているので「できた」にして、そう知らせる。
  // 前は、MP4 ができているのに「止めた」になり、<出力>.cancel も残った。→ true なら間に合わなかった（呼んだ側は「できた」の流れを続ける）
  function cancelMissed(r) {
    if (exportJob.state !== 'cancelling' || exportJob.cancelled || r.code !== 0) return false;
    try { fs.unlinkSync(exportJob.rOut + '.cancel'); } catch (e) { }
    // warning は日本語のまま（エンジンの注意と同じ欄。tools・smoke が読む）。画面は warningKey を今の言葉で出す
    exportJob.state = 'muxing'; exportJob.warning = I18N.tr('ja', 'srv.cancelMissed'); exportJob.warningKey = 'srv.cancelMissed';
    log('書き出し: ' + exportJob.warning);
    return true;
  }
  // ======== API から人の操作を（2026-11-15。Suno の採用と H3 の生成のほか、人の操作が要る所は全部 API から） ========
  // タイムラインの書きかえは editor/ops.js（編集画面のボタンと同じ関数）。サーバーがファイルを書き、開いている編集画面は「外の直し」として読み直す（Ctrl+Z で戻せる）。
  // 書きかえは 1 つずつ順に（ほかの API の書きかえと重ねない）。編集画面の保存の直後（0.7 秒）は少し待つ。直したあとの時刻の決まり・動画の長さは ops.finish（change と同じ）
  let opChain = Promise.resolve(), lastPut = 0;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  function writeTimeline(tl) { const tmp = timelineFile + '.tmp'; fs.writeFileSync(tmp, JSON.stringify(tl, null, 1) + '\n', 'utf8'); ATOMIC.replace(tmp, timelineFile); }
  function withTimeline(fn, opts) {
    const p = opChain.then(async () => {
      for (let i = 0; i < 15 && Date.now() - lastPut < 700; i++) await sleep(200);
      const tl = readTimeline(), before = JSON.stringify(tl);
      const r = (await fn(tl)) || {};
      if (r.abort) return Object.assign({ ok: false, changed: false }, r, { abort: undefined });
      OPS.finish(tl, before, opts);
      const changed = JSON.stringify(tl) !== before;
      if (changed) { writeTimeline(tl); notify('timeline'); }
      return Object.assign({ ok: true, changed }, r);
    });
    opChain = p.catch(() => { });
    return p;
  }
  // editor/ops.js に渡すもの（編集画面の opsEnv と同じ形。名前は今の言葉・知らせはサーバーの言葉）
  const msgOf = (k, v) => ({ k, v, lazy: true, toString() { return I18N.tr(lang, k, v); } });
  const clipName = c => c.label || (c.type === 'tts' ? c.text : '') || (c.type === 'effect' ? c.effect : '') || String((Array.isArray(c.src) ? c.src[0] : c.src) || '').split('/').pop() || c.id;
  async function opsEnvFor(need) {
    let fx = {}, fxReady = false;
    if (need && need.fx) { try { await renderer.waitReady(); fx = await renderer.effects(); fxReady = true; } catch (e) { } }
    const durs = (need && need.durs) || new Map();
    return { uid: p => p + '_' + Math.random().toString(36).slice(2, 8), t: (k, v) => $t(k, v), L: msgOf, label: clipName, name: c => msgOf('cm.q', { x: clipName(c) }),
      isPerCut: c => !!((((fx[c.effect] || {}).meta || {}).window || {}).per_cut), fxMeta: c => (fx[c.effect] || {}).meta || {}, srcDur: c => (durs.has(c.id) ? durs.get(c.id) : null), fxReady };
  }
  // 素材の長さ（カットに合わせるとき。編集画面はアセットの一覧・波形の長さ＝どちらも ffprobe の format の長さ）
  async function srcDurs(tl) {
    const root = path.resolve(project, tl.root || '.'), out = new Map();
    await Promise.all(OPS.allClips(tl).map(async ({ c }) => {
      if (c.type === 'tts') { const k = (c.takes || []).find(x => x.id === c.activeTake); if (k) out.set(c.id, +k.dur); return; }
      if (c.type !== 'video' && c.type !== 'audio') return;
      const s = OPS.vaSrc(c), f = s && inside(root, s); if (!f || !fs.existsSync(f)) return;
      const k = `${f}|${fs.statSync(f).size}`;
      if (!durCache.has(k)) durCache.set(k, await thumbJob(() => probeDur(f)).catch(() => 0));
      if (durCache.get(k)) out.set(c.id, durCache.get(k));
    }));
    return out;
  }
  const charsOf = () => projectChars().d.characters;
  const needClip = (tl, id, type) => { const f = OPS.findClip(tl, id); if (!f || (type && f.clip.type !== type)) throw KE('srv.op.noClip', { id, type: type || '' }); return f; };
  const cutItem = (K, label) => { const it = K.byLabel(label); if (!it) throw KE('srv.op.noCut', { label }); return it; };
  // 書きかえの一覧（名前 → (tl, args, E) → {message, …}）。どれも編集画面のボタンと同じ ops の関数を呼ぶ
  const OP_TABLE = {
    'tts-take': (tl, a) => { const f = needClip(tl, a.clip, 'tts'); if (!OPS.ttsSelectTake(f.clip, a.take)) throw KE('srv.op.noTake', { id: a.take }); return { message: $t('srv.op.selected', { id: a.take }) }; },
    'subs-from-lines': (tl, a, E) => {
      const sel = (a.clips || []).map(id => (OPS.findClip(tl, id) || {}).clip).filter(Boolean), lines = OPS.subLines(tl, sel);
      if (!lines.length) return { abort: true, error: $t('batch.noSubLines') };
      const r = OPS.subsFromLines(tl, lines, E);
      return Object.assign({ message: $t(r.kept ? 'batch.subsDoneKept' : 'batch.subsDone', r) }, r);
    },
    'frame-take': (tl, a) => { const f = needClip(tl, a.clip, 'plan'); if (!['start_frame', 'end_frame'].includes(a.which) || !OPS.planFrameTake(f.clip, a.which, a.take)) throw KE('srv.op.noTake', { id: a.take }); return { message: $t('srv.op.selected', { id: a.take }) }; },
    // 音のクリップのステム（Suno の audio-stems で取った WAV など）をミュートした音のトラックに置く（ops.placeStems。解析の stems と同じ形）
    'stems-place': (tl, a, E) => {
      const c = needClip(tl, a.clip, 'audio').clip, root = path.resolve(project, tl.root || '.');
      const stems = (a.stems || []).map(s => ({ src: String(s.src || '').replace(/\\/g, '/'), name: String(s.name || '') }));
      if (!stems.length) throw KE('srv.op.noStems');
      for (const s of stems) { const f = inside(root, s.src); if (!f || !fs.existsSync(f)) throw KE('srv.op.noAudioFile', { path: s.src }); if (!s.name) s.name = path.basename(f).replace(/\.[^.]+$/, ''); }
      const ids = OPS.placeStems(tl, c, stems, E);
      return { message: $t('srv.op.stemsPlaced', { n: ids.length }), tracks: ids };
    },
    'video-take': (tl, a) => { const f = needClip(tl, a.clip, 'plan'); if (!OPS.planVideoTake(f.clip, a.take)) throw KE('srv.op.noTake', { id: a.take }); return { message: $t('pl.takeSelected', { id: a.take }) }; },
    'adopt': (tl, a, E) => {
      const c = needClip(tl, a.clip, 'plan').clip, v = c.video || {}, id = a.take || v.activeTake, k = (v.takes || []).find(x => x.id === id);
      if (!k || !k.src) throw KE('srv.op.noTake', { id: id || '' });
      const r = OPS.adopt(tl, [[c, k]], E); if (!r) return { abort: true, error: $t('pl.noVideoTrack') };
      return { message: $t('pl.adoptedOne', { id: k.id, cuts: cutNoteOf(r.cuts) }), video_clip: c.video.adopted };
    },
    'adopt-all': (tl, a, E) => {
      const tr = a.track ? (tl.tracks || []).find(t => t.id === a.track && t.kind === 'plan') : null;
      if (a.track && !tr) throw KE('srv.op.noTrack', { id: a.track });
      if (!(tl.tracks || []).some(t => t.kind === 'video')) return { abort: true, error: $t('pl.noVideoTrackAdd') };
      const todo = OPS.pendingAdopt(tl, tr, !!a.latest); if (!todo.length) return { abort: true, error: $t(a.latest ? 'pl.nothingLatest' : 'pl.nothing') };
      const r = OPS.adopt(tl, todo, E);
      return { message: $t(a.latest ? 'pl.adoptedAllLatest' : 'pl.adoptedAll', { n: todo.length, cuts: cutNoteOf(r.cuts) }), n: todo.length };
    },
    // カットの段（cutmeta.js と同じ計算。ラベルで指す）
    'cut-first': (tl, a, E) => { const r = OPS.cuts(tl, E).firstCutIn(); if (!r) return { abort: true, error: $t('cm.cutsExists') }; return { message: $t(r.conv ? 'cm.firstCutConv' : 'cm.firstCut', { n: r.conv }) }; },
    'cut-lane': (tl, a, E) => {
      const K = OPS.cuts(tl, E), kind = a.kind === 'notes' ? 'notes' : 'cuts';
      if ((tl.meta || []).some(x => x.kind === kind)) return { abort: true, error: $t(kind === 'cuts' ? 'cm.cutsExists' : 'cm.notesExists') };
      if (kind === 'cuts') K.ensureCuts(); else K.ensureNotes();
      return { message: $t(kind === 'cuts' ? 'cm.cutsMade' : 'cm.notesMade') };
    },
    'cut-split': (tl, a, E) => {
      const K = OPS.cuts(tl, E), m = K.cutsMeta();
      if (!m || !m.items.length) { const r = K.firstCutIn(); return { message: $t('cm.firstCut'), label: r ? '1' : '' }; }
      const t = OPS.r6(K.snapFrame(+a.t)), it = a.label != null ? cutItem(K, a.label) : K.itemAt(m, t);
      if (!it) return { abort: true, error: $t('cm.noCutHere') };
      const er = K.splitErr(it, t); if (er) return { abort: true, error: String(er) };
      const old = K.lab(it), r = K.splitIn(m, it, t);
      return { message: $t('cm.splitDone', { old, t: OPS.fmt(t), label: K.lab(r.ni) }), label: K.lab(r.ni), moved: r.n.moved, split_clips: r.n.splitPic, copied_fx: r.n.dupFx };
    },
    'cut-join': (tl, a, E) => {
      const K = OPS.cuts(tl, E), m = K.cutsMeta(), it = cutItem(K, a.label), i = m.items.indexOf(it), dir = a.dir === 'next' ? 1 : -1;
      if (dir < 0 && i === 0) return { abort: true, error: $t('cm.joinFirst') };
      if (dir > 0 && i === m.items.length - 1) return { abort: true, error: $t('cm.joinLast') };
      const r = dir < 0 ? K.absorbIn(m, it, m.items[i - 1]) : K.absorbIn(m, m.items[i + 1], it);
      return { message: $t('cm.joined', { g: r.g, k: r.k, n: r.moved }), dropped: r.dropped };
    },
    'cut-remove': (tl, a, E) => {
      const K = OPS.cuts(tl, E), m = K.cutsMeta(), it = cutItem(K, a.label), i = m.items.indexOf(it);
      if (m.items.length < 2) return { abort: true, error: $t('cm.removeLast') };
      const r = K.absorbIn(m, it, m.items[i > 0 ? i - 1 : 1]);
      return { message: $t('cm.joined', { g: r.g, k: r.k, n: r.moved }), dropped: r.dropped };
    },
    'cut-rename': (tl, a, E) => {
      const K = OPS.cuts(tl, E), m = K.cutsMeta(), it = cutItem(K, a.label), nl = String(a.to || '').replace(/[\r\n\t]+/g, ' ').trim();
      if (!nl) return { abort: true, error: $t('cm.labelEmpty') };
      if (m.items.some(x => x !== it && K.lab(x) === nl)) return { abort: true, error: $t('cm.labelDup', { label: nl }) };
      const n = K.renameIn(it, nl); return { message: $t('cm.renamed', { old: String(a.label), label: nl, n }) };
    },
    'cut-edge': (tl, a, E) => {
      const K = OPS.cuts(tl, E), m = K.cutsMeta(), it = cutItem(K, a.label);
      const r = K.applyEdge(m, it, a.side === 'end' ? 'r' : 'l', +a.t); if (!r) return { abort: true, error: $t('cm.timesSame') };
      const w = K.mismatch(it);
      return { message: $t(r.nb ? 'cm.edgeMoved.boundary' : r.side === 'l' ? 'cm.edgeMoved.start' : 'cm.edgeMoved.end', { pair: K.lab(it), t: OPS.fmt(r.v) }), t: r.v, mismatch: !!w };
    },
    'cut-align': (tl, a, E) => {
      const K = OPS.cuts(tl, E), m = K.cutsMeta(); if (!m) return { abort: true, error: $t('cm.alignNone') };
      const items = (a.labels && a.labels.length) ? a.labels.map(l => cutItem(K, l)) : m.items.filter(x => K.mismatch(x));
      const pa = K.planAlign(items); if (pa.err) return { abort: true, error: $t('cm.alignFail', { label: pa.label, err: pa.err }) };
      if (!pa.todo.length) return { abort: true, error: $t('cm.alignNone') };
      K.applyAlign(pa.todo);
      return { message: $t('cm.aligned', { list: pa.todo.map(([it, p]) => $t('cm.alignItem', { label: K.lab(it), what: p.what })).join($t('cm.sepSlash')) }), labels: pa.todo.map(([it]) => K.lab(it)) };
    },
    'cut-from-clip': (tl, a, E) => {
      const K = OPS.cuts(tl, E), c = needClip(tl, a.clip).clip;
      const pe = K.rangePlan(K.cutsMeta(), c.start, c.start + c.dur); if (pe.err) return { abort: true, error: String(pe.err) };
      const r = K.cutFromClipIn(c); if (r.err) return { abort: true, error: String(r.err) };
      return { message: $t(r.kind === 'exist' ? 'cm.rangeExist' : 'cm.rangeMade', { a: OPS.fmt(c.start), b: OPS.fmt(c.start + c.dur), label: K.lab(r.it) }), label: K.lab(r.it), kind: r.kind };
    },
    'cuts-on-adopt': (tl, a, E) => { OPS.cuts(tl, E).setOnAdoptIn(!!a.on); return { message: $t(a.on ? 'cm.adoptOn' : 'cm.adoptOff') }; },
    // カット編集の道具のバー（cutedit.js と同じ計算。link：🔗 連動。既定はオン＝編集画面の既定と同じ）
    'split': (tl, a, E) => {
      const K = OPS.clipEdit(tl, E), fps = tl.fps || 30, t = Math.round(+a.t * fps) / fps, link = a.link !== false;
      let ids = (a.clips || []).filter(id => { const f = OPS.findClip(tl, id); return f && K.spans(f.clip, t); });
      if (!ids.length) ids = K.idsAt(t, false);
      if (!K.splitList(t, ids, link).length) return { abort: true, error: $t('ce.noSplit', { t: OPS.fmt(t) }) };
      const n = K.splitAt(t, ids, link); return { message: $t('ce.split', { n, t: OPS.fmt(t) }), n };
    },
    'delete': (tl, a, E) => { (a.clips || []).forEach(id => needClip(tl, id)); const n = OPS.clipEdit(tl, E).deleteClips(a.clips || [], a.link !== false); return { message: $t('ce.deleted', { n }), n }; },
    'ripple': (tl, a, E) => { (a.clips || []).forEach(id => needClip(tl, id)); const n = OPS.clipEdit(tl, E).rippleDelete(a.clips || [], a.link !== false); if (!n) return { abort: true, error: $t('why.noSel') }; return { message: $t('ce.ripple', { n }), n }; },
    'gaps': (tl, a, E) => {
      const trs = new Set((a.clips || []).map(id => needClip(tl, id).track));
      for (const id of a.tracks || []) { const tr = (tl.tracks || []).find(t => t.id === id); if (!tr) throw KE('srv.op.noTrack', { id }); trs.add(tr); }
      if (!trs.size) return { abort: true, error: $t('ce.gapsPick') };
      const moved = OPS.clipEdit(tl, E).closeGaps([...trs], a.link !== false); return { message: moved ? $t('ce.gaps', { n: moved }) : $t('ce.noGaps'), n: moved };
    },
    // ⟷ フッテージを伸ばす（映像の欄。warp.js と同じ）：to＝next（次のクリップの頭まで）・plan（予定の長さ）・秒数、how＝slow（ゆっくり）・hold（最後のコマで止める）
    'stretch': (tl, a, E) => {
      const K = OPS.clipEdit(tl, E), how = a.how === 'slow' ? 'slow' : 'hold', done = [];
      for (const id of a.clips || []) {
        const c = needClip(tl, id, 'video').clip;
        const T = a.to === 'next' ? K.nextTo(c) : a.to === 'plan' ? K.planTo(c) : +a.to;
        if (!(T > 0) || (a.to === 'next' && Math.abs(T - c.dur) < 1e-6)) continue;
        if (K.stretch(c, T, how, a.link !== false)) done.push(id);
      }
      if (!done.length) return { abort: true, error: $t('wp.nothing') };
      return { message: $t(how === 'slow' ? 'wp.stretchedAllSlow' : 'wp.stretchedAllHold', { n: done.length }), clips: done };
    },
  };
  const cutNoteOf = rs => { const ok = (rs || []).filter(r => r && r.label), ng = (rs || []).filter(r => r && r.err);
    return (ok.length ? $t('pl.cutNote', { list: ok.map(r => r.label + (r.kind === 'exist' ? $t('pl.existing') : '')).join($t('sep.list')) }) : '') + (ng.length ? $t('pl.cutNoteFail', { n: ng.length, err: String(ng[0].err) }) : ''); };
  const OP_NEEDS_FX = new Set(['adopt', 'adopt-all', 'cut-first', 'cut-lane', 'cut-split', 'cut-join', 'cut-remove', 'cut-rename', 'cut-edge', 'cut-align', 'cut-from-clip', 'cuts-on-adopt',
    'split', 'delete', 'ripple', 'gaps', 'stretch']);
  const ASYNC_OPS = { 'video-audio': opVideoAudio, 'place-video': opPlaceVideo, 'onbeat': opOnbeat };
  async function runOp(op, args) {
    if (ASYNC_OPS[op]) return ASYNC_OPS[op](args);
    const fn = OP_TABLE[op]; if (!fn) throw KE('srv.op.unknown', { op, list: Object.keys(OP_TABLE).concat(Object.keys(ASYNC_OPS)).join(', ') });
    const durs = op === 'cut-align' || op === 'stretch' ? await srcDurs(readTimeline()) : null;
    const E = await opsEnvFor({ fx: OP_NEEDS_FX.has(op), durs });
    if (OP_NEEDS_FX.has(op) && !E.fxReady) throw KE('srv.op.noFx');
    const r = await withTimeline(tl => fn(tl, args, E), op === 'cuts-on-adopt' ? { noExtend: true } : null);
    log(`API ${op}: ${r.ok ? (r.changed ? '直した' : '変わらない') : '止めた'} ${String(r.message || r.error || '').slice(0, 200)}`);
    return r;
  }
  // 動画の音を置く（道具のバーの「動画の音を置く」と同じ：取り出し /api/video_audio と同じ処理 → ops.vaPlace）
  async function extractVideoAudio(rel) {
    const root = path.resolve(project, readTimeline().root || '.'), file = inside(root, rel);
    if (!file || !fs.existsSync(file)) return { ok: false, error: $t('srv.noVideo') };
    const has = (await run('ffprobe', ['-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', file])).trim();
    if (!has) return { ok: true, none: true };
    const st = fs.statSync(file), tag = crypto.createHash('sha1').update(`${rel}|${st.size}|${st.mtimeMs}`).digest('hex').slice(0, 6);
    const name = (path.basename(file).replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_\-]/g, '_').replace(/_+/g, '_').slice(0, 40) || 'video') + '_' + tag + '.wav';
    const outRel = 'assets/video_audio/' + name, out = path.join(root, 'assets', 'video_audio', name);
    if (!fs.existsSync(out)) await once(out, async () => {
      if (fs.existsSync(out)) return;
      fs.mkdirSync(path.dirname(out), { recursive: true });
      const tmp = out + '.tmp.wav';
      await new Promise((ok, ng) => track(execFile('ffmpeg', ['-v', 'error', '-y', '-i', file, '-vn', '-map', '0:a:0', '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', tmp],
        { timeout: 600000, windowsHide: true }, e => e ? ng(e) : ok())));
      ATOMIC.replace(tmp, out);
    });
    log(`動画の音 ${rel} → ${outRel}`);
    return { ok: true, path: outRel, dur: await probeDur(out) };
  }
  async function opVideoAudio(a) {
    const ids = a.clips || [], done = [], skip = [];
    for (const id of ids) {
      const f = OPS.findClip(readTimeline(), id);
      if (!f || f.clip.type !== 'video') { skip.push({ clip: id, why: $t('srv.op.noClip', { id, type: 'video' }) }); continue; }
      const why = OPS.vaWhy(readTimeline(), f.clip); if (why) { skip.push({ clip: id, why: $t(why) }); continue; }
      const s = OPS.vaSrc(f.clip); if (!s) { skip.push({ clip: id, why: $t('ce.joinedNoAudio') }); continue; }
      let r; try { r = await extractVideoAudio(s); } catch (e) { r = { ok: false, error: E(e) }; }
      if (!r.ok) { skip.push({ clip: id, why: r.error || $t('ce.vaFailed') }); continue; } if (r.none) { skip.push({ clip: id, why: $t('ce.vaSilent') }); continue; }
      const E2 = await opsEnvFor();
      const w = await withTimeline(tl => { const g = OPS.findClip(tl, id); if (!g) return { abort: true }; OPS.vaPlace(tl, g.clip, r, E2); });
      if (w.ok) done.push({ clip: id, audio: r.path });
    }
    return { ok: done.length > 0 || !ids.length, changed: done.length > 0, placed: done, skipped: skip, message: skip.length ? $t('ce.vaPlacedSkip', { n: done.length, skip: [...new Set(skip.map(x => x.why))].join($t('sep.list')) }) : $t('ce.vaPlaced', { n: done.length }) };
  }
  // 動画を映像トラックに置く（アセット窓の「映像に置く」と同じ：音があれば取り出してリンクして置く → ops.placeVideo）
  async function opPlaceVideo(a) {
    const src = String(a.src || '').replace(/\\/g, '/'), tl0 = readTimeline(), root = path.resolve(project, tl0.root || '.'), file = inside(root, src);
    if (!file || !fs.existsSync(file)) throw KE('srv.noVideo');
    const fps = tl0.fps || 30, t = Math.round(Math.max(0, +a.at || 0) * fps) / fps, d = await probeDur(file).catch(() => 2) || 2;
    let au; try { au = await extractVideoAudio(src); } catch (e) { au = { ok: false, error: E(e) }; }
    const E2 = await opsEnvFor(), c = { id: E2.uid('vid'), type: 'video', src: [src], start: t, dur: +d.toFixed(3), in: 0, speed: 1, label: src.split('/').pop() };
    const r = await withTimeline(tl => {
      let tr = a.track ? (tl.tracks || []).find(x => x.id === a.track) : (tl.tracks || []).find(x => x.kind === 'video');
      if (!tr) throw KE(a.track ? 'srv.op.noTrack' : 'pl.noVideoTrack', { id: a.track });
      OPS.placeVideo(tl, tr, c, au, E2);
    });
    return Object.assign(r, { clip: c.id, audio: au && au.ok && !au.none ? au.path : null, message: $t(au && au.ok && !au.none ? 'ce.placedLinked' : au && au.none ? 'ce.placedSilent' : 'ce.placedNoAudio', { err: (au && au.error) || '' }) });
  }
  // 🎵 音ハメ（自動）：映像の欄の「音ハメ（自動）」と同じ（ops.warpAutoOpts・warpAutoQuery → 描画サーバーの /warp → ops.warpAutoApply）
  async function opOnbeat(a) {
    const c0 = needClip(readTimeline(), a.clip, 'video').clip;
    const o = OPS.warpAutoOpts(c0, a.fields || {}, a.adv || null), q = OPS.warpAutoQuery(readTimeline(), c0, o);
    if (!q) return { ok: false, error: $t('wp.noBeats') };
    await renderer.waitReady();
    const res = await renderer.warp(q);
    if (!res || !res.points) return { ok: false, error: E((res && res.error) || 'warp') };
    const r = await withTimeline(tl => { const f = OPS.findClip(tl, a.clip); if (!f) return { abort: true, error: $t('srv.op.noClip', { id: a.clip, type: 'video' }) }; OPS.warpAutoApply(f.clip, res, o); });
    return Object.assign(r, { message: $t(res.method === 'flow' ? 'wp.doneFlow' : 'wp.doneDiff', { n: (res.pairs || []).length, where: $t('ex.thisPC') }), pairs: (res.pairs || []).length, method: res.method });
  }
  // 🗣 セリフの声：1本作る（ファイルだけ）。前の /api/tts の中身（名前が重ならない _t<n>.wav・読み辞書）
  async function ttsGenerate(clipId, request, takenList) {
    const root = path.resolve(project, readTimeline().root || '.');
    const base = String(clipId || 'tts').replace(/[^A-Za-z0-9_\-]/g, '_');
    const dir = path.join(root, 'assets', 'voice'); fs.mkdirSync(dir, { recursive: true });
    const taken = new Set(takenList || []);  // そのクリップにもうあるテイクの名前とも重ならないように
    // 生成している途中の名前（ttsOut）とも重ならないように：前は、同じクリップの頼みが同時に 2 つ来ると、同じ _t<k>.wav を選んで上書きし合った
    let k = 1; while (fs.existsSync(path.join(dir, `${base}_t${k}.wav`)) || taken.has(`t${k}`) || ttsOut.has(path.join(dir, `${base}_t${k}.wav`))) k++;
    const out = path.join(dir, `${base}_t${k}.wav`);
    const dict = path.join(project, 'pronunciation.json');  // 作品の読み辞書（あれば）
    ttsOut.add(out);
    let r; try { r = await runTts(Object.assign({}, request, { out, voicevox_url: voicevoxUrl() }, fs.existsSync(dict) ? { dictionary: dict } : {})); } finally { ttsOut.delete(out); }
    if (!r.ok) return r;
    return { ok: true, id: `t${k}`, src: path.relative(root, out).split(path.sep).join('/'), dur: r.dur };
  }
  // 1本生成してテイクに入れる（編集画面の「生成」・「作り直す」と同じ：ops.ttsRequest → 生成 → ops.ttsAddTake）
  async function ttsClip(id) {
    const c = needClip(readTimeline(), id, 'tts').clip;
    if (!String(c.text || '').trim()) throw KE('srv.op.ttsNoText', { id });
    const request = OPS.ttsRequest(c, charsOf());
    log(`API セリフの声: ${id}（${request.engine}）`);
    const j = await ttsGenerate(id, request, (c.takes || []).map(k => k.id));
    if (!j.ok) return { ok: false, error: j.error || 'tts' };
    let ov = null;
    const r = await withTimeline(tl => { const f = OPS.findClip(tl, id); if (!f) return { abort: true, error: $t('srv.op.noClip', { id, type: 'tts' }) }; OPS.ttsAddTake(f.clip, j, request, new Date().toISOString()); ov = OPS.ttsOverlaps(tl).get(id) || null; });
    // 声の長さで伸びて、同じトラックの次のセリフに重なった：知らせる（編集画面ではクリップに印）
    return Object.assign(r, { clip: id, take: j.id, src: j.src, dur: j.dur, engine: request.engine, overlaps: ov,
      message: $t('tts.generated', { id: j.id, sec: (+j.dur).toFixed(2) }) + (ov ? $t('tts.overlapTail', { other: ov }) : '') });
  }
  // まとめて（「未生成のセリフを全部生成」pending・「全部を再生成」all と同じ：時間の順に1本ずつ、3 本続けて失敗したら止める）。止めるのは /api/tts/batch/stop
  const ttsBatch = { running: false, mode: null, stop: false, cur: null, done: 0, total: 0, fails: [], made: [] };
  const ttsBatchState = () => ({ running: ttsBatch.running, mode: ttsBatch.mode, cur: ttsBatch.cur, done: ttsBatch.done, total: ttsBatch.total, fails: ttsBatch.fails, made: ttsBatch.made, stopped: ttsBatch.stopped || false });
  function ttsBatchStart(mode) {
    if (ttsBatch.running) throw KE('srv.op.ttsBusy');
    const list = OPS.ttsLines(readTimeline(), mode).map(c => c.id);
    if (!list.length) throw KE(mode === 'all' ? 'srv.op.ttsNoLines' : 'srv.op.ttsNoPending');
    Object.assign(ttsBatch, { running: true, mode, stop: false, cur: null, done: 0, total: list.length, fails: [], made: [], stopped: false });
    log(`API セリフの声をまとめて: ${mode}・${list.length} 本`);
    (async () => {
      let streak = 0;
      for (const id of list) {
        if (ttsBatch.stop) break;
        const f = OPS.findClip(readTimeline(), id), c = f && f.clip;
        if (!c || !String(c.text || '').trim() || (mode === 'pending' && (c.takes || []).length)) { ttsBatch.done++; continue; }  // 途中で消した・ほかで生成した・文を消した
        ttsBatch.cur = id;
        let r; try { r = await ttsClip(id); } catch (e) { r = { ok: false, error: E(e) }; }
        if (r.ok) { ttsBatch.made.push({ clip: id, take: r.take }); streak = 0; } else { ttsBatch.fails.push({ clip: id, error: String(r.error || '').slice(-300) }); streak++; }
        ttsBatch.done++; ttsBatch.cur = null;
        if (streak >= 3) { ttsBatch.stop = true; ttsBatch.fails.push({ clip: '', error: $t('batch.streak') }); }
      }
      ttsBatch.stopped = ttsBatch.stop && ttsBatch.done < ttsBatch.total; ttsBatch.running = false; ttsBatch.cur = null;
      log(`API セリフの声をまとめて: 終わり（できた ${ttsBatch.made.length}・失敗 ${ttsBatch.fails.length}）`);
    })();
    return Object.assign({ ok: true }, ttsBatchState());
  }
  // 再生用の動画：make_proxy.py（--no-timeline）→ ops.applyProxy（書き出しの窓の「完了後、この動画をプレビュー再生に使う」と同じ）
  async function makeProxy(rel) {
    const f = inside(project, rel.replace(/\\/g, '/'));
    if (!f || !fs.existsSync(f) || !/\.(mp4|mov|mkv|webm)$/i.test(f)) throw KE('srv.op.noVideoFile', { path: rel });
    const local = await renderer.ensure();
    log(`API 再生用の動画: ${rel}`);
    const pr = await new Promise(ok => { track(execFile(local.python, ['-X', 'utf8', path.join(ROOT, 'tools', 'make_proxy.py'), timelineFile, f, '--no-timeline'],
      { timeout: 1800000, windowsHide: true }, (e, so) => { try { ok(JSON.parse(String(so).trim().split(/\r?\n/).pop())); } catch (err) { ok({ ok: false, error: String((e && e.message) || so).slice(-600) }); } })); });
    if (!pr.ok) return pr;
    const r = await withTimeline(tl => { OPS.applyProxy(tl, pr.proxy, $t('ex.proxyNote', { name: path.basename(f) })); });
    return Object.assign(r, { proxy: pr.proxy, bytes: pr.bytes, sec: pr.sec });
  }
  // 🎬 テイクの動画を真ん中のプレビューで見る（editor/plan.js の ▶。2026-11-16）：VS Code は H.264・AAC を再生できないので、WebM（make_proxy.py --no-timeline・高さ 720）を
  // 作品の work/proxy/<元の名前>.webm に作る。前に作ったもののほうが元より新しければそのまま。元が WebM ならそのまま
  async function takeProxy(rel) {
    const f = inside(project, String(rel || '').replace(/\\/g, '/'));
    if (!f || !fs.existsSync(f) || !/\.(mp4|mov|mkv|webm)$/i.test(f)) throw KE('srv.op.noVideoFile', { path: rel });
    const relOf = x => path.relative(project, x).split(path.sep).join('/');
    if (/\.webm$/i.test(f)) return { ok: true, proxy: relOf(f), made: false };
    const out = path.join(project, 'work', 'proxy', path.basename(f, path.extname(f)) + '.webm');
    const fresh = () => fs.existsSync(out) && fs.statSync(out).mtimeMs >= fs.statSync(f).mtimeMs;
    if (fresh()) return { ok: true, proxy: relOf(out), made: false };
    return once(out, async () => {
      if (fresh()) return { ok: true, proxy: relOf(out), made: false };
      const local = await renderer.ensure();
      log(`テイクの再生用の動画: ${rel}`);
      return new Promise(ok => { track(execFile(local.python, ['-X', 'utf8', path.join(ROOT, 'tools', 'make_proxy.py'), timelineFile, f, '--no-timeline', '--height', '720'],
        { timeout: 600000, windowsHide: true }, (e, so) => { try { ok(Object.assign(JSON.parse(String(so).trim().split(/\r?\n/).pop()), { made: true })); } catch (err) { ok({ ok: false, error: String((e && e.message) || so).slice(-600) }); } })); });
    });
  }
  // テイクの動画のサムネ（頭から 0.1 秒の 1 コマ。状態フォルダの thumbs/ にためる。thumbFor と同じ置き場と決まり）
  async function takeThumb(rel) {
    const f = inside(project, String(rel || '').replace(/\\/g, '/'));
    if (!f || !fs.existsSync(f) || !/\.(mp4|mov|mkv|webm)$/i.test(f)) throw KE('srv.op.noVideoFile', { path: rel });
    const st = fs.statSync(f);
    const key = crypto.createHash('sha1').update(`take|${f}|${st.size}|${st.mtimeMs}|${THUMB_H}`).digest('hex').slice(0, 16);
    const out = path.join(stateDir(), 'thumbs', key + '.jpg');
    if (!fs.existsSync(out)) await once(out, async () => {
      if (fs.existsSync(out)) return;
      fs.mkdirSync(path.dirname(out), { recursive: true });
      const tmp = out + '.tmp.jpg';
      await thumbJob(() => run('ffmpeg', ['-v', 'error', '-y', '-ss', '0.1', '-i', f, '-frames:v', '1', '-vf', `scale=-2:${THUMB_H}`, '-q:v', '4', tmp]));
      ATOMIC.replace(tmp, out);
    });
    return out;
  }
  // 書き出しを API で頼んだとき、決めていない値は窓の初めの値と同じに（名前・並列・プレビューに使う・マスターの画質）
  function apiExportDefaults(o) {
    const tl = readTimeline(), draft = (+o.step || 1) > 1 || ([0.5, 0.25].includes(+o.scale));
    if (!o.name) o.name = OPS.exportName(timelineFile, new Date(), !!o.master) + (draft && !o.master ? '_draft' : '');
    if (o.master) {
      if (o.upscale == null || o.upscale === '') o.upscale = OPS.masterUpscale(tl, masterCfg(), DEF.masterUpscale) || undefined;
      if (o.jobs == null) o.jobs = masterCfg().jobs || 0;
    } else {
      if (o.jobs == null) o.jobs = Math.max(1, Math.min(16, require('os').cpus().length - 2));
      if (o.proxy == null) o.proxy = !draft;
    }
  }
  // 👁 見える操作：開いている編集画面（変更通知 /api/events の道）に頼む → 編集画面が /api/ui/<id>/done で答える。開いていなければ理由を返す
  const uiWait = new Map();
  function uiSend(cmd, args, timeout) {
    if (!clients.size) return Promise.resolve({ ok: false, error: $t('srv.ui.noEditor') });
    const id = 'ui_' + crypto.randomBytes(4).toString('hex');
    return new Promise(ok => {
      const tm = setTimeout(() => { uiWait.delete(id); ok({ ok: false, error: $t('srv.ui.timeout') }); }, Math.max(1000, Math.min(120000, timeout || 15000)));
      uiWait.set(id, r => { clearTimeout(tm); uiWait.delete(id); ok(r); });
      for (const c of clients) c.write(`event: ui\ndata: ${JSON.stringify({ id, cmd, args })}\n\n`);
    });
  }
  const send = (res, code, body, type = 'application/json; charset=utf-8') => { res.writeHead(code, { 'Content-Type': type, 'Cache-Control': 'no-store' }); res.end(typeof body === 'string' ? body : JSON.stringify(body)); };

  // 変更通知（SSE）：タイムライン・スクリプト・素材が変わったら編集画面に知らせる
  let debounce = null; const pending = new Set();
  function notify(kind) {
    if (['timeline', 'effect', 'media', 'asset'].includes(kind)) bakeStop(kind);  // 裏で描いているものは古い絵になるので止める（編集画面がまた頼む）
    pending.add(kind); clearTimeout(debounce);
    debounce = setTimeout(() => { const kinds = [...pending]; pending.clear(); for (const c of clients) c.write(`event: change\ndata: ${JSON.stringify({ kinds })}\n\n`); }, 120);
  }
  // 中身が本当に変わったか：Windows はファイルを読んだだけでも（最後に開いた時刻が変わって）'change' が届く。書き出しの最中は描く処理が素材
  // （人のマスクの PNG など）を大量に読むので、そのたびに「絵が変わった」と知らせて、プレビューが細かく描き直されていた
  // （書き出しの最中にプレビューを描き直さないようにする）。大きさ・更新時刻を覚えておいて、変わったとき・消えたとき・
  // 新しくできたとき（覚えていないファイルは、更新時刻か作った時刻がこのサーバーの起動より後なら）だけ知らせる。フォルダ自体の変化は知らせない
  const seen = new Map(), T0 = Date.now() - 2000;
  function contentChanged(full) {
    let st; try { st = fs.statSync(full); } catch (e) { seen.delete(full); return true; }  // 消えた・名前が変わった
    if (st.isDirectory()) return false;
    const sig = st.size + ':' + st.mtimeMs, prev = seen.get(full); seen.set(full, sig);
    return prev !== undefined ? prev !== sig : (st.mtimeMs >= T0 || st.birthtimeMs >= T0);
  }
  let watcher = null;
  try {
    watcher = fs.watch(project, { recursive: true }, (ev, name) => {
      if (!name) return; const n = name.split(path.sep).join('/');
      if (NAMES.env('DEBUG')) console.error('[watch]', ev, n);  // 環境変数 MITTLER_DEBUG（古い名前 CC_DEBUG も）
      // 生成のジョブ（work/jobs/job_*.json）が変わった：編集画面がジョブを見に行って、できたものをテイクに入れる
      // （Claude が tools/mittler_api.py で頼んだものも。前は開いたときと、その画面で頼んだときしか見に行かなかったので、AI の側から置きかえても画面に出なかった）
      if (/^work\/jobs\/job_[^/]+\.json$/.test(n)) return contentChanged(path.join(project, name)) ? notify('jobs') : undefined;
      // 書き出し・作業ファイルでは読み直さない（Windows はフォルダ自体の変更 'work' も届く）
      if (IGNORE.has(n.split('/')[0]) || n.endsWith('.tmp')) return;
      // 素材の根 base/（偽マリアMV の書き出しの入力。マスクなど2万近いファイル）の変化では知らせない（前からの動き）
      if (n.split('/')[0] === 'base') return;
      if (!contentChanged(path.join(project, name))) return;  // 読んだだけ（最後に開いた時刻）・フォルダの変化
      const kind =path.resolve(project, name) === timelineFile ? 'timeline' : /^effects\/[^/]+\.py$/.test(n) ? 'effect'
        : n === 'characters.json' ? 'characters' : /\.cut\.json$/.test(n) ? null : 'asset';
      if (kind) notify(kind);
      // 絵・動画のファイル（同じ名前で上書きされたときも）：編集画面がサムネ・テイクの絵・プレビューを描き直す（描画サーバーは自分で更新時刻を見る）
      if (kind === 'asset' && MEDIA_EXT.test(n)) notify('media');
    });
  } catch (e) { console.error('[mittler] watch failed', e.message); }

  const server = http.createServer(async (req, res) => {
    try {
      const host = (req.headers.host || '').toLowerCase();
      if (host !== `127.0.0.1:${port}` && host !== `localhost:${port}`) return send(res, 403, { error: 'bad host' });
      const url = new URL(req.url, `http://127.0.0.1:${port}`);
      let p; try { p = decodeURIComponent(url.pathname); } catch (e) { return send(res, 400, { error: 'bad path' }); }  // /project/%E0 など、% のあとが正しくない（前は 500）
      const write = req.method !== 'GET' && req.method !== 'HEAD';
      const sent = NAMES.tokenOf(req.headers);  // ヘッダ X-Mittler-Token（古い名前 X-CC-Token も受ける。両方あれば新しいほう）
      if (write && sent !== token) return send(res, 403, { error: 'bad token' });
      // 副作用のある GET（プロセスを起動する・ファイルを書く）もトークンが要る。img・video・CSS の url() はヘッダーを付けられないので ?token= でもよい
      if (!write && TOKEN_GET.has(p) && sent !== token && url.searchParams.get('token') !== token) return send(res, 403, { error: 'bad token' });

      if (p === '/' ) { res.writeHead(302, { Location: `/editor/?token=${token}` }); return res.end(); }
      if (p === '/api/timeline' && req.method === 'GET') return send(res, 200, { file: path.basename(timelineFile), timeline: readTimeline() });
      if (p === '/api/timeline' && req.method === 'PUT') {
        const v = JSON.parse((await readBody(req)).toString('utf8'));
        // 取り込み器と同じ字下げ（git の差分を小さく）。置きかえは、描画サーバー（Python。コマごとにタイムラインを読む）が開いている瞬間に当たると
        // Windows では失敗する（EPERM）ので、短く待ってやり直す（server/atomic.js）
        const tmp = timelineFile + '.tmp'; fs.writeFileSync(tmp, JSON.stringify(v, null, 1) + '\n', 'utf8'); ATOMIC.replace(tmp, timelineFile);
        lastPut = Date.now();  // API の書きかえ（withTimeline）は、編集画面の保存の直後は少し待つ
        return send(res, 200, { ok: true });  // 編集画面はこのあと描き直す（描画サーバーは中身が変わったタイムラインを読み直す）
      }
      // 画面の言葉：GET は人が決めた言葉（決めていなければ今の言葉）と、人が決めたものか。POST {lang, save}：切り替えた（save が false でなければ、VS Code の中では拡張がユーザー設定 mittler.language に書く）。
      // save: false（URL の &lang= などで開いた画面が「今はこの言葉」と伝える）は、サーバーが返す文の言葉だけを変える（人が決めた言葉は変えない＝ほかの画面は決めた言葉で開く）
      if (p === '/api/lang' && req.method === 'GET') return send(res, 200, { lang: langSource === 'setting' ? langSetting : lang, source: langSource });
      if (p === '/api/lang' && req.method === 'POST') {
        const q = JSON.parse((await readBody(req, 1 << 12)).toString('utf8') || '{}');
        lang = I18N.norm(q.lang); process.env.MITTLER_LANG = lang;
        let saved = false;
        if (q.save !== false) {
          langSource = 'setting'; langSetting = lang;
          if (opts.saveLanguage) { try { await opts.saveLanguage(lang); saved = true; } catch (e) { log('言葉の設定を書けない: ' + (e.message || e)); } }
        }
        return send(res, 200, { ok: true, lang, saved });
      }
      if (p === '/api/quit' && req.method === 'POST' && opts.onQuit) {  // 単体で動かしたとき：片付けて止まる（描画サーバーも止める）
        send(res, 200, { ok: true }); setTimeout(opts.onQuit, 50); return;
      }
      // プレビューの絵（live=1）：描いている1枚と、待っている最新の1枚だけ。もっと新しい頼みが来たら、待っている古い頼みには 409 を返して捨てる
      // （描くのが重い作品で頼みが積もり、ブラウザの同時接続が埋まって再生用の動画が読めなくなった。2026-10-24）。ブラウザが取り消した頼みは描かない
      if (p === '/api/frame') bakePause();  // プレビューの絵を頼まれた（シーク・止めた所）：裏で描くのを一時停止
      if (p === '/api/frame' && url.searchParams.get('live')) {
        const job = { t: url.searchParams.get('t') || '0', q: url.searchParams.get('q'), prof: url.searchParams.get('prof') === '1', scale: url.searchParams.get('scale'),
          draft: url.searchParams.get('draft') === '1', res, gone: false };
        res.on('close', () => { if (!res.writableEnded) job.gone = true; });  // ブラウザが取り消した（req の close は GET だとすぐ来るので res で見る）
        if (live.busy) { if (live.wait) { const old = live.wait; if (!old.gone) send(old.res, 409, { superseded: true }); } live.wait = job; return; }
        return runLive(job);
      }
      if (p === '/api/frame') {
        await renderer.waitReady();
        const draft = url.searchParams.get('draft') === '1';  // ドラフト品質（ctx.draft。編集画面が再生・シークの間だけ付ける想定）
        const r = await renderer.frame(url.searchParams.get('t') || '0', url.searchParams.get('q'), null, { prof: url.searchParams.get('prof') === '1', scale: url.searchParams.get('scale'), draft });
        if (r.status === 200 && (url.searchParams.get('q') == null || +url.searchParams.get('q') >= 80) && !draft) lastFrame = { t: +(url.searchParams.get('t') || 0), body: r.body };  // 止めたときの1コマ（Claude に見せる用）
        const h = { 'Content-Type': r.headers['content-type'] || 'application/octet-stream', 'Cache-Control': 'no-store' };
        for (const k of FRAME_HEADERS) if (r.headers[k]) h[k] = r.headers[k];
        res.writeHead(r.status, h); return res.end(r.body);
      }
      if (p === '/api/warp/auto' && req.method === 'POST') {  // 🎵 音ハメ：{q}（mittler/onbeat.py の q）→ points・アクセント・動きの量
        try {
          const q = JSON.parse((await readBody(req, 1 << 20)).toString('utf8')).q || {};
          await renderer.waitReady();
          return send(res, 200, Object.assign({ ok: true, where: WHERE }, await renderer.warp(q)));
        } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      if (p === '/api/effects') { await renderer.waitReady(); return send(res, 200, await renderer.effects()); }
      // 部品の置き場（effects_lib/library.json のフォルダ：common・偽マリアのエフェクト集 false_maria）のエフェクトで、作品にまだ無いもの（3D のエフェクトなど。2026-11-13）と、
      // それを作品の effects/ に写す（上書きはしない）。
      // Blender の 3D（blender3d）を写すときは、場面のひな形（templates/3d/*.py）も作品の 3d/ に写す（あるものは写さない）
      if (p === '/api/effects_lib') { await renderer.waitReady(); return send(res, 200, await renderer.effectsLib()); }
      if (p === '/api/effects/add' && req.method === 'POST') {
        try {
          const name = String(JSON.parse((await readBody(req, 1 << 12)).toString('utf8')).name || '');
          if (!/^[A-Za-z0-9_-]+$/.test(name)) throw KE('srv.fxBadName', { name });
          // 置き場のフォルダ（effects_lib/library.json の packs。common・false_maria）を順に探す。読めなければ common だけ
          let packs = ['common'];
          try { packs = JSON.parse(fs.readFileSync(path.join(ROOT, 'effects_lib', 'library.json'), 'utf8')).packs.map(x => String(x.dir)); } catch (e) { }
          const src = packs.map(d => path.join(ROOT, 'effects_lib', d, name + '.py')).find(f => fs.existsSync(f)), dst = path.join(project, 'effects', name + '.py');
          if (!src) throw KE('srv.fxNoLib', { name });
          if (fs.existsSync(dst)) throw KE('srv.fxExists', { name });
          fs.mkdirSync(path.dirname(dst), { recursive: true });
          fs.copyFileSync(src, dst, fs.constants.COPYFILE_EXCL);
          const copied = [`effects/${name}.py`];
          if (name === 'html') {  // HTML のレイヤー：ひな形のページ（templates/html/<名前>/）と three.js（templates/html/vendor/）を作品の html/ に。ある名前は上書きしない
            const tdir = path.join(ROOT, 'templates', 'html');
            const walk = (d, rel) => {
              for (const e of fs.existsSync(d) ? fs.readdirSync(d, { withFileTypes: true }) : []) {
                const r = rel ? `${rel}/${e.name}` : e.name;
                if (e.isDirectory()) { walk(path.join(d, e.name), r); continue; }
                const to = path.join(project, 'html', ...r.split('/'));
                if (fs.existsSync(to)) continue;
                fs.mkdirSync(path.dirname(to), { recursive: true }); fs.copyFileSync(path.join(d, e.name), to, fs.constants.COPYFILE_EXCL); copied.push(`html/${r}`);
              }
            };
            walk(tdir, '');
          }
          if (name === 'blender3d') {
            const tdir = path.join(ROOT, 'templates', '3d');
            for (const n of fs.existsSync(tdir) ? fs.readdirSync(tdir).filter(n => n.endsWith('.py')) : []) {
              const to = path.join(project, '3d', n);
              if (fs.existsSync(to)) continue;
              fs.mkdirSync(path.dirname(to), { recursive: true }); fs.copyFileSync(path.join(tdir, n), to, fs.constants.COPYFILE_EXCL); copied.push(`3d/${n}`);
            }
          }
          log(`エフェクトを作品に入れた：${copied.join('・')}`);
          return send(res, 200, { ok: true, copied });
        } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      // 書き出し・プレビューで描いてためたコマの絵（作品の work/cache/frames/。pyengine/mittler/fcache.py）：数と大きさ・{clear: true} で全部消す
      if (p === '/api/fcache' && req.method === 'POST') {
        try {
          const clear = !!JSON.parse((await readBody(req, 1 << 12)).toString('utf8') || '{}').clear;
          const dir = path.join(cacheRoot(), 'cache', 'frames');
          let n = 0, bytes = 0;
          if (fs.existsSync(dir)) {
            for (const sub of fs.readdirSync(dir, { withFileTypes: true })) {
              if (!sub.isDirectory()) continue;
              for (const e of fs.readdirSync(path.join(dir, sub.name), { withFileTypes: true })) {
                if (!e.isFile() || !e.name.endsWith('.jpg')) continue;
                const f = path.join(dir, sub.name, e.name);
                try { bytes += fs.statSync(f).size; n++; if (clear) fs.unlinkSync(f); } catch (er) { }
              }
            }
          }
          if (clear) { await renderer.flush(); log(`ためたコマの絵を消した（${n} 枚）`); }
          return send(res, 200, { ok: true, frames: n, bytes, cleared: clear });
        } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      // Blender の 3D のクリップがためた絵（作品の work/3d/<クリップの id>/。pyengine/mittler/blender.py）を消す（「ためた絵を消す」「描き直す」）
      if (p === '/api/blender/clear' && req.method === 'POST') {
        try {
          const id = String(JSON.parse((await readBody(req, 1 << 12)).toString('utf8')).clip || '');
          const safe = (id.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 80)) || 'clip';  // blender.py の _safe と同じ（英数字と - _ のほかは _）
          const base = path.join(cacheRoot(), '3d'), dir = path.join(base, safe);
          if (path.dirname(dir) !== base) throw new Error('bad clip id');
          let n = 0;
          if (fs.existsSync(dir)) {
            const walk = d => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { if (e.isDirectory()) walk(path.join(d, e.name)); else n++; } };
            walk(dir);
            fs.rmSync(dir, { recursive: true, force: true });
          }
          await renderer.flush();  // 描画サーバーが覚えている JPEG も捨てる（同じ時刻を頼むと描き直す）
          log(`Blender の 3D：${safe} のためた絵を消した（${n} ファイル）`);
          return send(res, 200, { ok: true, files: n });
        } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      // 🔊 音の波形（タイムラインの音・セリフのクリップに出す）：素材ごとに ffmpeg の showwavespic で1枚（1秒 50px・最大 16000px）を状態フォルダの waves/ にためる。
      //   ?src=<素材の根からのパス> → {ok, key, dur, w}。&png=1 でその絵（k＝key が付いていればブラウザに覚えておいてもらう）
      if (p === '/api/wave') {
        try {
          const root = path.resolve(project, readTimeline().root || '.'), file = inside(root, url.searchParams.get('src') || '');
          if (!file || !fs.existsSync(file)) return send(res, 200, { ok: false, error: 'no file' });
          const st = fs.statSync(file);
          const key = crypto.createHash('sha1').update(`${file}|${st.size}|${st.mtimeMs}|wave1`).digest('hex').slice(0, 16);
          const png = path.join(stateDir(), 'waves', key + '.png'), meta = png.replace(/\.png$/, '.json');
          if (!fs.existsSync(meta)) {
            const bad = await once(png, async () => {  // 同じ素材の頼みが重なったら、作っている 1 つを待つ
              if (fs.existsSync(meta)) return null;
              const d = await probeDur(file); if (!(d > 0)) return 'no duration';
              const W = Math.max(200, Math.min(16000, Math.round(d * 50)));
              fs.mkdirSync(path.dirname(png), { recursive: true });
              const tmp = png + '.tmp.png';
              await thumbJob(() => run('ffmpeg', ['-v', 'error', '-y', '-i', file, '-filter_complex', `aformat=channel_layouts=mono,showwavespic=s=${W}x64:colors=white:scale=sqrt`, '-frames:v', '1', tmp]));
              ATOMIC.replace(tmp, png); fs.writeFileSync(meta, JSON.stringify({ dur: d, w: W }));
              return null;
            });
            if (bad) return send(res, 200, { ok: false, error: bad });
          }
          if (url.searchParams.get('png')) return sendFile(req, res, png, url.searchParams.get('k') ? 'private, max-age=86400' : null);
          return send(res, 200, Object.assign({ ok: true, key }, JSON.parse(fs.readFileSync(meta, 'utf8'))));
        } catch (e) { return send(res, 200, { ok: false, error: E(e).slice(-300) }); }
      }
      // 🔊 動画の音を取り出す：音のある動画 → <素材の根>/assets/video_audio/<名前>_<印>.wav（48 kHz・2ch・16bit。もうあれば作らない）→ {ok, path, dur}。音がなければ {ok, none}
      if (p === '/api/video_audio' && req.method === 'POST') {
        try {
          const q = JSON.parse((await readBody(req)).toString('utf8'));
          const root = path.resolve(project, readTimeline().root || '.'), rel = String(q.src || ''), file = inside(root, rel);
          if (!file || !fs.existsSync(file)) return send(res, 200, { ok: false, error: $t('srv.noVideo') });
          const has = (await run('ffprobe', ['-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', file])).trim();
          if (!has) return send(res, 200, { ok: true, none: true });
          const st = fs.statSync(file), tag = crypto.createHash('sha1').update(`${rel}|${st.size}|${st.mtimeMs}`).digest('hex').slice(0, 6);
          const name = (path.basename(file).replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_\-]/g, '_').replace(/_+/g, '_').slice(0, 40) || 'video') + '_' + tag + '.wav';
          const outRel = 'assets/video_audio/' + name, out = path.join(root, 'assets', 'video_audio', name);
          if (!fs.existsSync(out)) await once(out, async () => {  // 同じ動画の頼みが重なったら、作っている 1 つを待つ
            if (fs.existsSync(out)) return;
            fs.mkdirSync(path.dirname(out), { recursive: true });
            const tmp = out + '.tmp.wav';
            await new Promise((ok, ng) => track(execFile('ffmpeg', ['-v', 'error', '-y', '-i', file, '-vn', '-map', '0:a:0', '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', tmp],
              { timeout: 600000, windowsHide: true }, e => e ? ng(e) : ok())));
            ATOMIC.replace(tmp, out);
          });
          log(`動画の音 ${rel} → ${outRel}`);
          return send(res, 200, { ok: true, path: outRel, dur: await probeDur(out) });
        } catch (e) { return send(res, 200, { ok: false, error: E(e).slice(-300) }); }
      }
      if (p === '/api/thumb') {
        // v（クリップの中身の印。編集画面が付ける）があれば、ブラウザに覚えておいてもらう（タイムラインを描き直すたびに取り直さない）
        try { return sendFile(req, res, await thumbFor(url.searchParams.get('clip') || ''), url.searchParams.get('v') ? 'private, max-age=86400' : null); }
        catch (e) { return send(res, 404, { error: String(e.message || e) }); }
      }
      if (p === '/api/status' && renderer.st.dead) renderer.waitReady().catch(() => { });  // 止まっていたら起動し直す（待たない）
      if (p === '/api/status') return send(res, 200, { engine: 'py', where: WHERE, note: renderer.st.note || '', ready: renderer.st.ready, error: renderer.st.err ? E(renderer.st.err) : renderer.st.error });
      // エフェクトのコード（effects/*.py だけ）を読む・書く。VS Code では開く（openFile）
      if (p === '/api/file') {
        const rel = url.searchParams.get('path') || '';
        if (!/^(effects\/[A-Za-z0-9_\-]+\.py|characters\.json)$/.test(rel)) return send(res, 403, { error: $t('srv.fileOnly') });
        const f = inside(project, rel); if (!f) return send(res, 403, { error: 'forbidden' });
        if (req.method === 'GET') return send(res, 200, fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : '', 'text/plain; charset=utf-8');
        if (req.method === 'PUT') { const tmp = f + '.tmp'; fs.writeFileSync(tmp, await readBody(req)); ATOMIC.replace(tmp, f); return send(res, 200, { ok: true }); }
      }
      if (p === '/api/export' && req.method === 'GET') return send(res, 200, Object.assign({}, exportJob, { proc: undefined, proxyProc: undefined, where: WHERE, defaultJobs: Math.max(1, Math.min(16, require('os').cpus().length - 2)) }));
      if (p === '/api/export' && req.method === 'POST') {
        if (EXPORT_BUSY.includes(exportJob.state)) return send(res, 409, { error: $t('srv.exportBusy') });
        const o = JSON.parse((await readBody(req)).toString('utf8'));
        if (o.by === 'api') apiExportDefaults(o);  // API で頼んだ：決めていない値は窓の初めの値と同じに
        runExport(o).catch(e => { exportJob.proc = null; Object.assign(exportJob, { state: 'error', error: E(e).slice(-1500) }); log('書き出し: 失敗 ' + String(e.message || e).slice(-1500)); });
        if (o.by === 'api') exportJob.by = 'api';
        notify('export');  // 開いている編集画面が進み具合を見に行く（export.js）
        return send(res, 200, { ok: true, name: o.name, master: !!o.master, upscale: o.upscale, jobs: o.jobs, proxy: !!o.proxy });
      }
      if (p === '/api/export/cancel' && req.method === 'POST') { cancelExport(); return send(res, 200, { ok: true }); }
      // 🏆 マスター書き出し：設定（PC の設定か既定）・道具があるか・キャッシュの大きさ。始めるのは POST /api/export の {master: true}
      if (p === '/api/master' && req.method === 'GET') {
        const M = masterCfg(), has = f => { try { return fs.statSync(f).isFile(); } catch (e) { return false; } };
        // アップスケールの名前（作品の settings.master.upscale・クリップの upscale）→ モデルと、そのモデルが exe の隣の models/ にあるか（models/ が無ければ null＝分からない）
        const mdl = path.join(path.dirname(M.esrgan), 'models'), hasMdl = fs.existsSync(mdl);
        const models = Object.fromEntries(Object.entries(DEF.masterUpscale).map(([k, m]) => [k, hasMdl ? fs.readdirSync(mdl).some(n => n === m + '.param' || n.startsWith(m + '-x')) : null]));
        return send(res, 200, { settings: M, tools: { esrgan: has(M.esrgan), rife: has(M.rife), models }, upscale: DEF.masterUpscale, noUpscale: DEF.masterNoUpscale, cache: masterCache() });
      }
      if (p === '/api/master/cache/clear' && req.method === 'POST') {
        if (EXPORT_BUSY.includes(exportJob.state)) return send(res, 409, { ok: false, error: $t('srv.cacheBusy') });
        return send(res, 200, clearMasterCache());
      }
      if (p === '/api/log' && req.method === 'POST') { log('画面: ' + (await readBody(req, 1 << 16)).toString('utf8')); return send(res, 200, { ok: true }); }  // 画面で起きたこと（VS Code の記録に残る）
      if (p === '/api/assets') return send(res, 200, await listAssets());
      if (p === '/api/tts' && req.method === 'POST') {  // TTS を1本生成して新しいテイクのファイルにする（タイムラインに入れるのは編集画面。API の /api/tts/clip はサーバーが入れる）
        const q = JSON.parse((await readBody(req)).toString('utf8'));
        const r = await ttsGenerate(q.clip, q.request, q.taken);
        return send(res, r.ok ? 200 : 500, r);
      }
      // 🗣 セリフの声を API から（tools/mittler_api.py の tts・tts-all。2026-11-15）：生成して、テイクに入れるところまでサーバーが（editor/ops.js の ttsRequest・ttsAddTake＝編集画面の「生成」と同じ）
      if (p === '/api/tts/clip' && req.method === 'POST') {
        const q = JSON.parse((await readBody(req, 1 << 16)).toString('utf8'));
        try {
          // tempo（生成のあとの速さ）を言われたら、先にクリップの tempo に書く（右の欄の「速さ（生成のあと）」と同じ）
          if (q.tempo != null && q.tempo !== '') { const v = +q.tempo; await withTimeline(tl => { const f = OPS.findClip(tl, String(q.clip || '')); if (!f || f.clip.type !== 'tts' || !isFinite(v)) return { abort: true }; f.clip.tempo = Math.max(0.5, Math.min(2, v)); }); }
          return send(res, 200, await ttsClip(String(q.clip || '')));
        } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      if (p === '/api/tts/batch' && req.method === 'GET') return send(res, 200, ttsBatchState());
      if (p === '/api/tts/batch' && req.method === 'POST') {
        const q = JSON.parse((await readBody(req, 1 << 16)).toString('utf8') || '{}');
        try { return send(res, 200, ttsBatchStart(q.mode === 'all' ? 'all' : 'pending')); } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      if (p === '/api/tts/batch/stop' && req.method === 'POST') { ttsBatch.stop = !!ttsBatch.running; return send(res, 200, Object.assign({ ok: true }, ttsBatchState())); }
      // 🧩 タイムラインの書きかえを API から（editor/ops.js。編集画面のボタンと同じ計算）：{op, args} → {ok, changed, message, …}
      if (p === '/api/op' && req.method === 'POST') {
        const q = JSON.parse((await readBody(req, 1 << 20)).toString('utf8') || '{}');
        try { return send(res, 200, await runOp(String(q.op || ''), q.args || {})); } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      // 🎞 再生用の動画（WebM）を作ってプレビューに使う（API の proxy。書き出しの窓の「完了後、この動画をプレビュー再生に使う」と同じ make_proxy.py と preview.proxy）
      if (p === '/api/proxy' && req.method === 'POST') {
        const q = JSON.parse((await readBody(req, 1 << 16)).toString('utf8') || '{}');
        try { return send(res, 200, await makeProxy(String(q.src || ''))); } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      // 裏で先に描いてためる（bake）・ためた絵の地図・ためた絵の小さな JPEG（2026-11-16）
      if (p === '/api/bake' && req.method === 'POST') {
        const q = JSON.parse((await readBody(req, 1 << 12)).toString('utf8') || '{}');
        try { return send(res, 200, await bakeStart(q.from)); } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      if (p === '/api/bake/stop' && req.method === 'POST') { bakeStop('api'); return send(res, 200, Object.assign({ ok: true }, bakeState())); }
      if (p === '/api/bake/pause' && req.method === 'POST') { bakePause(); return send(res, 200, Object.assign({ ok: true }, bakeState())); }  // 編集画面の操作（ドラッグ・キー）
      if (p === '/api/bake' && req.method === 'GET') return send(res, 200, bakeState());
      if (p === '/api/cachemap') {
        try {
          const r = await renderer.cachemap(+url.searchParams.get('from') || 0, url.searchParams.get('to'));
          return send(res, 200, Object.assign(r, { bake: bakeState() }));
        } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      if (p === '/api/cframe') {  // 鍵（16 進 40 字）の絵だけ。中身は鍵で決まるので、ブラウザに覚えておいてもらう
        const k = String(url.searchParams.get('k') || '');
        if (!/^[0-9a-f]{40}$/.test(k)) return send(res, 400, { error: 'bad key' });
        return sendFile(req, res, path.join(cacheRoot(), 'cache', 'frames', k.slice(0, 2), k + '.p.jpg'), 'private, max-age=604800, immutable');
      }
      // 🎬 テイクの動画を見る：再生用の WebM（作るだけ。preview.proxy は変えない）・サムネ
      if (p === '/api/takeproxy' && req.method === 'POST') {
        const q = JSON.parse((await readBody(req, 1 << 16)).toString('utf8') || '{}');
        try { return send(res, 200, await takeProxy(String(q.src || ''))); } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      if (p === '/api/takethumb') {
        try { return sendFile(req, res, await takeThumb(url.searchParams.get('src') || ''), 'private, max-age=86400'); }
        catch (e) { return send(res, 404, { error: String(e.message || e) }); }
      }
      // 👁 画面の見える操作（API の ui。再生・止める・飛ぶ・選ぶ・タブ・拡大・言葉・窓）：開いている編集画面に頼んで、その答えを返す。作品は変えない
      if (p === '/api/ui' && req.method === 'POST') {
        const q = JSON.parse((await readBody(req, 1 << 16)).toString('utf8') || '{}');
        return send(res, 200, await uiSend(String(q.cmd || ''), q.args || {}, +q.timeout || 0));
      }
      const um = /^\/api\/ui\/(ui_[0-9a-f]+)\/done$/.exec(p);
      if (um && req.method === 'POST') { const f = uiWait.get(um[1]); const r = JSON.parse((await readBody(req, 1 << 20)).toString('utf8') || '{}'); if (f) f(r); return send(res, 200, { ok: !!f }); }
      if (p === '/api/annotate' && req.method === 'POST') {  // ✏️ 書き込んだ画面を保存して、VS Code の中なら Claude Code の入力欄にフォーカス
        try {
          const meta = saveAnnotation(JSON.parse((await readBody(req, 64 << 20)).toString('utf8')));
          let handed = false;
          if (opts.focusClaude) { try { handed = !!(await opts.focusClaude()); } catch (e) { log('Claude Code にフォーカスできない: ' + (e.message || e)); } }
          log(`書き込み ${meta.id}（${meta.t}s）`);
          refreshStatePending();
          return send(res, 200, { ok: true, id: meta.id, image: meta.image, path: path.join(project, meta.image), meta: path.join(project, STATE_NAME, 'annotations', meta.id, 'annotation.json'), handed });
        } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      // ✏️ 書き込みの記録を読む（編集画面の縮小と「Claude に届いたか」）：状態フォルダの annotations/<id>/ の after.jpg・before.jpg・annotation.json だけ（/project/ は状態フォルダを配らない）
      if (p === '/api/annotation' && req.method === 'GET') {
        const id = url.searchParams.get('id') || '', name = url.searchParams.get('file') || '';
        if (!/^ann_[0-9A-Za-z_-]+$/.test(id) || !['after.jpg', 'before.jpg', 'annotation.json'].includes(name)) return send(res, 404, { error: 'not found' });
        return sendFile(req, res, path.join(stateDir(), 'annotations', id, name));
      }
      if (p === '/api/state' && req.method === 'POST') {  // 編集画面の今の状態 → 状態フォルダの state.json（Claude Code が読む。tools/mittler_state.py のフックが毎回そえる）
        const st = JSON.parse((await readBody(req, 4 << 20)).toString('utf8'));
        writeState(st);
        return send(res, 200, { ok: true });
      }
      // キャラ設定のプリセット（このリポジトリの隣の presets/characters）：一覧・小さい絵・作品に写す
      if (p === '/api/presets/characters' && req.method === 'GET') return send(res, 200, listCharPresets());
      if (p === '/api/presets/thumb') { const id = String(url.searchParams.get('id') || '').replace(/[^A-Za-z0-9_-]/g, ''); if (!presetsDir()) return send(res, 404, { error: 'no presets' }); return sendFile(req, res, path.join(presetsDir(), 'thumbs', id + '.jpg')); }
      if (p === '/api/presets/characters/add' && req.method === 'POST') {
        const o = JSON.parse((await readBody(req)).toString('utf8'));
        try { return send(res, 200, addCharPreset(String(o.id || ''), !!o.overwrite)); } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      if (p === '/api/analyze' && req.method === 'GET') return send(res, 200, { jobs: anJobs, kinds: ANALYZE_KINDS, labels: AK.labels, labels_en: AK.labels_en || {} });  // labels_en：英語の画面のメニューの名前
      if (p === '/api/analyze' && req.method === 'POST') {
        const o = JSON.parse((await readBody(req, 4 << 20)).toString('utf8'));
        try { return send(res, 200, createAnalyze(o)); } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      const am = /^\/api\/analyze\/(an_[\w-]+)\/applied$/.exec(p);
      if (am && req.method === 'POST') { const j = anJobs.find(x => x.id === am[1]); if (j) { j.applied = true; anSave(); } return send(res, 200, { ok: !!j }); }
      // 🎵 Suno の曲（docs/Suno受け渡し契約.md の「Mittler 側の受け渡し」）：納品（tools/mittler_api.py の music-take）・一覧（編集画面が入れる）・入れた印・suno.com のページを開く
      if (p === '/api/music' && req.method === 'GET') return send(res, 200, { deliveries: music.list() });
      if ((p === '/api/music/take' || p === '/api/music/open') && req.method === 'POST') {
        const o = JSON.parse((await readBody(req, 1 << 20)).toString('utf8'));
        try { return send(res, 200, p === '/api/music/take' ? await music.take(o) : music.open(o.url)); } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }  // 断る理由は呼んだ側に出す
      }
      const mum = /^\/api\/music\/(mu_[\w-]+)\/applied$/.exec(p);
      if (mum && req.method === 'POST') return send(res, 200, { ok: music.applied(mum[1]) });
      if (p === '/api/jobs' && req.method === 'GET') return send(res, 200, listJobs());
      if (p === '/api/jobs' && req.method === 'POST') {
        const o = JSON.parse((await readBody(req, 1 << 20)).toString('utf8'));
        try { return send(res, 200, await createJob(o)); } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }  // 頼めない理由は画面に出す（HTTP のエラーにしない）
      }
      const jm = /^\/api\/jobs\/(job_[\w-]+)\/(cancel|applied)$/.exec(p);
      if (jm && req.method === 'POST') {
        const f = path.join(jobsDir(), jm[1] + '.json'); if (!fs.existsSync(f)) return send(res, 404, { error: 'no job' });
        const j = JSON.parse(fs.readFileSync(f, 'utf8')); j[jm[2] === 'cancel' ? 'cancel' : 'applied'] = true; writeJob(f, j);
        if (jm[2] === 'cancel') ensureRunner();
        return send(res, 200, { ok: true });
      }
      if (p === '/api/plan/resolve' && req.method === 'POST') {  // 🎬 プロンプトの参照（@import）を読んで、送るものを組み立てる（server/plan_refs.js）
        const o = JSON.parse((await readBody(req, 1 << 20)).toString('utf8'));
        const ctx = planCtx(typeof o.clip === 'object' ? o.clip.id : o.clip, o.which);
        if (o.clip && typeof o.clip === 'object') ctx.clip = o.clip;  // 編集画面の今のクリップ（まだ保存していなくてもよい）
        if (!ctx.clip) return send(res, 404, { error: 'no clip' });
        const text = o.text != null ? o.text : ((o.which === 'video' ? ctx.clip.video : ctx.clip[o.which]) || {}).prompt;
        const rr = require('./plan_refs').resolve(text, ctx);
        if (o.which !== 'video') { const en = imageEngine(ctx.clip[o.which], ctx.tl); rr.engine = en; rr.project_engine = projectImageEngine(ctx.tl); rr.max_refs = (ENGINES.engines[en] || {}).max_refs || 5; }  // 参照画像の上限（編集画面のチップ）
        return send(res, 200, rr);
      }
      if (p === '/api/voicevox/speakers') {  // このPCの VOICEVOX の話者（なければ空）
        try { const r = await fetch(voicevoxUrl() + '/speakers', { signal: AbortSignal.timeout(3000) }); return send(res, 200, await r.json()); }
        catch (e) { return send(res, 200, []); }
      }
      if (p === '/api/still' && req.method === 'POST') {  // 📷 表示中のコマを PNG で output/stills/ に保存（描画サーバーで描き直す）
        try {
          const o = JSON.parse((await readBody(req, 1 << 20)).toString('utf8'));
          const tl = readTimeline(), fps = tl.fps || 30, t = Math.max(0, +o.t || 0), n = Math.round(t * fps);
          await renderer.waitReady();
          const r = await renderer.frame(String(t), null, 'png');
          if (r.status !== 200) throw new Error(r.body.toString('utf8').trim().split('\n').slice(-1)[0] || ('HTTP ' + r.status));
          const png = r.body;
          const stem = path.basename(timelineFile).replace(/\.cut\.json$/, '').replace(/\.test$/, '');
          const mm = Math.floor(t / 60), ss = t - mm * 60;
          const name = `${stem}_${String(mm).padStart(2, '0')}m${ss.toFixed(3).padStart(6, '0').replace('.', 's')}_f${n}.png`;
          const out = path.join(project, 'output', 'stills', name);
          fs.mkdirSync(path.dirname(out), { recursive: true }); fs.writeFileSync(out, png);
          log(`PNG ${name}（${(png.length / 1e6).toFixed(1)}MB）`);
          return send(res, 200, { ok: true, path: `output/stills/${name}`, bytes: png.length });
        } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      if (p === '/api/reveal' && req.method === 'POST') {  // 📂 書き出し先を開く：作品の中のファイル（無ければそのフォルダ）をエクスプローラーで
        const rel = String(JSON.parse((await readBody(req)).toString('utf8')).path || 'output');
        let f = inside(project, rel); if (!f) return send(res, 200, { ok: false, error: $t('srv.outside') });
        if (!fs.existsSync(f)) { if (path.extname(f)) f = path.dirname(f); if (!fs.existsSync(f)) fs.mkdirSync(f, { recursive: true }); }  // 無いファイルならそのフォルダ、無いフォルダ（まだ書き出していない output）なら作る
        const how = opts.revealFile ? 'vscode' : NAMES.env('NO_REVEAL') ? 'none' : 'explorer';  // 環境変数 MITTLER_NO_REVEAL（古い名前 CC_NO_REVEAL も）
        if (how === 'vscode') opts.revealFile(f);
        else if (how === 'explorer' && process.platform === 'win32') {  // 単体で動かしたとき（ブラウザで開いた編集画面）
          const isDir = fs.statSync(f).isDirectory();
          require('child_process').spawn('explorer.exe', isDir ? [f] : ['/select,', f], { detached: true, stdio: 'ignore' }).unref();
        }
        log(`書き出し先を開く（${how}）: ${f}`);
        return send(res, 200, { ok: true, path: path.relative(project, f).split(path.sep).join('/') || '.', how });
      }
      if (p === '/api/open' && req.method === 'POST') {
        const rel = JSON.parse((await readBody(req)).toString('utf8')).path || '';
        const f = inside(project, rel); if (!f || !opts.openFile) return send(res, 404, { error: 'no opener' });
        opts.openFile(f); return send(res, 200, { ok: true });
      }
      // 🆕 新しい作品を作る（編集画面の「新規」ボタン。editor/newproject.js）。作るのは tools/new_project.js の create()（VS Code のコマンド「Mittler: 新しい作品を作る」・
      // スキル・コマンドラインと同じ 1 つの道。作り方をここに持たない）。決まりも create() のまま：名前は英数字と - _、置く先は無いか空のフォルダだけ。
      //   GET  /api/new_project        … 窓の初めの値（置く場所＝今の作品の親のフォルダ、ひな形の大きさ・fps・長さ、フォルダ選び・開くを VS Code に頼めるか）。トークンが要る（PC のパスを返すので）
      //   POST /api/new_project/pick   … 置く場所を OS のフォルダ選びで（VS Code の中だけ。拡張の pickFolder）
      //   POST /api/new_project        … 作る。VS Code の中なら、できたタイムラインを開く（拡張の openProject）
      //   POST /api/new_project/reveal … 直前にここで作った作品のフォルダをエクスプローラーで（ブラウザで直に開いているとき用。ほかの場所は開かない）
      if (p === '/api/new_project' && req.method === 'GET') {
        let tpl = {}; try { tpl = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'templates', 'project', 'project.cut.json'), 'utf8')); } catch (e) { }
        return send(res, 200, { parent: path.dirname(project), canPick: !!opts.pickFolder, canOpen: !!opts.openProject,
          defaults: { width: tpl.width || 1920, height: tpl.height || 1080, fps: tpl.fps || 30, duration: tpl.duration || 60 } });
      }
      if (p === '/api/new_project/pick' && req.method === 'POST') {
        if (!opts.pickFolder) return send(res, 200, { ok: false, error: $t('srv.np.pickOnlyVsc') });
        const q = JSON.parse((await readBody(req, 1 << 16)).toString('utf8') || '{}');
        try { const dir = await opts.pickFolder(String(q.start || path.dirname(project))); return send(res, 200, { ok: !!dir, dir: dir || '' }); }
        catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      if (p === '/api/new_project' && req.method === 'POST') {
        const q = JSON.parse((await readBody(req, 1 << 16)).toString('utf8'));
        const parent = String(q.parent || '').trim(), id = String(q.id || '').trim();
        try {
          if (!parent || !path.isAbsolute(parent)) throw KE('srv.np.abs');
          if (!fs.existsSync(parent) || !fs.statSync(parent).isDirectory()) throw KE('srv.np.noParent', { dir: parent });
          if (!id) throw KE('srv.np.noId');
          // lang：ひな形の名前（トラック・字幕など）の言葉。「＋ 新規」は画面の言葉を送る（無ければサーバーの言葉）
          const o = { dir: path.join(parent, id), title: String(q.title || '').trim() || id, lang: I18N.norm(q.lang || lang) };
          for (const k of ['width', 'height', 'fps', 'duration']) if (q[k] != null && q[k] !== '') o[k] = q[k];
          if (q.git === false) o.git = false;
          const r = require('../tools/new_project').create(o);  // 名前・空のフォルダ・大きさの確かめは create() がする
          lastNewProject = r.dir; log(`新しい作品を作った: ${r.dir}（git: ${r.git}）`);
          let opened = 'none';
          if (opts.openProject && q.open !== false) { try { await opts.openProject(r); opened = 'vscode'; } catch (e) { log('新しい作品を開けない: ' + (e.message || e)); r.notes.push($t('srv.np.openFail', { err: String(e.message || e) })); } }
          return send(res, 200, { ok: true, dir: r.dir, timeline: r.timeline, git: r.git, notes: r.notes, opened });
        } catch (e) { return send(res, 200, { ok: false, error: E(e) }); }
      }
      if (p === '/api/new_project/reveal' && req.method === 'POST') {
        if (!lastNewProject || !fs.existsSync(lastNewProject)) return send(res, 200, { ok: false, error: $t('srv.np.notYet') });
        const how = opts.revealFile ? 'vscode' : NAMES.env('NO_REVEAL') ? 'none' : 'explorer';
        if (how === 'vscode') opts.revealFile(lastNewProject);
        else if (how === 'explorer' && process.platform === 'win32') require('child_process').spawn('explorer.exe', [lastNewProject], { detached: true, stdio: 'ignore' }).unref();
        return send(res, 200, { ok: true, how });
      }
      if (p === '/api/events') {
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive' });
        res.write('retry: 1000\n\n'); clients.add(res); req.on('close', () => clients.delete(res)); return;
      }
      const map = [['/editor/', path.join(ROOT, 'editor')], ['/project/', project]];
      for (const [pre, base] of map) {
        if (!p.startsWith(pre)) continue;
        let rel = p.slice(pre.length); if (pre === '/editor/' && (rel === '' || rel.endsWith('/'))) rel += 'index.html';
        const f = inside(base, rel); if (!f) return send(res, 403, { error: 'forbidden' });
        if (pre === '/project/' && hiddenIn(base, f)) return send(res, 403, { error: 'forbidden' });  // .git・状態フォルダ（.mittler・.claude-cut。トークン）は配らない
        return sendFile(req, res, f);
      }
      send(res, 404, { error: 'not found' });
    } catch (e) { console.error('[mittler]', e); try { send(res, 500, { error: E(e) }); } catch (_) { } }
  });

  return new Promise((ok, ng) => {
    server.on('error', ng);
    server.listen(opts.port || 0, '127.0.0.1', () => {
      port = server.address().port;
      // Claude Code（編集画面の外）からジョブなどを頼むための入口：作品の状態フォルダ（.mittler。古い作品は .claude-cut）の server.json にポートとトークン（git には入らない。tools/mittler_api.py が読む）
      try { fs.mkdirSync(stateDir(), { recursive: true }); fs.writeFileSync(serverInfo(), JSON.stringify({ port, token, pid: process.pid, started: new Date().toISOString(), timeline: path.basename(timelineFile) }, null, 1)); } catch (e) { log('server.json を書けない: ' + e.message); }
      ok({
        port, token, project, timelineFile,
        url: `http://127.0.0.1:${port}/editor/?token=${token}`,
        // 描く python の準備の結果：'' なら描ける。だめなら理由の鍵（'srv.py.noRenderPython' など）。拡張が「Mittler: 初期設定」へ案内するのに使う
        renderReady: renderer.ready.then(ok => (ok ? '' : (renderer.st.err && renderer.st.err.key) || 'error')),
        close() { bakeStop('close'); if (watcher) watcher.close(); for (const c of clients) c.end(); server.close(); renderer.close(); cancelExport(); for (const pr of [...kids]) killTree(pr); markStateClosed();
          try { const o = JSON.parse(fs.readFileSync(serverInfo(), 'utf8')); if (o.token === token) fs.unlinkSync(serverInfo()); } catch (e) { } },  // 自分の書いた server.json だけ消す
      });
    });
  });
}

module.exports = { start };
