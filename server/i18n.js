// Mittler の画面の言葉（英語・日本語）を、サーバー（Node）と拡張から引く。辞書の正本は editor/i18n/en.json・ja.json（1 か所。編集画面も Python も同じものを読む）。
//   const I18N = require('./i18n'); I18N.tr('ja', 'srv.export.busy', { n: 2 })
// 鍵が無ければ、もう片方の言葉 → 鍵そのもの。値の {名前} を vars で埋める。値が {one, other} なら vars.n が 1 のとき one（英語の単数・複数）。
'use strict';
const fs = require('fs');
const path = require('path');

const DIR = path.join(__dirname, '..', 'editor', 'i18n');
const LANGS = ['en', 'ja'];
const DEFAULT_LANG = 'en';  // 既定は英語
let dicts = null;
function load() {
  if (dicts) return dicts;
  dicts = {};
  for (const l of LANGS) { try { dicts[l] = JSON.parse(fs.readFileSync(path.join(DIR, l + '.json'), 'utf8')); } catch (e) { dicts[l] = {}; } }
  return dicts;
}
const norm = l => (LANGS.includes(String(l || '').toLowerCase()) ? String(l).toLowerCase() : DEFAULT_LANG);
// 値の中の { k: 鍵, v: 値 }（入れ子の鍵。L(…) で作る）は、同じ言葉で訳して埋める（例外の文を、あとで別の言葉で作り直せるように）
function fill(v, vars, lang) {
  if (v && typeof v === 'object') v = (vars && +vars.n === 1 && v.one != null) ? v.one : v.other;
  const val = x => (x && typeof x === 'object' && x.lazy) ? tr(lang, x.k, x.v) : String(x);
  // 渡された値が null（シグナルで止まったプロセスの終わりの番号など）なら、前の文と同じく 'null'・undefined なら空と出す（{code} のまま出さない）
  // 辞書のアイコンの印 {icon:名前}（編集画面がアイコンにする。editor/ui.js）は、サーバー・拡張の文（VS Code の知らせ・ログ・ツールチップ）では出せないので外す
  return String(v).replace(/\{icon:[a-z0-9-]+\} ?/g, '').replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? (vars[k] != null ? val(vars[k]) : vars[k] === null ? 'null' : '') : m));
}
function tr(lang, key, vars) {
  const d = load(), l = norm(lang), o = l === 'ja' ? 'en' : 'ja';
  const v = d[l][key] != null ? d[l][key] : d[o][key] != null ? d[o][key] : key;
  return fill(v, vars, l);
}
// 入れ子の鍵（keyedError の値に使う）。そのまま文字にすると日本語（ログ・コマンドラインの道具の出力は日本語のまま）
const L = (k, v) => ({ k, v, lazy: true, toString() { return tr('ja', k, v); } });
// 例外に鍵を持たせる：メッセージは日本語のまま（コマンドラインの道具の出力は日本語のまま）、画面は err.key・err.vars で訳す
function keyedError(key, vars) { const e = new Error(tr('ja', key, vars)); e.key = key; e.vars = vars || {}; return e; }
// 例外を今の言葉の文に（鍵があれば訳す。無ければ生の文のまま）
const errText = (lang, e) => (e && e.key ? tr(lang, e.key, e.vars) : String((e && e.message) || e));

module.exports = { tr, load, norm, LANGS, DEFAULT_LANG, keyedError, errText, L };
