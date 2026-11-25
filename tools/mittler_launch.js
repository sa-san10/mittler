// tools/mittler.cmd の中身（VS Code の Node＝Electron as Node で動く）：mittler.cmd serve … → server/main.js、mittler.cmd node <スクリプト> … → そのスクリプト。
// 引数は mittler.cmd が %* のまま渡す（cmd.exe の中で引数を 1 つずつ数えない）。前は mittler.cmd が if "%~2"=="" で 1 つずつ集めていて、
// 空白の入った名前（--title "Kuro Coffee"）が bash から \" つきで届くと、cmd.exe が引用を読みちがえて落ちた（2026-11-14 使ってみた知らせ：
// `Coffee\""=="" was unexpected at this time.`）。今は分け方を Node（Windows の決まり）にまかせる。= , ; で分かれることも無くなった。
'use strict';
const path = require('path');
const Module = require('module');
const [mode, ...rest] = process.argv.slice(2);
let script;
if (/^node$/i.test(mode || '') && rest.length && rest[0].startsWith('-')) {
  // Node のオプションから始まるもの（mittler.cmd node -e "…" など）：そのまま Node（この Code.exe）に渡して動かす（前の mittler.cmd と同じ）
  const r = require('child_process').spawnSync(process.execPath, rest, { stdio: 'inherit', env: process.env, windowsHide: true });
  process.exit(r.status == null ? 1 : r.status);
}
if (/^serve$/i.test(mode || '')) script = path.join(__dirname, '..', 'server', 'main.js');
else if (/^node$/i.test(mode || '') && rest.length) script = path.resolve(rest.shift());
else { console.log('usage: mittler.cmd serve <timeline.cut.json> [options] | mittler.cmd node <script.js> [args]'); process.exit(2); }
process.argv = [process.argv[0], script, ...rest];
Module.runMain();  // process.argv[1] をいちばん上のスクリプトとして動かす（require.main === module もそのまま効く）
