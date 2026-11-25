// Mittler：VS Code のコマンド「Mittler: 初期設定」（mittler.setup。2026-11-13 パッケージ化）。extension.js が登録する。
// 1. setup/mittler_setup.py --json で確かめる（何も変えない）→ 結果を出力の「Mittler」に出し、足りないものを知らせる。
// 2. 描く python が無ければ、ユーザーが押したときだけ、拡張の保存場所（globalStorage）の render-venv に venv を作って
//    setup/requirements-engine.txt（選べば requirements-3d.txt も）を入れ、設定 mittler.render.python をそこに向ける（何を入れるかを先に見せる）。
//    描く python がそこの venv で GPU の 3D（moderngl）が無ければ、押したときだけ足す。
// 3. Python・ffmpeg・Git・VS Code そのものは入れない：入れ方（winget のコマンド）を出力に出す。Blender は 3D を使う人への案内だけ。
// 画面と知らせの言葉は辞書の鍵（editor/i18n/*.json の ext.setup.*）。mittler_setup.py の項目の文は日本語なので、英語の画面では項目の名前だけ鍵で訳す。
'use strict';
const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');

const ROOT = __dirname;
const SETUP_PY = path.join(ROOT, 'setup', 'mittler_setup.py');
const REQ = path.join(ROOT, 'setup', 'requirements-engine.txt');
const REQ_3D = path.join(ROOT, 'setup', 'requirements-3d.txt');
const WINGET_PY = 'winget install Python.Python.3.12 --scope user';

let out = null;
const channel = () => out || (out = vscode.window.createOutputChannel('Mittler'));

// 子のプロセス：終わりの番号・標準出力・標準エラー（起動できなければ code -1 と理由）。Mittler の置き場に __pycache__ を書かない
function run(exe, args, o = {}) {
  return new Promise(ok => {
    try {
      execFile(exe, args, Object.assign({ windowsHide: true, maxBuffer: 32 << 20, encoding: 'utf8',
        env: Object.assign({}, process.env, { PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8' }) }, o),
      (e, so, se) => ok({ code: e ? (typeof e.code === 'number' ? e.code : -1) : 0, stdout: String(so || ''), stderr: String(se || ''), err: e ? String(e.message || e) : '' }));
    } catch (e) { ok({ code: -1, stdout: '', stderr: '', err: String(e.message || e) }); }
  });
}

// 道具を動かす python（標準ライブラリだけで足りる。3.10 以上）：設定 mittler.tools.python → PATH の python → py（Python ランチャー）
async function basePython(toolsPython) {
  for (const c of [toolsPython, 'python', 'py'].filter(Boolean)) {
    const r = await run(c, ['-c', 'import sys;print(sys.version_info[:2]>=(3,10))'], { timeout: 30000 });
    if (r.code === 0 && /True/.test(r.stdout)) return c;
  }
  return '';
}

// requirements の「名前==版」を並べる（確かめの窓に出す）
const pkgList = f => { try { return fs.readFileSync(f, 'utf8').split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith('#')).join(', '); } catch (e) { return ''; } };

const venvDir = storage => path.join(storage, 'render-venv');
const venvPython = storage => path.join(venvDir(storage), 'Scripts', 'python.exe');
const same = (a, b) => !!a && !!b && path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();

// env：{ $t, lang（今の言葉）, settings（extension.js の settingsNow() の返り値）, storage（globalStorage のフォルダ）, setRenderPython（値 → Promise） }
async function setup(env) {
  const { $t } = env;
  const ch = channel(); ch.clear(); ch.show(true);
  const py = await basePython(env.settings.python);
  if (!py) {
    ch.appendLine($t('ext.setup.noPython', { cmd: WINGET_PY }));
    const pick = await vscode.window.showErrorMessage($t('ext.setup.noPython', { cmd: WINGET_PY }), $t('ext.setup.btnCopy'));
    if (pick) await vscode.env.clipboard.writeText(WINGET_PY);
    return;
  }
  const res = await check(env, py);
  if (!res) return;
  const items = res.items || [];
  const missing = items.filter(i => i.level === 'missing');
  const renderMissing = items.some(i => i.id === 'render_python' && i.level === 'missing');
  const mine = same(res.render_python, venvPython(env.storage));
  const no3d = items.some(i => i.id === 'gl3d' && i.level !== 'ok');
  const btns = [];
  if (renderMissing) btns.push($t('ext.setup.btnInstallVenv'));
  else if (mine && no3d) btns.push($t('ext.setup.btn3d'));
  btns.push($t('ext.setup.btnRecheck'));
  const msg = res.ok ? $t('ext.setup.allOk') : $t('ext.setup.missing', { n: missing.length, list: missing.map(i => itemTitle(env, i)).join(' / ') });
  const pick = await (res.ok ? vscode.window.showInformationMessage(msg, ...btns) : vscode.window.showWarningMessage(msg, ...btns));
  if (pick === $t('ext.setup.btnInstallVenv')) return installVenv(env, py);
  if (pick === $t('ext.setup.btn3d')) return install3d(env, venvPython(env.storage));
  if (pick === $t('ext.setup.btnRecheck')) return setup(env);
}

// 項目の名前：日本語の画面は mittler_setup.py の文のまま、英語の画面は鍵 ext.setup.item.<id>（無ければ元の文）
function itemTitle(env, i) {
  if (env.lang === 'ja') return i.title;
  const k = 'ext.setup.item.' + i.id, v = env.$t(k);
  return v === k ? i.title : v;
}

// 確かめ（mittler_setup.py --json。何も変えない）→ 出力に並べて、結果の JSON を返す（失敗なら null）
async function check(env, py) {
  const { $t } = env, s = env.settings, ch = channel();
  const args = ['-X', 'utf8', '-B', SETUP_PY, '--json'];
  if (s.local && s.local.python) args.push('--python', s.local.python);
  if (s.local && s.local.ffmpegDir) args.push('--ffmpeg-dir', s.local.ffmpegDir);
  if (s.blenderPath) args.push('--blender', s.blenderPath);
  const r = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: $t('ext.setup.running') },
    () => run(py, args, { timeout: 600000, cwd: env.storage }));
  let res = null;
  try { res = JSON.parse(r.stdout); } catch (e) { }
  if (!res) {
    const err = (r.stderr || r.err || r.stdout).trim().split(/\r?\n/).slice(-3).join(' / ');
    ch.appendLine($t('ext.setup.failed', { err })); vscode.window.showErrorMessage($t('ext.setup.failed', { err }));
    return null;
  }
  print(env, res);
  return res;
}

function print(env, res) {
  const { $t } = env, ch = channel();
  ch.appendLine($t('ext.setup.outHead', { version: res.version || '?', kind: res.kind || '?', dir: res.repo || '' }));
  for (const i of res.items || []) {
    ch.appendLine(`${$t('ext.setup.mark.' + i.level)} ${itemTitle(env, i)}${i.detail ? ' : ' + i.detail : ''}`);
    for (const f of i.fix || []) ch.appendLine('      → ' + f);
  }
  const st = Object.entries(res.settings || {});
  if (st.length) { ch.appendLine(''); ch.appendLine($t('ext.setup.outSettings')); for (const [k, v] of st) ch.appendLine(`  ${JSON.stringify(k)}: ${JSON.stringify(v)},`); }
  ch.appendLine('');
}

// 描く python を入れる：何を入れるかを見せて、押したときだけ（拡張の保存場所の render-venv。パッケージは PyPI から取ってくる）
async function installVenv(env, py) {
  const { $t } = env, ch = channel();
  const q = await vscode.window.showQuickPick([
    { label: $t('ext.setup.venvEngine'), detail: pkgList(REQ), with3d: false },
    { label: $t('ext.setup.venv3d'), detail: pkgList(REQ) + ', ' + pkgList(REQ_3D), with3d: true },
  ], { title: $t('ext.setup.venvPick'), ignoreFocusOut: true });
  if (!q) return;
  const dir = venvDir(env.storage);
  const go = await vscode.window.showWarningMessage($t('ext.setup.venvConfirm', { dir, pkgs: q.detail }), { modal: true }, $t('ext.setup.btnInstall'));
  if (go !== $t('ext.setup.btnInstall')) return;
  fs.mkdirSync(env.storage, { recursive: true });
  const args = ['-X', 'utf8', '-B', SETUP_PY, '--install-venv', dir, '--json', ...(q.with3d ? ['--with-3d'] : [])];
  ch.appendLine($t('ext.setup.installing'));
  const r = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: $t('ext.setup.installing') },
    () => run(py, args, { timeout: 1800000, cwd: env.storage }));
  let res = null; try { res = JSON.parse(r.stdout); } catch (e) { }
  const acts = (res && res.actions) || [];
  for (const a of acts) ch.appendLine(`${a.returncode === 0 ? '[OK]' : '[NG]'} ${a.title}\n      ${a.command}${a.returncode ? '\n      ' + String(a.tail || '').trim() : ''}`);
  const vpy = venvPython(env.storage);
  if (!res || acts.some(a => a.ran && a.returncode !== 0) || !fs.existsSync(vpy)) {
    const err = res ? (acts.find(a => a.returncode !== 0) || {}).tail || '' : (r.stderr || r.err).trim().split(/\r?\n/).slice(-3).join(' / ');
    vscode.window.showErrorMessage($t('ext.setup.installFail', { err: String(err).trim().slice(-400) }));
    return;
  }
  print(env, res);
  await env.setRenderPython(vpy);
  vscode.window.showInformationMessage($t('ext.setup.installed', { py: vpy }));
}

// GPU の 3D（moderngl・glcontext）を、拡張の保存場所の venv に足す（押したときだけ）
async function install3d(env, vpy) {
  const { $t } = env, ch = channel();
  const go = await vscode.window.showWarningMessage($t('ext.setup.3dConfirm', { py: vpy, pkgs: pkgList(REQ_3D) }), { modal: true }, $t('ext.setup.btnInstall'));
  if (go !== $t('ext.setup.btnInstall')) return;
  const r = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: $t('ext.setup.installing') },
    () => run(vpy, ['-m', 'pip', 'install', '--only-binary=:all:', '-r', REQ_3D], { timeout: 1800000 }));
  ch.appendLine((r.stdout + r.stderr).trim().split(/\r?\n/).slice(-5).join('\n'));
  if (r.code) vscode.window.showErrorMessage($t('ext.setup.installFail', { err: (r.stderr || r.err).trim().slice(-400) }));
  else vscode.window.showInformationMessage($t('ext.setup.3dDone'));
}

// ---- 入れた直後の 1 回の知らせ（新しく入れた人に、描く python のパッケージの入れ方を案内する）----
// VS Code の起動が終わってから（package.json の activationEvents の onStartupFinished）、拡張の版ごとに 1 回だけ、短く確かめる（描く python が numpy・opencv・Pillow を
// import できるか・ffmpeg が見つかるか。静止画は描かない。数秒）。
// - 初めて入れたとき：足りなければ「準備が要る」＋「Mittler: 初期設定」「あとで」。足りていれば歓迎＋「新しい作品を作る」。
// - 版が上がったとき：足りないものがあるときだけ知らせる。
// - 知らせを出したら（どのボタンでも・閉じても）、その版ではもう出さない（globalState の mittler.seenVersion）。作品を開いたときの知らせ（ext.setup.noRender）は別に残る。
const SEEN_KEY = 'mittler.seenVersion';

// 描く python と ffmpeg の短い確かめ：{ render: 見つかった python か ''、ffmpeg: 見つかった ffmpeg か '' }。探す順は server/pyrender.js と同じ（設定 → 既定の場所 → PATH）
async function quickCheck(settings) {
  const D = require('./server/defaults');
  const local = (settings && settings.local) || {};
  const pys = [...new Set([local.python, D.renderPython, 'python'].filter(p => p && (!/[\\/]/.test(p) || fs.existsSync(p))))];
  let render = '';
  for (const p of local.python ? [local.python] : pys) {  // 設定の python があれば、それだけを見る（サーバーも設定の python だけを使う）
    const r = await run(p, ['-c', 'import numpy, cv2, PIL'], { timeout: 30000 });
    if (r.code === 0) { render = p; break; }
  }
  const dirs = [local.ffmpegDir, ...(D.ffmpegDirs || [])].filter(Boolean);
  let ffmpeg = (dirs.map(d => path.join(d, 'ffmpeg.exe')).find(f => fs.existsSync(f))) || '';
  if (!ffmpeg) { const r = await run('ffmpeg', ['-hide_banner', '-version'], { timeout: 15000 }); if (r.code === 0) ffmpeg = 'ffmpeg'; }
  return { render, ffmpeg };
}

// env：setupEnv と同じもの＋ { state（globalState）, version（この拡張の版）, commands（{ setup, newProject }：実行するコマンドの ID） }。返り値は何を出したか（確かめ用）
async function firstRun(env) {
  const { $t, state, version } = env;
  const seen = state.get(SEEN_KEY);
  if (seen === version) return { shown: '' };
  const q = await quickCheck(env.settings);
  const lack = [q.render ? '' : $t('ext.first.lackRender'), q.ffmpeg ? '' : $t('ext.first.lackFfmpeg')].filter(Boolean);
  let shown = '', pick;
  await state.update(SEEN_KEY, version);  // 先に覚える（ボタンを押さずに閉じても、この版ではもう出さない）
  if (lack.length) {
    shown = 'lack';
    pick = await vscode.window.showWarningMessage($t(seen ? 'ext.first.lackUpdated' : 'ext.first.lack', { list: lack.join($t('ext.first.sep')), version }),
      $t('ext.setup.btnSetup'), $t('ext.first.later'));
    if (pick === $t('ext.setup.btnSetup')) await vscode.commands.executeCommand(env.commands.setup);
  } else if (!seen) {
    shown = 'welcome';
    pick = await vscode.window.showInformationMessage($t('ext.first.welcome', { version }), $t('ext.first.btnNew'));
    if (pick === $t('ext.first.btnNew')) await vscode.commands.executeCommand(env.commands.newProject);
  }
  return { shown, lack, check: q };
}

module.exports = { setup, basePython, venvPython, channel, firstRun, quickCheck, SEEN_KEY };
