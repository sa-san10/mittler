// Mittler：名前と、古い名前（claude-cut）の互換（JS 側の1か所。Python 側は pyengine/mittler/names.py）。Node の標準だけ（vscode は読まない：単体でも確かめられる）。
// 2026-11-12 に claude-cut を Mittler に改名した。**新しい名前が正**で、古い名前は「読める」だけ残してある（今までの作品と PC の設定を直さずに動かすため）。
// 古い名前を読むところは、ここと pyengine/mittler/names.py、古い名前の入口（pyengine/ccpy/・tools/cc.cmd・tools/cc_state.py・tools/cc_api.py）と
// package.json の claudeCut.*（deprecationMessage 付き）にまとめてある。互換を外すときは「古い名前の互換」の印が付いたところを消す。
// | もの | 新しい名前 | 古い名前（読むだけ） |
// | VS Code の設定 | mittler.* | claudeCut.*（pickSetting。両方あれば新しいほう） |
// | 環境変数 | MITTLER_<名前> | CC_<名前>（env。両方あれば新しいほう） |
// | 作品の中の状態フォルダ | .mittler/ | .claude-cut/（stateDirName。古い作品はそのまま .claude-cut/ を使う） |
// | HTTP のトークンのヘッダ | X-Mittler-Token | X-CC-Token（tokenOf。両方あれば新しいほう） |
// | タイムラインの format・engine | "mittler/py1"・"mittler" | "claude-cut/py1"・"ccpy"（formatOk。どちらも開く。中身は同じ形） |
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const SETTINGS = 'mittler', OLD_SETTINGS = 'claudeCut';            // VS Code の設定の頭（古い名前の互換：claudeCut.*）
const ENV_PREFIX = 'MITTLER_', OLD_ENV_PREFIX = 'CC_';              // 環境変数の頭（古い名前の互換：CC_*）
const STATE_DIR = '.mittler', OLD_STATE_DIR = '.claude-cut';        // 作品の中の状態フォルダ（古い名前の互換：.claude-cut/）
const TOKEN_HEADER = 'x-mittler-token', OLD_TOKEN_HEADER = 'x-cc-token';  // トークンのヘッダ（Node は小文字で渡す。古い名前の互換：X-CC-Token）
const FORMAT_PREFIX = 'mittler/py', OLD_FORMAT_PREFIX = 'claude-cut/py';  // タイムラインの format の頭（古い名前の互換：claude-cut/py…。新しく作る作品は mittler/py1）
const STATE_DIRS = [STATE_DIR, OLD_STATE_DIR];                      // どちらも /project/ で配らない・変更の見張りから外す

// 環境変数 MITTLER_<name>。無ければ（空も）古い名前 CC_<name>（古い名前の互換）。e は確かめ用（既定 process.env）
function env(name, e) {
  e = e || process.env;
  return e[ENV_PREFIX + name] || e[OLD_ENV_PREFIX + name] || '';
}

// 作品の状態フォルダの名前（server.json・state.json・current_frame.jpg・annotations・thumbs・waves などの置き場）。pyengine/mittler/names.py の state_dir_name と同じ決まり：
// .mittler/ があればそれ。無くて .claude-cut/ があれば .claude-cut（古い名前の互換：今までの作品のフック・CLAUDE.md がそこを読む）。
// どちらも無いとき（clone したばかりなど）は、作品の .gitignore に .claude-cut だけが書いてあれば .claude-cut（古い作品。.mittler/ を作ると git に見えてしまう）、ほかは .mittler
function stateDirName(project) {
  const isDir = d => { try { return fs.statSync(path.join(project, d)).isDirectory(); } catch (e) { return false; } };
  if (isDir(STATE_DIR)) return STATE_DIR;
  if (isDir(OLD_STATE_DIR)) return OLD_STATE_DIR;
  let lines = [];
  try { lines = fs.readFileSync(path.join(project, '.gitignore'), 'utf8').split(/\r?\n/).map(s => s.trim().replace(/^\/+|\/+$/g, '')); } catch (e) { }
  return lines.includes(OLD_STATE_DIR) && !lines.includes(STATE_DIR) ? OLD_STATE_DIR : STATE_DIR;
}

// タイムラインの format が読める形か：mittler/py… か、前の名前の claude-cut/py…（古い名前の互換。中身は同じ形）
function formatOk(format) {
  const f = String(format || '');
  return f.startsWith(FORMAT_PREFIX) || f.startsWith(OLD_FORMAT_PREFIX);
}

// 要求のヘッダからトークン：X-Mittler-Token。無ければ古い名前 X-CC-Token（古い名前の互換）
function tokenOf(headers) {
  return headers[TOKEN_HEADER] !== undefined ? headers[TOKEN_HEADER] : headers[OLD_TOKEN_HEADER];
}

// VS Code の設定1つの値：mittler.<key> を人が書いていればそれ。無ければ古い名前 claudeCut.<key> を人が書いていればそれ（古い名前の互換）。どちらも無ければ新しい名前の既定値。
// insNew・insOld は vscode の WorkspaceConfiguration.inspect(key) の返り値（{defaultValue, globalValue, workspaceValue, workspaceFolderValue}。無ければ undefined）。
// 「人が書いた」＝フォルダ → ワークスペース → ユーザー（Remote-SSH の接続先の設定もここ）の順で、最初に undefined でないもの（VS Code の強さの順と同じ）
function pickSetting(insNew, insOld) {
  const written = ins => { if (!ins) return undefined; for (const k of ['workspaceFolderValue', 'workspaceValue', 'globalValue']) if (ins[k] !== undefined) return ins[k]; return undefined; };
  const a = written(insNew); if (a !== undefined) return a;
  const b = written(insOld); if (b !== undefined) return b;
  return insNew ? insNew.defaultValue : undefined;
}

// 作り直せる大きなもの（コマの絵 cache/frames・マスターの中間 master・Blender の 3D の絵 3d）の置き場の根（2026-11-22）。pyengine/mittler/names.py の cache_root と同じ決まり：
// 環境変数 MITTLER_CACHE_DIR（PC の設定 mittler.cache.dir。server.js が入れる）が無ければ作品の work/。あれば <そこ>/<作品のフォルダの名前>-<作品の場所の印 8 字>/
function cacheRoot(project, e) {
  const base = env('CACHE_DIR', e);
  if (!base) return path.join(project, 'work');
  const full = path.resolve(project);
  const key = full.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
  const name = path.basename(full.replace(/[\\/]+$/, '')).replace(/[^A-Za-z0-9_.-]/g, '_') || 'project';
  const root = path.join(base, `${name}-${crypto.createHash('sha1').update(key, 'utf8').digest('hex').slice(0, 8)}`);
  const mark = path.join(root, '_project.txt');
  if (!fs.existsSync(mark)) { try { fs.mkdirSync(root, { recursive: true }); fs.writeFileSync(mark, full + '\n', 'utf8'); } catch (err) { } }
  return root;
}

module.exports = { SETTINGS, OLD_SETTINGS, ENV_PREFIX, OLD_ENV_PREFIX, STATE_DIR, OLD_STATE_DIR, STATE_DIRS, TOKEN_HEADER, OLD_TOKEN_HEADER, FORMAT_PREFIX, OLD_FORMAT_PREFIX, formatOk, env, stateDirName, tokenOf, pickSetting, cacheRoot };
