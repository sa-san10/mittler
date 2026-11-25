// Mittler：作品の状態フォルダ（.mittler/。前からの作品は .claude-cut/）に、その PC 用のファイルを書く（2026-11-13 パッケージ化）。Node の標準だけ。
// 作品のファイル（AGENTS.md・CLAUDE.md・.claude/settings.json）に Mittler の絶対パスを書かないため、PC ごとに変わるものはここに置く
// （状態フォルダは git に入らない。作品を別の PC に写しても、拡張の版が上がって置き場が変わっても、開けば書き直される）：
//   env.json  … Mittler の場所・版・描く python・ffmpeg・Blender・言葉など（エージェントと道具が読む。鍵・トークンは入れない：トークンは server.json）
//   guide.md  … Mittler の AI 用ガイド（docs/スターターガイド（AI用）.md）の写し。作品の CLAUDE.md が `@.mittler/guide.md` で読み込む
//               （作品の中なので Claude Code の取り込みの許可が要らない。git に入らないファイルでも取り込まれることを claude -p で確かめた）
//   hook.py・api.py・engine.py … templates/state/ の中継（env.json の場所の tools/mittler_state.py・tools/mittler_api.py・`python -m mittler` を呼ぶ）
// 書くとき：拡張（サーバー）が作品を開いたとき（server.js の start。描く python が決まったらもう一度）と、新しい作品を作ったとき（tools/new_project.js）。
// 中身が同じなら書かない（ファイルの時刻を変えない）。書けなくても作品は開く（ログに出すだけ）。
'use strict';
const fs = require('fs');
const path = require('path');
const NAMES = require('./names');
const ATOMIC = require('./atomic');

const ROOT = path.resolve(__dirname, '..');
const GUIDE = path.join(ROOT, 'docs', 'スターターガイド（AI用）.md');
const RELAYS = ['hook.py', 'api.py', 'engine.py'];  // templates/state/ から写す中継

// この Mittler の版と、配布版（VSIX。tools/build_vsix.py が mittler_build.json を入れる）か開発版（リポジトリ）か
function about() {
  let version = '', kind = 'dev', commit = '';
  try { version = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8')).version || ''; } catch (e) { }
  try { const b = JSON.parse(fs.readFileSync(path.join(ROOT, 'mittler_build.json'), 'utf8')); kind = 'vsix'; commit = b.commit || ''; } catch (e) { }
  return { dir: ROOT, version, kind, commit };
}

// 中身が違うときだけ書く（一時ファイルに書いて置きかえ）
function put(file, text) {
  try { if (fs.readFileSync(file, 'utf8') === text) return false; } catch (e) { }
  ATOMIC.write(file, text, '.part');  // フックがちょうど読んでいる瞬間でも通るように（server/atomic.js）
  return true;
}

// project：作品のフォルダ。o：{ stateName（無ければ names.js の決まり）, renderPython, ffmpegDir, blender, language, by（'server'・'new_project'） }
// → { dir: 状態フォルダ, written: [書いたファイルの名前] }
function write(project, o = {}) {
  const stateName = o.stateName || NAMES.stateDirName(project);
  const dir = path.join(project, stateName);
  fs.mkdirSync(dir, { recursive: true });
  const a = about();
  const s = v => String(v || '');
  const env = {
    about: 'Mittler がこの PC 用に書くファイル（作品を開くたびに書き直す。直さない。git に入らない）。docs_dir・tools_dir・pyengine_dir は Mittler の中の場所',
    mittler_dir: a.dir, mittler_version: a.version, mittler_kind: a.kind,  // kind：vsix（配布版の拡張）・dev（リポジトリを読む開発版）
    docs_dir: path.join(a.dir, 'docs'), tools_dir: path.join(a.dir, 'tools'), pyengine_dir: path.join(a.dir, 'pyengine'),
    guide: `${stateName}/guide.md`, render_python: s(o.renderPython), ffmpeg_dir: s(o.ffmpegDir), cache_dir: s(process.env.MITTLER_CACHE_DIR), blender: s(o.blender), language: s(o.language),
    commands: {
      hook: `python ${stateName}/hook.py`,
      api: `python ${stateName}/api.py . <コマンド>`,
      engine: `python ${stateName}/engine.py stills <タイムライン> --at <秒> --out work/stills`,
    },
    written_by: s(o.by || 'server'),
  };
  if (a.commit) env.mittler_commit = a.commit;
  const written = [];
  if (put(path.join(dir, 'env.json'), JSON.stringify(env, null, 1) + '\n')) written.push('env.json');
  let guide = '';
  try { guide = fs.readFileSync(GUIDE, 'utf8'); } catch (e) { }
  if (guide) {
    const head = `<!-- Mittler ${a.version}（${a.kind}）の docs/スターターガイド（AI用）.md の写し。作品を開くたびに書き直す（直さない）。` +
      `この中の docs/・tools/・pyengine/ などは Mittler の場所（${stateName}/env.json の mittler_dir）から見た場所 -->\n`;
    if (put(path.join(dir, 'guide.md'), head + guide)) written.push('guide.md');
  }
  for (const n of RELAYS) {
    let t = ''; try { t = fs.readFileSync(path.join(ROOT, 'templates', 'state', n), 'utf8'); } catch (e) { continue; }
    if (put(path.join(dir, n), t)) written.push(n);
  }
  return { dir, written };
}

module.exports = { write, about, ROOT };
