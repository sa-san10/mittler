// Mittler 編集画面の見た目の土台（2026-11-12）：テーマ・知らせ（トースト）・押せない理由・アイコン（2026-11-14。前の絵文字の代わり）。
// index.html でいちばん先に読む（editor.js より前）。色・書体・余白の決まりは editor.css の頭（デザイントークン）。
//
// テーマの届き方：
//   VS Code の中：拡張（extension.js）の Webview が、自分に届いている --vscode-* の変数を全部、中の iframe（この画面）へ postMessage で渡す
//     （iframe は別の文書なので、VS Code の変数はそのままでは届かない）。テーマを切り替えたときも同じ道で届く。
//   ブラウザで直に（tools\mittler.cmd serve の URL）：--vscode-* は無いので、editor.css が持っている自前のダーク／ライトに落ちる。
//     どちらにするかは OS・ブラウザの設定（prefers-color-scheme）。URL に &theme=light か &theme=dark を付けると決め打ちにできる（確かめ用）。
// テーマが変わったら window に 'mittler-theme' を出す（canvas に色を描いている所＝音ハメのグラフが描き直す）。
'use strict';
(() => {
  const root = document.documentElement;
  const q = new URLSearchParams(location.search).get('theme');
  if (q === 'light' || q === 'dark') root.dataset.theme = q;

  // ---- テーマ ----
  const VAR_OK = /^--vscode-[A-Za-z0-9-]+$/;
  const VAL_BAD = /url\s*\(|expression|[;{}<>]/i;  // 色・書体・大きさだけを通す（念のため。送ってくるのは自分の拡張の Webview だけ）
  let applied = [];
  function applyVscode(kind, vars) {
    for (const k of applied) root.style.removeProperty(k);
    applied = [];
    for (const [k, v] of Object.entries(vars || {})) {
      if (!VAR_OK.test(k) || typeof v !== 'string' || v.length > 300 || VAL_BAD.test(v)) continue;
      root.style.setProperty(k, v); applied.push(k);
    }
    // kind：vscode-light・vscode-dark・vscode-high-contrast・vscode-high-contrast-light（VS Code が body に付けるクラス）
    root.dataset.theme = /light/.test(kind || '') ? 'light' : 'dark';
    root.dataset.vscode = kind || '';
    root.classList.toggle('hc', /high-contrast/.test(kind || ''));
    announce();
  }
  window.addEventListener('message', e => {
    if (e.source !== window.parent || window.parent === window) return;  // 自分を入れている親（拡張の Webview）からだけ
    const d = e.data; if (!d || d.type !== 'mittler-theme') return;
    applyVscode(d.kind, d.vars);
  });
  const announce = () => { cache.clear(); window.dispatchEvent(new Event('mittler-theme')); };
  // 親（拡張の Webview）に「読めた。テーマをください」と伝える（Webview が先に送っていても、取りこぼさないように）
  if (window.parent !== window) { try { window.parent.postMessage({ type: 'mittler-theme-please' }, '*'); } catch (e) { } }
  try { matchMedia('(prefers-color-scheme: light)').addEventListener('change', announce); } catch (e) { }

  // CSS のトークン（--bg など）の今の値。canvas に描く色に使う
  const cache = new Map();
  function token(name, fallback) {
    if (cache.has(name)) return cache.get(name);
    const v = getComputedStyle(root).getPropertyValue(name).trim() || fallback || '';
    cache.set(name, v); return v;
  }
  window.MITTLER_THEME = { token, apply: applyVscode, isLight: () => (root.dataset.theme ? root.dataset.theme === 'light' : matchMedia('(prefers-color-scheme: light)').matches) };

  // ---- アイコン（2026-11-14。前の絵文字の代わり）：Lucide の線のアイコンを 1 色で（editor/icons/*.svg・editor.css の .ic）----
  // MITTLER_ICON('film') … アイコンの HTML（<i class="ic" data-ic="film">）。名前は Lucide の名前（editor.css の一覧にあるもの）
  // 辞書の文の中の {icon:名前} … 画面（DOM の文字）に出たところで、下の見張りがアイコンに置きかえる（$t が返す文は印のまま。
  //   innerHTML でも textContent でも同じ）。文字しか出せない所（title・placeholder・aria-label・選ぶ欄の項目）では印を外して言葉だけに
  //   （ツールチップ用の文には、はじめから印を書かない。これは書き忘れたときの安全のため）
  const escH = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const ICON = name => `<i class="ic" data-ic="${escH(name)}" aria-hidden="true"></i>`;
  window.MITTLER_ICON = ICON;
  const MARK = /\{icon:([a-z0-9-]+)\} ?/g, HAS = '{icon:';
  const stripIcons = s => String(s).replace(MARK, '');
  window.MITTLER_STRIP_ICONS = stripIcons;
  const TEXT_ONLY = new Set(['TEXTAREA', 'SCRIPT', 'STYLE', 'OPTION', 'TITLE']);
  function iconizeText(node) {
    const s = node.nodeValue; if (!s || s.indexOf(HAS) < 0) return;
    const par = node.parentNode; if (!par) return;
    if (TEXT_ONLY.has(par.nodeName)) { node.nodeValue = stripIcons(s); return; }
    const frag = document.createDocumentFragment(); let last = 0; MARK.lastIndex = 0; let m;
    while ((m = MARK.exec(s))) {
      if (m.index > last) frag.appendChild(document.createTextNode(s.slice(last, m.index)));
      const i = document.createElement('i'); i.className = 'ic'; i.dataset.ic = m[1]; i.setAttribute('aria-hidden', 'true'); frag.appendChild(i);
      // 印のあとの空白 1 つは、アイコンと字のあいだの空き（.ic の右の余白）に置きかえる
      if (m[0].endsWith(' ') && MARK.lastIndex < s.length) i.classList.add('sp');
      last = MARK.lastIndex;
    }
    if (last < s.length) frag.appendChild(document.createTextNode(s.slice(last)));
    par.replaceChild(frag, node);
  }
  const ATTRS = ['title', 'placeholder', 'aria-label'];
  function iconizeAttrs(el) {
    for (const a of ATTRS) { const v = el.getAttribute(a); if (v && v.indexOf(HAS) >= 0) el.setAttribute(a, stripIcons(v)); }
  }
  function iconizeTree(n) {
    if (n.nodeType === 3) { iconizeText(n); return; }
    if (n.nodeType !== 1) return;
    iconizeAttrs(n);
    if (n.textContent.indexOf(HAS) < 0 && !n.querySelector('[title*="{icon:"],[placeholder*="{icon:"],[aria-label*="{icon:"]')) return;
    for (const el of n.querySelectorAll('[title],[placeholder],[aria-label]')) iconizeAttrs(el);
    const w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT); const list = [];
    while (w.nextNode()) if (w.currentNode.nodeValue.indexOf(HAS) >= 0) list.push(w.currentNode);
    for (const t of list) iconizeText(t);
  }
  window.MITTLER_ICONIZE = iconizeTree;
  function watch() {
    iconizeTree(document.body);
    new MutationObserver(recs => {
      for (const r of recs) {
        if (r.type === 'childList') { for (const n of r.addedNodes) iconizeTree(n); }
        else if (r.type === 'characterData') iconizeText(r.target);
        else if (r.type === 'attributes') iconizeAttrs(r.target);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }
  if (document.body) watch(); else document.addEventListener('DOMContentLoaded', watch);

  // ---- 知らせ（右下のトースト）----
  // level：'ok'（緑。できた）・'info'（ふつう）・'warn'（黄。気をつける）・'bad'（赤。失敗）。
  // 失敗（bad）と warn は、押して閉じるまで消えない（上のバーの 1 行は次の知らせですぐ上書きされるので、失敗はここにも残す）。
  // opts.key：同じ鍵の知らせは 1 つだけ（中身を置きかえる。「保存できなかった…n 回目」が積み上がらない）。opts.ms：消えるまでのミリ秒（0＝消えない）。
  // opts.action：{ label, run }（知らせの中のボタン）。返り値：{ close() }
  // text・opts.action.label は文字列か、あとで訳す文（$L）。$L なら言葉を切り替えたときに訳し直す
  const keyed = new Map();
  function paintToast(t) {
    t.querySelector('.tbody').textContent = String(t._text);
    const c = t.querySelector('.tclose'); c.title = $t('ui.close'); c.setAttribute('aria-label', $t('ui.close'));
    const a = t.querySelector('.tact'); if (a && t._actLabel != null) a.textContent = String(t._actLabel);
    t.title = $t('ui.clickToClose');
  }
  function notify(text, level, opts) {
    level = level === true ? 'bad' : (level || 'ok'); opts = opts || {};
    let box = document.getElementById('mittlerToasts');
    if (!box) { box = document.createElement('div'); box.id = 'mittlerToasts'; box.setAttribute('role', 'status'); box.setAttribute('aria-live', 'polite'); document.body.appendChild(box); }
    let t = opts.key ? keyed.get(opts.key) : null;
    if (!t || !t.isConnected) {
      t = document.createElement('div'); box.appendChild(t);
      if (opts.key) keyed.set(opts.key, t);
    }
    clearTimeout(t._timer);
    t.className = 'mittlerToast ' + level; t.dataset.level = level;
    t.innerHTML = '<span class="tmark" aria-hidden="true"></span><span class="tbody"></span><button class="tclose">' + ICON('x') + '</button>';
    t._text = text; t._actLabel = opts.action ? opts.action.label : null;
    const close = () => { clearTimeout(t._timer); if (opts.key && keyed.get(opts.key) === t) keyed.delete(opts.key); t.remove(); };
    if (opts.action) {
      const b = document.createElement('button'); b.className = 'tact';
      b.onclick = ev => { ev.stopPropagation(); try { opts.action.run(); } finally { close(); } };
      t.querySelector('.tbody').after(b);
    }
    paintToast(t); t.onclick = close;
    const sticky = level === 'bad' || level === 'warn';
    const ms = opts.ms != null ? opts.ms : (sticky ? 0 : 9000);
    if (ms > 0) t._timer = setTimeout(close, ms);
    // たまりすぎないように：古いものから消す（失敗は 4 つまで残す）
    const all = [...box.children]; if (all.length > 6) all.slice(0, all.length - 6).forEach(x => x.remove());
    return { close, el: t };
  }
  notify.close = key => { const t = keyed.get(key); if (t) { keyed.delete(key); t.remove(); } };
  window.MITTLER_NOTIFY = notify;
  // 言葉を切り替えたら、出ている知らせも訳し直す（$L で渡したもの）
  if (window.MITTLER_I18N) MITTLER_I18N.onChange(() => { for (const t of document.querySelectorAll('#mittlerToasts .mittlerToast')) if (t._text != null) paintToast(t); });

  // 上のバーの 1 行（#status）の種類は、呼ぶ側が決めて渡す（editor.js の setStatus(文, 種類)）。
  // 前は文の言葉から決めていた（「できなかった」なら失敗…）。言葉を切り替えられるようにしたので、文から決めるのをやめた（2026-11-12）

  // ---- 押せないボタンに理由を出す：disabled のあいだだけ、title の頭に「押せない：理由」を付ける ----
  // （disabled のボタンは title のツールチップが出ない環境があるので、理由はマウスのそばの札にも出す：cutedit.js の whyTip）
  // reason は文字列か、あとで訳す文（$L）。ボタンの元のツールチップ（dataset.tip）は、決まった文なら data-i18n-title から入れ直される
  function setDisabled(btn, reason) {
    if (!btn) return;
    if (btn.dataset.tip == null) btn.dataset.tip = btn.title || '';
    btn.disabled = !!reason;
    btn.title = reason ? $t('ui.disabledWhy', { why: String(reason) }) + '\n' + btn.dataset.tip : btn.dataset.tip;
    if (reason) btn.dataset.why = String(reason); else delete btn.dataset.why;
  }
  window.MITTLER_SET_DISABLED = setDisabled;

  // ---- アイコンのボタンの中身：アイコン＋名前。名前は幅が狭いとたたむ（opt は先にたたむ）。editor.css の #bar .lb ----
  window.MITTLER_ICO = (icon, label, opt, tail) => `${ICON(icon)}<span class="lb${opt ? ' opt' : ''}">${escH(stripIcons(label))}</span>${tail ? ' ' + escH(tail) : ''}`;
})();
