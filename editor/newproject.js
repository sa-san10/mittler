// 新しい作品（プロジェクト）を作る：上のバーの「＋ 新規」ボタン → 小さな窓（置く場所・フォルダの名前・表示名・大きさ・fps・長さ）→ 作る → 開く。
// 新しい作品はひな形から作るので、Mittler の画面の上にそのためのボタンを置く。
// 作るのはサーバーの /api/new_project → tools/new_project.js の create()（ひな形 templates/project/ から。VS Code のコマンド「Mittler: 新しい作品を作る」・
// スキル mittler-new-project・コマンドラインと同じ 1 つの道）。今開いている作品は何も変わらない。
// VS Code の中：置く場所は「選ぶ…」（OS のフォルダ選び）でも選べて、できたタイムラインが新しいタブで開く。
// ブラウザで直に開いているとき：置く場所は文字で入れる。作ったあと、場所と開き方を窓に出す（フォルダをエクスプローラーで開ける）。
// 画面の言葉は辞書の np.*。作る作品のトラックの名前は、今の画面の言葉で入る（サーバーに lang を渡す）。言葉を切り替えたら、窓を打った値のまま作り直す
'use strict';
(() => {
  const btn = $('newProjBtn'); if (!btn) return;
  const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;  // tools/new_project.js と同じ決まり（最後に確かめるのは create()）
  const SIZES = [[1920, 1080, 'size.fhdH'], [1280, 720, 'size.hdH'], [854, 480, 'size.sdH'], [1080, 1920, 'size.fhdV'], [1080, 1080, 'size.square']];  // 📐 と同じ並び（名前は辞書の鍵）
  const post = (p, body) => api(p, { method: 'POST', body: JSON.stringify(body || {}), headers: { 'Content-Type': 'application/json' } }).then(r => r.json());
  let dlg = null, info = null, lastFocus = null, result = null, errMsg = null;

  function close() { if (dlg) { dlg.remove(); dlg = null; result = null; errMsg = null; document.removeEventListener('keydown', onKey, true); if (lastFocus && lastFocus.focus) lastFocus.focus(); } }
  function onKey(e) {
    if (!dlg) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.key === 'Enter' && e.target.tagName === 'INPUT' && dlg.querySelector('[data-n="create"]')) { e.preventDefault(); e.stopPropagation(); create(); return; }
    // 窓の中の欄で打つキー（Space・Delete・矢印…）が、後ろのタイムラインに効かないように。Tab は窓の中だけを回る
    if (e.key === 'Tab') {
      const f = [...dlg.querySelectorAll('button,input,select')].filter(x => !x.disabled && x.offsetParent);
      if (!f.length) return; const i = f.indexOf(document.activeElement);
      e.preventDefault(); f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
    }
    e.stopPropagation();
  }

  async function open() {
    if (dlg) return; lastFocus = document.activeElement;
    try { info = await (await api('/api/new_project', { cache: 'no-store' })).json(); }
    catch (e) { MITTLER_NOTIFY($L('np.openFail', { err: e.message || e }), 'bad'); return; }
    dlg = document.createElement('div'); dlg.className = 'mdlg'; dlg.id = 'newProjDlg';
    document.body.appendChild(dlg);
    document.addEventListener('keydown', onKey, true);
    dlg.addEventListener('mousedown', e => { if (e.target === dlg) close(); });
    dlg.addEventListener('click', e => {
      const b = e.target.closest('[data-n]'); if (!b) return;
      ({ close, create, pick, reveal })[b.dataset.n]();
    });
    paint(null);
    dlg.querySelector('#npId').focus();
  }
  // 窓の中身を描く。vals：打った値（言葉を切り替えて描き直すとき、そのまま入れる）
  function paint(vals) {
    const d = info.defaults || {}, W = S.tl.width || d.width, H = S.tl.height || d.height;
    const sizes = SIZES.some(s => s[0] === W && s[1] === H) ? SIZES : [[W, H, 'np.sameSize'], ...SIZES];
    const v = vals || { parent: info.parent || '', id: '', name: '', size: `${W}x${H}`, fps: String(+(S.tl.fps || d.fps)), dur: String(+d.duration) };
    dlg.innerHTML = `<div class="box" role="dialog" aria-modal="true" aria-labelledby="npTitle">
      <div class="dh"><b id="npTitle">${$t('np.title')}</b><span class="sp"></span><button class="xx" data-n="close" title="${esc($t('np.closeEsc'))}" aria-label="${esc($t('ui.close'))}">${MITTLER_ICON('x')}</button></div>
      <div class="db">
        <div class="dl"><label for="npParent">${$t('np.parent')}</label><div><div class="drow"><input id="npParent" type="text" spellcheck="false" value="${esc(v.parent)}">${info.canPick ? `<button data-n="pick" title="${esc($t('np.pick.tip'))}">${$t('np.pick')}</button>` : ''}</div>
          <div class="dnote">${$t('np.parent.note')}</div></div></div>
        <div class="dl"><label for="npId">${$t('np.id')}</label><div><input id="npId" type="text" spellcheck="false" placeholder="my-anime-01" autocomplete="off" value="${esc(v.id)}">
          <div class="dnote">${$t('np.id.note1')}<code id="npFile"></code>${$t('np.id.note2')}</div></div></div>
        <div class="dl"><label for="npName">${$t('np.name')}</label><div><input id="npName" type="text" placeholder="${esc($t('np.name.ph'))}" autocomplete="off" value="${esc(v.name)}"></div></div>
        <div class="dl"><label for="npSize">${$t('np.size')}</label><div><select id="npSize">${sizes.map(([w, h, k]) => `<option value="${w}x${h}"${`${w}x${h}` === v.size ? ' selected' : ''}>${esc($t('size.item', { name: $t(k), w, h }))}</option>`).join('')}</select></div></div>
        <div class="dl"><label for="npFps">${$t('np.fpsDur')}</label><div class="drow"><input id="npFps" type="number" min="1" step="1" value="${esc(v.fps)}" title="${esc($t('np.fps.tip'))}"><span class="tdim">fps</span>
          <input id="npDur" type="number" min="1" step="1" value="${esc(v.dur)}" title="${esc($t('np.dur.tip'))}"><span class="tdim">${$t('np.sec')}</span></div></div>
        <div class="dnote">${$t('np.makes')}</div>
        <div class="derr" id="npErr" role="alert"></div>
      </div>
      <div class="df"><button data-n="close">${$t('np.cancel')}</button><button class="primary" data-n="create">${$t('np.create')}</button></div></div>`;
    const id = dlg.querySelector('#npId');
    const upd = () => {
      const val = id.value.trim(), bad = !!val && !ID_RE.test(val);
      id.classList.toggle('bad', bad); dlg.querySelector('#npFile').textContent = (val && !bad ? val : $t('np.namePh')) + '.cut.json';
      if (bad) err($L('np.badId')); else if (errMsg && errMsg.k === 'np.badId') err('');
    };
    id.addEventListener('input', upd); upd();
    if (errMsg) err(errMsg);
    if (result) paintResult();
  }
  const err = t => { errMsg = t || null; const e = dlg && dlg.querySelector('#npErr'); if (e) e.textContent = t ? String(t) : ''; };

  async function pick() {
    const inp = dlg.querySelector('#npParent');
    try { const r = await post('/api/new_project/pick', { start: inp.value.trim() }); if (r.ok && r.dir && dlg) inp.value = r.dir; else if (r.error) err(r.error); }
    catch (e) { err($L('np.pickFail', { err: e.message || e })); }
  }

  async function create() {
    if (!dlg) return;
    const v = k => dlg.querySelector('#' + k).value.trim();
    const id = v('npId'), [w, h] = v('npSize').split('x').map(Number);
    if (!v('npParent')) return err($L('np.needParent'));
    if (!ID_RE.test(id)) { dlg.querySelector('#npId').focus(); return err($L('np.needId')); }
    const b = dlg.querySelector('[data-n="create"]'); b.disabled = true; b.textContent = $t('np.creating'); err('');
    let r;
    // lang：作る作品のトラックの名前などを、今の画面の言葉で（tools/new_project.js の create() の lang）
    try { r = await post('/api/new_project', { parent: v('npParent'), id, title: v('npName'), width: w, height: h, fps: v('npFps'), duration: v('npDur'), lang: MITTLER_I18N.lang }); }
    catch (e) { r = { ok: false, error: $t('save.noConn', { err: e.message || e }) }; }
    if (!dlg) return;
    if (!r.ok) { b.disabled = false; b.textContent = $t('np.create'); return err($L('np.failed', { err: r.error || '' })); }
    const notes = (r.notes || []).length ? '\n' + r.notes.join('\n') : '';
    if (r.opened === 'vscode') {  // VS Code の中：新しいタブで開いた
      close(); MITTLER_NOTIFY($L('np.openedTab', { dir: r.dir, notes }), (r.notes || []).length ? 'warn' : 'ok', { ms: 12000 });
      setStatus($L('np.made')); return;
    }
    // ブラウザで直に開いているとき：場所と開き方を出す
    setStatus($L('np.made'));
    result = { r, notes }; paintResult();
    dlg.querySelector('.df .primary').focus();
  }
  function paintResult() {
    const { r, notes } = result;
    dlg.querySelector('.db').innerHTML = `<div class="dok"><b>${$t('np.done')}</b><br>${$t('np.folder')}<code>${esc(r.dir)}</code><br>${$t('np.timeline')}<code>${esc(r.timeline)}</code>${notes ? `<br>${esc(notes.trim())}` : ''}</div>
      <div class="dnote">${$t('np.howOpen1')}<code>tools\\mittler.cmd serve "${esc(r.timeline)}"</code><br>${$t('np.howOpen2')}</div>`;
    dlg.querySelector('.df').innerHTML = `<button data-n="reveal">${$t('np.reveal')}</button><button class="primary" data-n="close">${$t('ui.close')}</button>`;
  }
  async function reveal() { try { const r = await post('/api/new_project/reveal'); if (!r.ok) err(r.error || ''); } catch (e) { } }

  btn.addEventListener('click', open);
  // 言葉を切り替えたら、窓が開いていれば打った値のまま描き直す
  MITTLER_I18N.onChange(() => {
    if (!dlg) return;
    const q = k => { const e = dlg.querySelector('#' + k); return e ? e.value : ''; };
    const vals = dlg.querySelector('#npId') ? { parent: q('npParent'), id: q('npId'), name: q('npName'), size: q('npSize'), fps: q('npFps'), dur: q('npDur') } : null;
    paint(vals);
  });
  window.MITTLER_NEWPROJECT = { open, close };
})();
