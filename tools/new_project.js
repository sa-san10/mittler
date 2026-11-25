// Mittler：新しい作品フォルダを作る（templates/project の中身＋最初のエフェクト＋空のフォルダ＋git）。Node の標準だけ。
//   node tools/new_project.js <作品フォルダ> [--title 表示名] [--width 1920] [--height 1080] [--fps 30] [--duration 60] [--lang en|ja] [--no-git] [--json]
//   （幅・高さは偶数の整数、fps・長さは正の数。--json：結果を 1 行の JSON で出す）
//   --lang：ひな形のトラック・メタデータの段の名前の言葉（既定は英語。編集画面の「＋ 新規」は画面の言葉を渡す）。CLAUDE.md・README.md は日本語のまま
//   このPC（Node なし）：tools\mittler.cmd node tools\new_project.js …
// 作品フォルダは、無いか空のときだけ作る（中身があれば何もしない）。名前は英数字と - _ だけ（日本語などのパスで道具が壊れないように）。
// 「空」：VS Code・Claude Code が開いたときに自分で作るもの（.claude/・.vscode/・desktop.ini・Thumbs.db）だけなら空とみなす
//   （VS Code で空のフォルダを開いて Claude Code に「Mittler で新しい作品を始めたい」と頼む流れ。.claude/settings.json があればフックを足す）。
// VS Code のコマンド「Mittler: 新しい作品を作る」も、この create() を呼ぶ。
'use strict';
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const I18N = require('../server/i18n');  // ひな形の名前（tpl.<トラックの id>）・断る理由（np.*）の言葉
const NAMES = require('../server/names');

const ROOT = path.resolve(__dirname, '..');
// Claude Code のフック（作品の .claude/settings.json の UserPromptSubmit）。絶対パスを書かない形（2026-11-13 パッケージ化）：
// python が環境変数 CLAUDE_PROJECT_DIR（Claude Code がフックに渡す作品の場所。無ければ今のフォルダ）から上にたどって、状態フォルダの中継
// .mittler/hook.py（前からの作品は .claude-cut/hook.py）を探して動かす。無ければ何もしない（まだ編集画面で開いていない作品でも、話しかけるのを止めない）。
// シェルの変数（$CLAUDE_PROJECT_DIR・%CLAUDE_PROJECT_DIR%）を使わないのは、フックを動かすシェルが PC で違う（Git Bash・cmd・PowerShell）ため：
// claude -p で試した PC（Git Bash）では $… は展開され %…% は展開されなかった。python の中で環境変数を読めば、どのシェルでも同じ
const HOOK_CMD = 'python -c "import os,runpy,pathlib as P;d=P.Path(os.environ.get(\'CLAUDE_PROJECT_DIR\') or \'.\').resolve();' +
  'h=[x/s/\'hook.py\' for x in [d,*d.parents] for s in (\'.mittler\',\'.claude-cut\') if (x/s/\'hook.py\').is_file()];' +
  'h and runpy.run_path(str(h[0]),run_name=\'__main__\')"';
// Mittler のフックか（今の書き方・前の絶対パスの mittler_state.py・古い名前の cc_state.py。cc_state.py＝古い名前の互換）
const isHook = cmd => /mittler_state\.py|cc_state\.py|\.mittler'.{0,80}hook\.py/.test(String(cmd || ''));
const TEMPLATE = path.join(ROOT, 'templates', 'project');
const FIRST_EFFECTS = ['subtitle', 'sprite', 'fade', 'grade'];  // effects_lib/common から写す
const ASSET_DIRS = ['images', 'videos', 'sfx', 'bgm', 'music', 'voice', 'fonts', 'characters', 'overlays'];  // music：🎵 Suno の曲（採用したテイクの音・サイドカー）
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;

const today = () => { const d = new Date(), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; };

// o: { dir, title, width, height, fps, duration, git（既定 true）, lang（'en'・'ja'。既定 'en'） } → { dir, timeline, files, git, notes }
// 断る理由は鍵つきの例外（メッセージは日本語。サーバーは画面の言葉に直して返す）
function create(o) {
  const lang = I18N.norm(o.lang), KE = I18N.keyedError;
  const dir = path.resolve(o.dir), id = path.basename(dir);
  if (!ID_RE.test(id)) throw KE('np.err.id', { id });
  const IGNORE = new Set(['.claude', '.vscode', 'desktop.ini', 'Thumbs.db', '.DS_Store']);
  const others = fs.existsSync(dir) ? fs.readdirSync(dir).filter(n => !IGNORE.has(n)) : [];
  if (others.length) throw KE('np.err.notEmpty', { dir, list: others.slice(0, 5).join('、') + (others.length > 5 ? ' …' : '') });
  // 大きさ・fps・長さ：作る前に確かめる（前は --width abc が width: null になり、奇数の大きさは書き出しのときに分かりにくいエラーで落ちた）
  const nums = {};
  for (const k of ['width', 'height', 'fps', 'duration']) {
    if (o[k] == null || o[k] === '') continue;
    const v = +o[k];
    if (!isFinite(v) || v <= 0) throw KE('np.err.positive', { k, v: o[k] });
    if ((k === 'width' || k === 'height') && (!Number.isInteger(v) || v % 2)) throw KE('np.err.even', { k, v: o[k] });
    nums[k] = v;
  }
  const title = o.title || id, date = today();
  const timelineName = `${id}.cut.json`;
  // 作品のファイルには Mittler の場所（絶対パス）を書かない（2026-11-13 パッケージ化。配布版の拡張は置き場に版の番号が入り、更新で変わる・作品をほかの PC に写すと合わない）。
  // PC ごとのもの（Mittler の場所・AI 用ガイドの写し・中継）は状態フォルダ .mittler/ に書く（server/project_env.js。作品を開くたびに書き直す）
  const vars = { TITLE: title, ID: id, DATE: date, TIMELINE: timelineName };
  const fill = s => s.replace(/\{\{(\w+)\}\}/g, (m, k) => (k in vars ? vars[k] : m));
  const files = [];
  const put = (rel, text) => { const f = path.join(dir, rel); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, text, 'utf8'); files.push(rel.split(path.sep).join('/')); };

  fs.mkdirSync(dir, { recursive: true });
  // タイムライン：テンプレート（そのまま読める空の cut.json）に値を入れる
  const tl = JSON.parse(fs.readFileSync(path.join(TEMPLATE, 'project.cut.json'), 'utf8'));
  tl.name = title;
  // トラック・メタデータの段の名前：作る言葉で（辞書の tpl.<id>。無い id はひな形のまま）。日本語はひな形と同じ
  const tpl = k => { const d = I18N.load(); return d[lang] && d[lang][k] != null ? I18N.tr(lang, k) : null; };
  for (const x of [...(tl.tracks || []), ...(tl.meta || [])]) { const n = tpl('tpl.' + x.id); if (n != null) x.name = n; }
  Object.assign(tl, nums);
  tl.created = date;
  put(timelineName, JSON.stringify(tl, null, 1) + '\n');
  put('characters.json', fs.readFileSync(path.join(TEMPLATE, 'characters.json'), 'utf8'));
  put('pronunciation.json', fs.readFileSync(path.join(TEMPLATE, 'pronunciation.json'), 'utf8'));  // 読み辞書（Gemini TTS。足すのはユーザーが言ったときだけ）
  put('.gitignore', fs.readFileSync(path.join(TEMPLATE, 'gitignore.txt'), 'utf8'));
  for (const n of ['AGENTS.md', 'CLAUDE.md', 'README.md']) put(n, fill(fs.readFileSync(path.join(TEMPLATE, n), 'utf8')));  // AGENTS.md が本文、CLAUDE.md はそれを読み込む入口
  // Claude Code のフック：話しかけるたびに、編集画面の今（選んでいるもの・時刻）を Claude にそえる（状態フォルダの中継 .mittler/hook.py → Mittler の tools/mittler_state.py）。
  // 書き方は HOOK_CMD（絶対パスなし。下の説明）。.claude/settings.json がもうあれば（Claude Code で開いていたフォルダ）、ほかの設定は残してフックだけ足す
  const hookCmd = HOOK_CMD, sp = path.join(dir, '.claude', 'settings.json');
  let st = {}; try { st = JSON.parse(fs.readFileSync(sp, 'utf8')); } catch (e) { st = {}; }
  st.hooks = st.hooks || {}; st.hooks.UserPromptSubmit = st.hooks.UserPromptSubmit || [];
  let had = false;  // もうこのフックがあれば（前の絶対パス・相対パス・書きまちがい・古い名前の cc_state.py）、今の書き方に書き直す
  for (const g of st.hooks.UserPromptSubmit) for (const h of g.hooks || []) if (isHook(h.command)) { h.command = hookCmd; had = true; }
  if (!had) st.hooks.UserPromptSubmit.push({ hooks: [{ type: 'command', command: hookCmd }] });
  put(path.join('.claude', 'settings.json'), JSON.stringify(st, null, 2) + '\n');
  for (const n of FIRST_EFFECTS) put(path.join('effects', n + '.py'), fs.readFileSync(path.join(ROOT, 'effects_lib', 'common', n + '.py'), 'utf8'));
  for (const d of ASSET_DIRS) fs.mkdirSync(path.join(dir, 'assets', d), { recursive: true });
  fs.mkdirSync(path.join(dir, 'work', 'proxy'), { recursive: true });
  fs.mkdirSync(path.join(dir, 'output'), { recursive: true });
  // 状態フォルダ .mittler/（git に入らない）に、この PC 用のファイル（env.json・guide.md・中継）を今すぐ書く：
  // 作ったあと、編集画面で開く前にエージェントが作業を始めても、ガイドと Mittler の場所が読めるように（開けばサーバーが書き直す）
  require('../server/project_env').write(dir, { stateName: NAMES.STATE_DIR, language: lang, by: 'new_project' });

  // git：作って最初のコミット（git が無い・名前が設定されていないときは、作るところまで）
  const notes = []; let git = 'skipped';
  if (o.git !== false) {
    const g = (...a) => execFileSync('git', ['-c', `safe.directory=${dir.split(path.sep).join('/')}`, ...a], { cwd: dir, stdio: 'pipe', windowsHide: true }).toString();
    try {
      g('init', '-q'); g('add', '-A'); git = 'init';
      try { g('commit', '-q', '-m', `新しい作品（Mittler の new_project で作成）：${title}`); git = 'committed'; }
      catch (e) { notes.push(I18N.tr(lang, 'np.note.noCommit')); }
    } catch (e) { notes.push(I18N.tr(lang, 'np.note.noGit', { err: String(e.message).split('\n')[0] })); }
  }
  return { dir, timeline: path.join(dir, timelineName), files, git, notes };
}

function main() {
  const args = process.argv.slice(2);
  const opt = n => { const i = args.indexOf('--' + n); return i >= 0 ? args[i + 1] : undefined; };
  const FLAGS = ['--no-git', '--json'];  // 値を取らないオプション（この後ろに作品フォルダを書いてもよい）
  const dir = args.find((a, i) => !a.startsWith('--') && (i === 0 || !args[i - 1].startsWith('--') || FLAGS.includes(args[i - 1])));
  if (!dir) { console.error('使い方: node tools/new_project.js <作品フォルダ> [--title 表示名] [--width W --height H --fps N --duration 秒] [--lang en|ja] [--no-git] [--json]'); process.exit(2); }
  try {
    const r = create({ dir, title: opt('title'), width: opt('width'), height: opt('height'), fps: opt('fps'), duration: opt('duration'), lang: opt('lang'), git: !args.includes('--no-git') });
    if (args.includes('--json')) { console.log(JSON.stringify(r)); return; }
    console.log(`作った: ${r.dir}`);
    for (const f of r.files) console.log('  ' + f);
    console.log('  assets/（images videos sfx bgm music voice fonts characters overlays）・work/proxy/・output/');
    console.log(`git: ${r.git}`); for (const n of r.notes) console.log('  ' + n);
    console.log(`次：VS Code で ${path.basename(r.timeline)} を開く。素材は assets/ に入れる。`);
  } catch (e) { console.error(e.message); process.exit(1); }
}

if (require.main === module) main();
module.exports = { create, HOOK_CMD, isHook };
