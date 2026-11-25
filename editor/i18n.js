// Mittler 編集画面の言葉（英語・日本語を切り替えられる。既定は英語）。
// index.html でいちばん先に読む。辞書の正本は editor/i18n/en.json・ja.json（サーバー server/i18n.js・エンジン pyengine/mittler/i18n.py も同じものを読む）。
//
//   $t('bar.export')                 … 今の言葉の文
//   $t('cut.nsel', { n: 3 })          … {名前} を埋める。値が {one, other} なら n が 1 のとき one（英語の単数・複数）
//   $L('st.saved')                    … あとで訳す文（setStatus・MITTLER_NOTIFY に渡すと、言葉を切り替えたときに訳し直す）
//   <b data-i18n="tab.clip"></b>      … index.html の決まった文（data-i18n-title・-ph・-aria も）。切り替えたら入れ直す
//   MITTLER_I18N.onChange(fn)         … 言葉を切り替えたら呼ぶ（右の欄・タイムライン・窓を作り直す）
//
// 今の言葉の決め方（上が勝つ）：URL の &lang=ja|en（確かめ用）→ PC の設定（VS Code の mittler.language・単体は --lang。サーバーが /api/lang で返す）
// → このブラウザに覚えたもの（localStorage）→ 英語。編集画面で切り替えたら、サーバーに伝える（VS Code の中なら拡張がユーザー設定 mittler.language に書く）。
// 作品（タイムライン）・.mittler/state.json には書かない（言葉は作品のものではなく、使う人のもの）。
'use strict';
(() => {
  const LANGS = ['en', 'ja'];
  const NAMES = { en: 'EN', ja: '日本語' };  // 切り替えの文字（どちらの言葉でも同じ：その言葉の名前はその言葉で書く）
  const qs = new URLSearchParams(location.search);
  const TOKEN = qs.get('token') || '';
  const get = (url, sync) => { const x = new XMLHttpRequest(); x.open('GET', url, false); try { x.send(); return x.status === 200 ? JSON.parse(x.responseText) : null; } catch (e) { return null; } };
  // 辞書は始めに両方読む（片方に無い鍵は、もう片方で出す。画面を描く前に要るので同期で読む）
  const D = {}; for (const l of LANGS) D[l] = get('i18n/' + l + '.json') || {};
  const store = { get() { try { return localStorage.getItem('mittler.lang'); } catch (e) { return null; } }, set(v) { try { localStorage.setItem('mittler.lang', v); } catch (e) { } } };
  const srv = get('/api/lang') || {};  // { lang, source: 'setting'（VS Code の設定・--lang）| 'default' }
  const urlLang = LANGS.includes(qs.get('lang')) ? qs.get('lang') : null;
  let lang = urlLang || (srv.source === 'setting' && LANGS.includes(srv.lang) ? srv.lang : null) || (LANGS.includes(store.get()) ? store.get() : null) || (LANGS.includes(srv.lang) ? srv.lang : 'en');

  function fill(v, vars) {
    if (v && typeof v === 'object') v = (vars && +vars.n === 1 && v.one != null) ? v.one : v.other;
    return String(v).replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? (vars[k] === undefined ? '' : String(vars[k])) : m));  // null は 'null'・undefined は空（{code} のまま出さない）
  }
  function $t(key, vars) {
    const o = lang === 'ja' ? 'en' : 'ja';
    const v = D[lang][key] != null ? D[lang][key] : D[o][key] != null ? D[o][key] : key;
    return fill(v, vars);
  }
  // あとで訳す文：文字列のように使える（String(x)・`${x}`）。鍵と値を持っているので、切り替えたら訳し直せる
  const $L = (key, vars) => ({ k: key, v: vars, toString() { return $t(key, vars); } });
  // あとで訳す文をつないだもの（$L・文字列を順につなぐ。鍵は最初の $L のもの）。語順が変わらない「文のあとに文」だけに使う（文の中の差し込みは $L の値で）
  const $LJ = (...parts) => ({ k: ((parts.find(p => p && p.k) || {}).k) || '', toString() { return parts.map(p => (p == null ? '' : String(p))).join(''); } });

  // index.html の決まった文：data-i18n（文字）・data-i18n-title・data-i18n-ph（placeholder）・data-i18n-aria（aria-label）
  function applyStatic(rootEl) {
    const r = rootEl || document;
    for (const el of r.querySelectorAll('[data-i18n]')) el.textContent = $t(el.dataset.i18n);
    for (const el of r.querySelectorAll('[data-i18n-title]')) { el.title = $t(el.dataset.i18nTitle); if (el.dataset.tip != null) el.dataset.tip = el.title; }
    for (const el of r.querySelectorAll('[data-i18n-ph]')) el.placeholder = $t(el.dataset.i18nPh);
    for (const el of r.querySelectorAll('[data-i18n-aria]')) el.setAttribute('aria-label', $t(el.dataset.i18nAria));
  }
  const fns = [];
  function refreshSwitch() {
    for (const b of document.querySelectorAll('#langSel [data-lang]')) { const on = b.dataset.lang === lang; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false'); }
  }
  function setLang(l, opts) {
    if (!LANGS.includes(l) || l === lang) return;
    lang = l; document.documentElement.lang = l; store.set(l);
    applyStatic(); refreshSwitch();
    for (const fn of fns) { try { fn(l); } catch (e) { console.error('[mittler] 言葉の切り替え：', e); } }
    window.dispatchEvent(new Event('mittler-lang'));
    // サーバーに伝える（サーバーの返す文・ジョブの文がこの言葉に。VS Code の中では拡張がユーザー設定 mittler.language に書く）
    if (!(opts && opts.local)) { try { fetch('/api/lang', { method: 'POST', body: JSON.stringify({ lang: l }), headers: { 'Content-Type': 'application/json', 'X-Mittler-Token': TOKEN } }); } catch (e) { } }
  }
  document.documentElement.lang = lang;
  // 起動したときの言葉がサーバーの言葉と違えば（URL・このブラウザに覚えたもの）、サーバーにも伝える（サーバーが返す文をそろえる。設定には書かない）
  if (lang !== srv.lang && srv.lang) { try { fetch('/api/lang', { method: 'POST', body: JSON.stringify({ lang, save: false }), headers: { 'Content-Type': 'application/json', 'X-Mittler-Token': TOKEN } }); } catch (e) { } }

  // 上のバーの切り替え（index.html の #langSel）
  function initSwitch() {
    const box = document.getElementById('langSel'); if (!box) return;
    box.innerHTML = LANGS.map(l => `<button data-lang="${l}" lang="${l}">${NAMES[l]}</button>`).join('');
    box.addEventListener('click', e => { const b = e.target.closest('[data-lang]'); if (b) setLang(b.dataset.lang); });
    refreshSwitch();
  }
  const ready = () => { applyStatic(); initSwitch(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();

  window.$t = $t; window.$L = $L; window.$LJ = $LJ;
  window.MITTLER_I18N = { get lang() { return lang; }, set: setLang, t: $t, L: $L, LJ: $LJ, onChange: fn => fns.push(fn), apply: applyStatic, dicts: D, LANGS };
})();
