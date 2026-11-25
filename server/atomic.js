// Mittler：ファイルの置きかえ（一時ファイルに書いて rename）。外部依存なし（Node 標準だけ）。
// Windows では、置きかえ先をほかのプロセスが開いている瞬間は rename が EPERM・EBUSY・EACCES で失敗する。
// Python はファイルを「消してよい」の印なしで開くので、描画サーバー（コマごとにタイムラインを丸ごと読む）やジョブ係（ジョブのファイルを読む）が
// 読んでいる瞬間に当たると、保存が 500 になっていた（2026-11-12）。読むのは一瞬なので、短く待って数回やり直す。
'use strict';
const fs = require('fs');

const RETRY_CODES = new Set(['EPERM', 'EBUSY', 'EACCES']);
const sleepBuf = new Int32Array(new SharedArrayBuffer(4));
const sleepMs = ms => { Atomics.wait(sleepBuf, 0, 0, ms); };  // 同期で待つ（長くて合計 0.4 秒ほど。めったに起きない）

// tmp を dst に置きかえる。開かれていて失敗したら、少し待ってやり直す（tries 回まで。だめなら最後のエラーを投げる）
function replace(tmp, dst, tries = 12) {
  for (let i = 0; ; i++) {
    try { fs.renameSync(tmp, dst); return i; }
    catch (e) { if (!RETRY_CODES.has(e.code) || i >= tries - 1) throw e; sleepMs(10 + i * 5); }
  }
}

// data を dst に書く（<dst><suffix> に書いてから置きかえる。読む側が書きかけを見ないように）
function write(dst, data, suffix = '.tmp') {
  const tmp = dst + suffix;
  fs.writeFileSync(tmp, data);
  return replace(tmp, dst);
}

module.exports = { replace, write };
