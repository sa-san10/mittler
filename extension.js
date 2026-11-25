// Mittler VS Code 拡張：*.cut.json を開くと編集画面が出る。（2026-11-12 に claude-cut から改名。古い名前の設定 claudeCut.* も読む：server/names.js）
// 中身はローカルサーバー（server/server.js）が配る編集画面を iframe で表示するだけ。ブラウザで開いても同じ画面になる。
// Claude Code は公式拡張をそのまま右に開いて使う（この拡張は Claude Code を埋め込まない）。
'use strict';
const vscode = require('vscode');
const path = require('path');
const { start } = require('./server/server');
const NAMES = require('./server/names');
const I18N = require('./server/i18n');  // 画面の言葉（辞書は editor/i18n/*.json）

const servers = new Map(); // タイムラインのパス → { server, refs }

// 描くのはこのPC（拡張が動いている PC。Remote-SSH ならつないだ先の PC）。PC ごとの設定（VS Code の mittler.*）をサーバーに渡す。
// 空の項目は server/defaults.js の既定値（設定ゼロで今までと同じ）。一覧は docs/インストールガイド.md の 12
function serverSettings(get) {
  const s = k => String(get(k) || '').trim();
  const n = k => { const v = get(k); return v === undefined || v === null || v === '' ? '' : +v; };  // 数の設定（0 も設定として使う：master.outHeight の 0＝4K のまま）
  return {
    local: { python: s('render.python'), ffmpegDir: s('render.ffmpegDir') },  // 描く python・ffmpeg のフォルダ（空なら探す。server/pyrender.js）
    analysisPython: s('analysis.python'), analysisModels: s('analysis.modelsDir'),
    voicevoxUrl: s('voicevox.url'), presetsDir: s('presetsDir'), python: s('tools.python'),
    codexPath: s('codex.path'), codexModel: s('codex.model'),  // 🎬 の絵（Codex CLI の場所・モデル。ジョブ係に環境変数で渡す）
    imageEngine: s('image.engine'), openaiImageModel: s('openai.imageModel'), openaiImageQuality: s('openai.imageQuality'),
    geminiImageModel: s('gemini.imageModel'), geminiImageSize: s('gemini.imageSize'),  // Nano Banana（Gemini）の絵のモデル・解像度（空なら tools/gemini_image_jobs.py の既定＝Nano Banana Pro・2K）  // 🎬 の絵の既定のエンジン・OpenAI のモデルと品質（鍵は資格情報マネージャー）
    blenderPath: s('blender.path'),
    cacheDir: s('cache.dir'),  // ためた絵などの置き場（空なら作品の work/。server/names.js の cacheRoot）  // Blender の 3D の blender.exe（描くプロセスに環境変数 MITTLER_BLENDER で渡す。空なら既定）
    bakeJobs: n('bake.jobs'),  // 裏で先に描く並列の数（空＝自動、0＝裏で描かない。server.js の bake）
    lang: s('language'),  // 画面の言葉（en・ja。既定 en）
    // 🏆 マスター書き出し（機能追加案03 v2）。空なら server/defaults.js の master
    master: { esrgan: s('master.esrgan'), esrganModel: s('master.esrganModel'), rife: s('master.rife'), scale: n('master.scale'), fps: n('master.fps'),
      outHeight: n('master.outHeight'), cacheGb: n('master.cacheGb') },
  };
}
// 設定を読む：mittler.<key>。人が書いていなければ古い名前 claudeCut.<key>（古い名前の互換。両方書いてあれば新しいほう。決まりは server/names.js の pickSetting）
const settingsNow = () => {
  const n = vscode.workspace.getConfiguration(NAMES.SETTINGS), o = vscode.workspace.getConfiguration(NAMES.OLD_SETTINGS);
  const r = serverSettings(k => NAMES.pickSetting(n.inspect(k), o.inspect(k)));
  // 言葉は、人が書いたときだけ「決めた言葉」（編集画面はそれに従う）。書いていなければ既定（編集画面が覚えた言葉があればそれ）
  const li = n.inspect('language'); r.langExplicit = !!(li && ['workspaceFolderValue', 'workspaceValue', 'globalValue'].some(k => li[k] !== undefined));
  return r;
};
// 画面の言葉（拡張が出す知らせ用）：mittler.language（en・ja。既定 en）
const langNow = () => { try { return I18N.norm(vscode.workspace.getConfiguration(NAMES.SETTINGS).get('language')); } catch (e) { return I18N.DEFAULT_LANG; } };
const $t = (k, v) => I18N.tr(langNow(), k, v);
// 編集画面で言葉を切り替えたら、ユーザー設定 mittler.language に書く（PC ごとの設定。作品には書かない）
const saveLanguage = l => vscode.workspace.getConfiguration(NAMES.SETTINGS).update('language', I18N.norm(l), vscode.ConfigurationTarget.Global);
// 🎵 suno.com の曲のページを、ユーザーの既定のブラウザ（VS Code の外）で開く。URL の形（https://suno.com/song/<id> だけ）はサーバー（server/music.js）が確かめてから呼ぶ。
// VS Code は信頼していないドメインなら「外のサイトを開くか」をユーザーに聞く
const openExternal = url => vscode.env.openExternal(vscode.Uri.parse(url, true));

// Workspace Trust：信頼していないフォルダでは動かない（package.json の capabilities.untrustedWorkspaces.supported=false で VS Code が拡張を止める。これは念のため）。
// 作品を開くと作品の effects/*.py とタイムラインの python が実行されるため
async function acquire(ctx, file) {
  if (vscode.workspace.isTrusted === false) throw new Error($t('ext.untrusted'));
  let e = servers.get(file);
  if (!e) {
    // 先に表に入れる（サーバーの起動を待つあいだに同じタイムラインをもう 1 つ開かれても、サーバーを 2 つ起動しない。前は 2 つ起動して 1 つが残った）
    e = { server: null, ready: null, refs: 0 }; servers.set(file, e);
    // エフェクトのコードは VS Code の横の列で開く（編集画面の「コードを開く」）
    const openFile = f => vscode.window.showTextDocument(vscode.Uri.file(f), { viewColumn: vscode.ViewColumn.Beside, preview: false });
    // ✏️ 書き込みを渡したとき：横の Claude Code の入力欄にフォーカス（公式拡張のコマンド。無ければ何もしない）
    const focusClaude = async () => {
      const cmds = await vscode.commands.getCommands(true);
      if (!cmds.includes('claude-vscode.focus')) return false;
      await vscode.commands.executeCommand('claude-vscode.focus'); return true;
    };
    // 書き出し先を開く：エクスプローラー（OS のファイルの窓）で、そのファイルを選んだ状態に（フォルダならそのフォルダ）
    const revealFile = f => vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(f));
    // 🆕 編集画面の「新規」ボタン（editor/newproject.js → サーバーの /api/new_project）：フォルダ選びと、作ったタイムラインを開くのは VS Code の役目
    e.ready = Promise.resolve().then(() => start(Object.assign({ timeline: file, openFile, focusClaude, revealFile, openExternal, pickFolder: pickParentFolder, openProject: openCreated, saveLanguage }, settingsNow())))
      .then(s => { e.server = s; return s; }, err => { if (servers.get(file) === e) servers.delete(file); throw err; });
  }
  e.refs++;
  try { return await e.ready; } catch (err) { e.refs--; throw err; }
}
// ---- 新しい作品（コマンド「Mittler: 新しい作品を作る」と、編集画面の「新規」ボタンが同じものを使う。作るのはどちらも tools/new_project.js の create()）----
// この拡張の package.json が言っているカスタムエディタの ID（activate で入れる。新しい作品を作ったあと、その ID で開く）
let viewType = 'mittler.timeline';
// 置く場所（親のフォルダ）を選ぶ。選ばなければ ''
async function pickParentFolder(start) {
  const o = { canSelectFolders: true, canSelectFiles: false, canSelectMany: false, openLabel: $t('ext.pick.label'), title: $t('ext.pick.title') };
  if (start) { try { o.defaultUri = vscode.Uri.file(start); } catch (e) { } }
  const r = await vscode.window.showOpenDialog(o);
  return r && r.length ? r[0].fsPath : '';
}
// 作った作品（create() の返り値）のタイムラインを編集画面で開き、「フォルダを VS Code で開く」を聞く（聞くのは待たない：編集画面の窓を止めないように）
async function openCreated(r) {
  await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(r.timeline), viewType);
  vscode.window.showInformationMessage($t('ext.created', { dir: r.dir, git: r.git }) + (r.notes.length ? $t('ext.notesSep') + r.notes.join($t('ext.notesSep')) : ''), $t('ext.openFolder'))
    .then(pick => { if (pick) return vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(r.dir), { forceNewWindow: true }); })
    .then(undefined, () => { });
}
function release(file) {
  const e = servers.get(file); if (!e) return;
  if (--e.refs <= 0) {
    servers.delete(file);
    if (e.server) e.server.close(); else e.ready.then(s => s.close(), () => { });  // 起動の途中で閉じられた：起動しきってから止める
  }
}
// エラーの画面に出す文字（HTML として読まれないように）
const escHtml = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// Webview の中身：編集画面（ローカルサーバーが配るページ）を iframe で出す。
// テーマ：VS Code は Webview の <html> の style に --vscode-* の変数（色・書体）を、<body> に vscode-dark／vscode-light／vscode-high-contrast… のクラスを付ける。
// iframe は別の文書で、その変数は届かないので、ここの小さなスクリプトが全部読んで iframe へ postMessage で渡す（受ける側は editor/ui.js。色は editor/editor.css のトークン）。
// 渡すのは：iframe が読めたとき・iframe が「ください」と言ったとき・テーマが変わったとき（<html> の style か <body> の class が変わる）。
// 地の色も VS Code のテーマの色（前は #16171b の決め打ちで、ライトのテーマだと開く瞬間に黒く光った）
function html(src, origin, nonce) {
  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src ${origin}; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>html,body{margin:0;padding:0;height:100%;overflow:hidden;background:var(--vscode-editor-background)}iframe{border:0;width:100%;height:100vh;display:block}</style></head>
<body><iframe id="mittlerFrame" src="${src}" allow="autoplay; clipboard-read; clipboard-write"></iframe>
<script nonce="${nonce}">(function () {
  var f = document.getElementById('mittlerFrame'), origin = ${JSON.stringify(origin)};
  function send() {
    var st = document.documentElement.style, vars = {}, i, k;
    for (i = 0; i < st.length; i++) { k = st[i]; if (k.indexOf('--vscode-') === 0) vars[k] = st.getPropertyValue(k).trim(); }
    try { f.contentWindow.postMessage({ type: 'mittler-theme', kind: document.body.className, vars: vars }, origin); } catch (e) { }
  }
  f.addEventListener('load', send);
  window.addEventListener('message', function (e) { if (e.source === f.contentWindow && e.data && e.data.type === 'mittler-theme-please') send(); });
  new MutationObserver(send).observe(document.documentElement, { attributes: true, attributeFilter: ['style'] });
  new MutationObserver(send).observe(document.body, { attributes: true, attributeFilter: ['class'] });
})();</script></body></html>`;
}
const newNonce = () => require('crypto').randomBytes(16).toString('hex');

class TimelineEditor {
  constructor(ctx) { this.ctx = ctx; }
  async resolveCustomTextEditor(doc, panel) {
    const file = doc.uri.fsPath;
    panel.webview.options = { enableScripts: true };
    let srv;
    try { srv = await acquire(this.ctx, file); }
    catch (err) { panel.webview.html = `<body style="font-family:var(--vscode-font-family,sans-serif);font-size:var(--vscode-font-size,13px);color:var(--vscode-errorForeground,#f48771);background:var(--vscode-editor-background,#1f1f1f);padding:20px;line-height:1.6">${escHtml(I18N.errText(langNow(), err))}</body>`; return; }
    const ext = await vscode.env.asExternalUri(vscode.Uri.parse(srv.url));
    const origin = `${ext.scheme}://${ext.authority}`;
    panel.webview.html = html(ext.toString(true), origin, newNonce());
    panel.onDidDispose(() => release(file));
    lastUrl = srv.url;
    hintSetup(srv);
  }
}
let lastUrl = '';

// 拡張の ID の頭：新しい名前 mittler と、古い名前 claudeCut（古い名前の互換）。
// 古いほうでも登録するのは、前の名前で入れた拡張（sa-san10.claude-cut。入口 loader.js がこのファイルを読む）を入れ替える前に、リポジトリだけ新しくなったときのため：
// VS Code が知っているのは入れてある拡張の package.json の ID（claudeCut.timeline・claudeCut.*）なので、その ID で登録しておかないと *.cut.json が開かなくなる。
// 新しい拡張（sa-san10.mittler）だけが入っていれば、古い ID の登録はどこからも呼ばれない。入れ替えが済んだら外してよい（docs/インストールガイド.md の 13）。
const ID_PREFIXES = [NAMES.SETTINGS, NAMES.OLD_SETTINGS];  // 'mittler'・'claudeCut'

// 「Mittler: 初期設定」（extension_setup.js）に渡すもの：言葉・PC の設定・拡張の保存場所（globalStorage。描く python の venv を作る所）・設定を書く口
function setupEnv(ctx) {
  const storage = ctx.globalStorageUri ? ctx.globalStorageUri.fsPath : ctx.globalStoragePath;
  return { $t, lang: langNow(), settings: settingsNow(), storage,
    setRenderPython: v => vscode.workspace.getConfiguration(NAMES.SETTINGS).update('render.python', v, vscode.ConfigurationTarget.Global) };
}
// 作品を開いて、描く python が見つからない（設定の python が使えない）とき：「Mittler: 初期設定」へ案内する（このウィンドウで 1 回だけ）
let setupHinted = false;
function hintSetup(srv) {
  if (setupHinted || !srv || !srv.renderReady) return;
  srv.renderReady.then(key => {
    if (setupHinted || !key || !/^srv\.py\./.test(key)) return;
    setupHinted = true;
    vscode.window.showWarningMessage($t('ext.setup.noRender'), $t('ext.setup.btnSetup'))
      .then(pick => { if (pick) return vscode.commands.executeCommand(NAMES.SETTINGS + '.setup'); }).then(undefined, () => { });
  }, () => { });
}

function activate(ctx) {
  // この拡張の package.json が言っているカスタムエディタの ID（新しい作品を作ったあと、その ID で開く）
  try { viewType = ctx.extension.packageJSON.contributes.customEditors[0].viewType || viewType; } catch (e) { }
  // 1つずつ登録する（前の拡張と新しい拡張が両方入っていると activate が2回呼ばれ、同じ ID の2回目の登録は断られる。断られても、ほかの登録は続ける）
  const reg = make => { try { ctx.subscriptions.push(make()); } catch (e) { console.error('[mittler] 登録できない：', e.message || e); } };
  const commands = {
    openInBrowserUrl: async () => {
      if (!lastUrl) return vscode.window.showInformationMessage($t('ext.noUrl'));
      await vscode.env.clipboard.writeText(lastUrl); vscode.window.showInformationMessage($t('ext.urlCopied', { url: lastUrl }));
    },
    // 新しい作品：置き場所（親のフォルダ）→ 作品フォルダの名前 → 表示名 → tools/new_project.js で作って、タイムラインを開く（ひな形の名前は mittler.language の言葉）
    newProject: async () => {
      const parent = await pickParentFolder(''); if (!parent) return;
      const id = await vscode.window.showInputBox({ title: $t('ext.np.idTitle'), prompt: $t('ext.np.idPrompt'), ignoreFocusOut: true,
        validateInput: v => /^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(v || '') ? null : $t('ext.np.idBad') });
      if (!id) return;
      const title = await vscode.window.showInputBox({ title: $t('ext.np.titleTitle'), prompt: $t('ext.np.titlePrompt'), value: id, ignoreFocusOut: true });
      if (title === undefined) return;
      let r;
      try { r = require('./tools/new_project').create({ dir: path.join(parent, id), title, lang: langNow() }); }
      catch (err) { return vscode.window.showErrorMessage($t('ext.np.fail', { err: I18N.errText(langNow(), err) })); }
      await openCreated(r);
    },
    reopenAsText: async () => {
      const tab = vscode.window.tabGroups.activeTabGroup.activeTab; const uri = tab && tab.input && tab.input.uri;
      if (uri) await vscode.commands.executeCommand('vscode.openWith', uri, 'default');
    },
    // 初期設定（extension_setup.js）：確かめて、足りない描く python は押したときだけ拡張の保存場所（globalStorage）に入れる
    setup: () => require('./extension_setup').setup(setupEnv(ctx)),
  };
  for (const pre of ID_PREFIXES) {
    reg(() => vscode.window.registerCustomEditorProvider(pre + '.timeline', new TimelineEditor(ctx), { webviewOptions: { retainContextWhenHidden: true } }));
    for (const [name, fn] of Object.entries(commands)) reg(() => vscode.commands.registerCommand(pre + '.' + name, fn));
  }
  // 入れた直後（この版で初めて起きたとき）の 1 回の知らせ：足りなければ「初期設定」へ、足りていれば歓迎（extension_setup.js の firstRun）。待たない（起動を遅くしない）
  firstRunPromise = firstRun(ctx);
}
let firstRunPromise = null;
function firstRun(ctx) {
  if (!ctx.globalState || !ctx.extension || !ctx.extension.packageJSON) return Promise.resolve({ shown: '' });
  const env = Object.assign(setupEnv(ctx), { state: ctx.globalState, version: String(ctx.extension.packageJSON.version || ''),
    commands: { setup: NAMES.SETTINGS + '.setup', newProject: NAMES.SETTINGS + '.newProject' } });
  return require('./extension_setup').firstRun(env).catch(e => { console.error('[mittler] 入れた直後の知らせ：', e && e.message || e); return { shown: '', error: String(e) }; });
}
function deactivate() { for (const e of servers.values()) { if (e.server) e.server.close(); else if (e.ready) e.ready.then(s => s.close(), () => { }); } servers.clear(); }

module.exports = { activate, deactivate, serverSettings, settingsNow, openExternal, html, setupEnv, hintSetup, firstRun: ctx => firstRun(ctx), lastFirstRun: () => firstRunPromise };  // firstRun・lastFirstRun：入れた直後の知らせの確かめ用（tools/smoke_package.py）  // setupEnv・hintSetup：初期設定の確かめ用（tools/smoke_package.py）  // html：Webview の中身（テーマを iframe に渡す所の確かめ用。tools/smoke_ui.py）  // serverSettings・settingsNow・openExternal は確かめ用（設定の名前 → サーバーのオプション、古い名前の設定の読み方（tools/smoke_compat.py）、開く口）
