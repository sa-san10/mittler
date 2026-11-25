// Mittler 編集画面：カットの段（メタデータ kind "cuts"：{label, start, end, 歌詞 lyric・ト書き togaki など}）を手で置く・直す道具。editor.js のあとに読む。
// カットとト書きを、タイムラインの上で手で置く・直すための道具
// （✂ カット編集の道具 cutedit.js はクリップを切る道具で、これとは別。ここが直すのはカットのメタデータ）
// - 境目をつかんで動かす：隣のカットの終わり・始まりも一緒に動く（すき間・重なりは作らない）
// - 分ける（再生位置・ダブルクリック・右クリック）：新しいラベルは今のラベルから（12 → 12b、全部が数字で最後のカットなら 41 → 42、数字の無いラベルは hook → hook-2）
// - つなぐ・消す：隣のカットに吸わせる（Delete は前のカットへ。先頭なら次へ）
// - ラベルを変える（右の「メタデータ」の欄）・歌詞とト書きの文字（同じ欄）
// カットのラベルを参照しているもの（クリップの cut：映像・画像・🎬・エフェクト。色の卓の grade・窓が per_cut のエフェクトも）の扱い：
// - ラベルを変える：参照も一緒に変える（絵は変わらない）
// - 分ける：新しいほうにあるクリップは新しいラベルへ。またがるもの：per_cut のエフェクト（色の卓など）は両方のカットに写す（同じ値）、
//   そのほかのエフェクトは同じ時間のまま新しいカット用の写しを足す、映像・画像のクリップは同じところで分ける（映る絵は同じ）。
//   分けると絵が変わってしまう映像（音ハメの表のファイル・最後のコマに着地 land・弾んで出る画像・🎬 のクリップ）がまたがるときは、分けない（知らせる）
// - つなぐ・消す：消えるカットのクリップは、残るカット（吸った先）のラベルへ。ただし per_cut のエフェクトで、残るカットに同じエフェクトがあるものは消す（残るカットの値になる）
// - per_cut のエフェクトの頭と長さは、いつもカットに合わせる
// - 映像クリップは動かさない（映像とカットは別のもの）。カットの境目と、そのカットのラベルの付いた映像クリップの端がずれたら、カットの段に ⚠ を出して知らせる
//   （ずれたところの絵は、そのカットの映像クリップが無い時刻になる。エンジンの _pick_clip）。
//   「🎞️ 映像をカットに合わせる」（欄・右クリック・境目を動かしたあとの知らせ・「全部合わせる」）で、映像の端をカットにそろえる（ロール編集。下の alignVideo）
// どれも1回の取り消し（Ctrl+Z）で戻る。
// 計算（上の決まりそのもの）は editor/ops.js の cuts（2026-11-15 に移した。API の cut-* と同じもの）。ここは画面（知らせ・選ぶ・欄・右クリック）
'use strict';
(() => {
  const K = () => OPS.cuts(S.tl, opsEnv());
  const lab = it => String(it.label);
  const cutsMeta = () => (S.tl.meta || []).find(m => m.kind === 'cuts');
  const ready = () => {
    if (S.fxReady) return true;
    setStatus($L('cm.waitFx'), 'busy'); return false;
  };
  const after = (msg, level) => { buildMetaPanel(); buildGradePanel(); if (msg) setStatus(msg, level); };
  const nextLabel = (m, it) => K().nextLabel(m, it);
  const syncPerCut = (m, labels) => K().syncPerCut(m, labels);
  const mismatch = it => K().mismatch(it);
  const warnText = (it, w) => $t('cm.warn', { label: lab(it), a: fmt(w.lo), b: fmt(w.hi), c: fmt(it.start), d: fmt(it.end) });

  // ---------- 🎞️ 映像をカットに合わせる（ロール編集） ----------
  // items（カットの項目）の映像を合わせる。1つでも合わせられなければ何も変えない（理由を知らせる）。1回の取り消し
  function alignVideo(items) {
    if (!ready()) return false;
    const m = cutsMeta(); if (!m) return false;
    const pa = K().planAlign(items);
    if (pa.err) { setStatus($L('cm.alignFail', { label: pa.label, err: pa.err })); return false; }
    const todo = pa.todo;
    if (!todo.length) { setStatus($L('cm.alignNone')); return false; }
    change(() => { K().applyAlign(todo); }, { keepForm: true });
    const left = todo.filter(([it]) => mismatch(it));
    const list = { toString: () => todo.map(([it, p]) => $t('cm.alignItem', { label: lab(it), what: p.what })).join($t('cm.sepSlash')) };
    after($LJ($L('cm.aligned', { list }), left.length ? $L('cm.stillOff', { list: left.map(([it]) => lab(it)).join($t('sep.list')) }) : '', $L('cm.undoTail')));
    return true;
  }
  const alignAll = () => { const m = cutsMeta(); return alignVideo(m ? m.items.filter(x => mismatch(x)) : []); };
  // 境目をドラッグしたあとの知らせを押すと、そのカットを合わせる
  let pendingAlign = null;
  $('status').addEventListener('click', () => { if (pendingAlign && S.status.level === 'act' && statusIs('cm.edgeMoved')) { const it = pendingAlign; pendingAlign = null; alignVideo(it); } });

  // ---------- 境目を動かす ----------
  const edgeRange = (m, it, side) => K().edgeRange(m, it, side);
  function edgeMsg(it, r) {
    const nb = r.nb, ws = [it].concat(nb ? [nb] : []).map(x => [x, mismatch(x)]).filter(x => x[1]);
    const sb = $t('sep.bar'), pair = nb ? (r.side === 'l' ? `${lab(nb)}${sb}${lab(it)}` : `${lab(it)}${sb}${lab(nb)}`) : lab(it);
    pendingAlign = ws.length ? ws.map(x => x[0]) : null;  // 知らせを押すと、このカット（と隣）の映像を合わせる
    const w0 = ws.length ? { toString: () => warnText(ws[0][0], ws[0][1]) } : null;
    const msg = $LJ($L(nb ? 'cm.edgeMoved.boundary' : r.side === 'l' ? 'cm.edgeMoved.start' : 'cm.edgeMoved.end', { pair, t: fmt(r.v) }), w0 ? $L('cm.edgeWarn', { w: w0 }) : '');
    msg.act = !!w0;  // 押せる知らせ（▶ ここを押すと…）
    return msg;
  }
  function moveEdge(m, it, side, t) {
    if (!ready() || !m.items.includes(it)) return;
    let r = null; change(() => { r = K().applyEdge(m, it, side, t); }, { keepForm: true });
    if (r) { const msg = edgeMsg(it, r); after($LJ(msg, $L('cm.undoTail')), msg.act ? 'act' : ''); }
  }
  // 欄の頭・終わりの数字から（両方そろってから）。頭と終わりを両方変えても1回の取り消し
  function setTimes(m, it, s, e) {
    if (!ready() || !m.items.includes(it)) return;
    const rs = [];
    change(() => {
      const k = K();
      if (Math.abs(s - it.start) > 1e-6) rs.push(k.applyEdge(m, it, 'l', s));
      if (Math.abs(e - it.end) > 1e-6) rs.push(k.applyEdge(m, it, 'r', e));
    }, { keepForm: true });
    const done = rs.filter(Boolean);
    if (!done.length) { after($L('cm.timesSame'), 'warn'); return; }
    const msgs = done.map(r => edgeMsg(it, r)), parts = [];
    msgs.forEach((x, i) => { if (i) parts.push({ toString: () => $t('cm.sepSlash') }); parts.push(x); });
    after($LJ(...parts, $L('cm.undoTail')), msgs.some(x => x.act) ? 'act' : '');
  }

  // ---------- 分ける ----------
  function split(m, it, t) {
    if (!ready() || !m.items.includes(it)) return null;
    t = OPS.r6(snapFrame(t));
    const er = K().splitErr(it, t); if (er) { setStatus(er); return null; }
    const old = lab(it); let r = null;
    change(() => { r = K().splitIn(m, it, t); }, { keepForm: true });
    const ni = r.ni, nl = lab(ni), n = r.n;
    S.metaSel = { m: m.id, it: ni };
    const det = n.moved || n.dupFx || n.splitPic
      ? $LJ($L('cm.splitMoved', { n: n.moved, label: nl }), n.splitPic ? $L('cm.splitPic', { n: n.splitPic }) : '', n.dupFx ? $L('cm.splitFx', { n: n.dupFx, label: nl }) : '', $L('cm.closeParen')) : '';
    after($LJ($L('cm.splitDone', { old, t: fmt(t), label: nl }), det, $L('cm.undoTail')));
    return ni;
  }
  function splitAtPlayhead() {
    const m = cutsMeta(); if (!m || !m.items.length) { firstCut(); return; }
    const t = snapFrame(S.t), it = m.items.find(x => t >= x.start && t < x.end);
    if (!it) { setStatus($L('cm.noCutHere')); return; }
    split(m, it, t);
  }

  // ---------- つなぐ・消す ----------
  // gone を隣の keep に吸わせる（gone は消える）
  function absorb(m, gone, keep) {
    if (!ready() || !m.items.includes(gone) || !m.items.includes(keep)) return;
    let r = null;
    change(() => {
      r = K().absorbIn(m, gone, keep);
      if (S.metaSel && S.metaSel.it === gone) S.metaSel = { m: m.id, it: keep };
    }, { keepForm: true });
    const w = mismatch(keep);
    after($LJ($L('cm.joined', { g: r.g, k: r.k, n: r.moved }), r.dropped ? $L('cm.joinedDrop', { k: r.k, n: r.dropped }) : '', $L('cm.closeParen'),
      w ? $L('cm.warnTail', { w: { toString: () => warnText(keep, w) } }) : '', $L('cm.undoTail')));
  }
  function join(m, it, dir) {  // dir：-1＝前のカットとつなぐ（it が前に吸われる）、+1＝次のカットとつなぐ（次が it に吸われる）
    const i = m.items.indexOf(it); if (i < 0) return;
    if (dir < 0) { if (i === 0) { setStatus($L('cm.joinFirst')); return; } absorb(m, it, m.items[i - 1]); }
    else { if (i === m.items.length - 1) { setStatus($L('cm.joinLast')); return; } absorb(m, m.items[i + 1], it); }
  }
  function remove(m, it) {  // 消す＝前のカットに吸わせる（先頭なら次へ）
    const i = m.items.indexOf(it); if (i < 0) return;
    if (m.items.length < 2) { setStatus($L('cm.removeLast')); return; }
    if (i > 0) absorb(m, it, m.items[i - 1]); else absorb(m, it, m.items[1]);
  }

  // ---------- ラベルを変える ----------
  function rename(m, it, nl) {
    if (!ready() || !m.items.includes(it)) return false;
    nl = String(nl).replace(/[\r\n\t]+/g, ' ').trim(); const old = lab(it);
    if (!nl) { setStatus($L('cm.labelEmpty'), 'warn'); return false; }
    if (nl === old) return true;
    if (m.items.some(x => x !== it && lab(x) === nl)) { setStatus($L('cm.labelDup', { label: nl })); return false; }
    let n = 0;
    change(() => { n = K().renameIn(it, nl); }, { keepForm: true });
    after($L('cm.renamed', { old, label: nl, n }), 'ok'); return true;
  }

  // ---------- 範囲をカットにする（🎬 採用のとき・欄の「この範囲をカットにする」。動画化予定 → 採用 → カットのデータを足す道） ----------
  const rangePlan = (m, s, e) => K().rangePlan(m, s, e);
  const rangeIn = (s, e, name, extra) => K().rangeIn(s, e, name, extra);
  // 欄のボタン：クリップ c の範囲をカットにする（映像クリップなら、その cut もカットのラベルに）
  function cutFromClip(id) {
    if (!ready()) return;
    const f = findClip(id); if (!f) return; const c = f.clip;
    const pe = rangePlan(cutsMeta(), c.start, c.start + c.dur); if (pe.err) { setStatus($LJ('{icon:scissors} ', pe.err)); return; }
    let r = null;
    change(() => { r = K().cutFromClipIn(c); }, { keepForm: true });
    if (!r || r.err) return;
    S.metaTab = cutsMeta().id; S.metaSel = { m: S.metaTab, it: r.it };
    const isV = c.type === 'video';
    after(r.kind === 'exist' ? $L(isV ? 'cm.rangeExistV' : 'cm.rangeExist', { label: lab(r.it) })
      : $L(isV ? 'cm.rangeMadeV' : 'cm.rangeMade', { a: fmt(c.start), b: fmt(c.start + c.dur), label: lab(r.it) }), r.kind === 'exist' ? '' : 'ok');
    showSel();
  }
  // 🎬 採用のとき（change の中で呼ぶ）：作品の settings.cuts_on_adopt が true なら、予定のクリップの範囲をカットにして、映像クリップ vc の cut をそのラベルに
  const adoptIn = (plan, vc) => K().adoptIn(plan, vc);
  const onAdopt = () => !!((S.tl.settings || {}).cuts_on_adopt);
  function setOnAdopt(on) { change(() => { K().setOnAdoptIn(on); }, { keepForm: true }); setStatus($L(on ? 'cm.adoptOn' : 'cm.adoptOff')); }

  // ---------- 段を作る・最初のカット ----------
  const ensureCuts = () => K().ensureCuts();
  const ensureNotes = () => K().ensureNotes();
  // 最初のカット（全体：0〜動画の長さ、ラベル 1）。カットの無いあいだに全体に置いた色の卓（cut の無い grade）は、このカットのものにする（絵は同じ）
  function firstCut() {
    if (!ready()) return null;
    let r = null;
    change(() => { r = K().firstCutIn(); }, { keepForm: true });
    if (!r) return null;
    const m = cutsMeta(); S.metaSel = { m: m.id, it: r.it }; S.metaTab = m.id;
    after(r.conv ? $L('cm.firstCutConv', { n: r.conv }) : $L('cm.firstCut'));
    return r.it;
  }
  function addLane(kind) {
    if (kind === 'cuts') { if (cutsMeta()) { setStatus($L('cm.cutsExists')); return; } change(() => ensureCuts()); setStatus($L('cm.cutsMade')); }
    else { if ((S.tl.meta || []).some(x => x.kind === 'notes')) { setStatus($L('cm.notesExists')); return; } change(() => ensureNotes()); setStatus($L('cm.notesMade')); }
    buildMetaPanel();
  }

  // ---------- 足す（段の名前の横の ＋・右クリック・ダブルクリック） ----------
  function focusRow(it) {
    const i = S.metaItems.indexOf(it), ta = document.querySelector(`#metaBody .mrow[data-i="${i}"] textarea, #metaBody .mrow[data-i="${i}"] input.mval`); if (ta) ta.focus();
  }
  function addAt(m, t) {  // カット：t で分ける（無ければ最初のカット）。ほか：t に1つ足す
    if (m.kind === 'cuts') {
      if (!m.items.length) { firstCut(); return; }
      const it = m.items.find(x => t >= x.start && t < x.end);
      if (!it) { setStatus($L('cm.noCutHereDrag')); return; }
      const ni = split(m, it, t); if (ni) selectMeta(m, ni); return;
    }
    const it = addMetaItem(m, snapFrame(t)); selectMeta(m, it); focusRow(it);
    setStatus($L('cm.itemAdded', { name: m.name || KIND[m.kind] || m.kind, t: fmt(it.start) }));
  }

  // ---------- 右クリックのメニュー（メタデータの段） ----------
  let menu = null;
  const closeMenu = () => { if (menu) { menu.remove(); menu = null; } };
  $('lanes').addEventListener('contextmenu', e => {
    const ln = e.target.closest('.lane.meta'); if (!ln || !S.tl) return;
    const m = (S.tl.meta || []).find(x => x.id === ln.dataset.meta); if (!m || !Array.isArray(m.items) || m.kind === 'beats' || m.kind === 'pulse_grid') return;
    e.preventDefault(); closeMenu();
    const t = snapFrame(timeAt(e)), iel = e.target.closest('.item'), it = iel ? m.items[+iel.dataset.i] : null;
    if (it) selectMeta(m, it);
    const nm = String(m.name || KIND[m.kind] || m.kind); let h = `<div class="cmh">${esc(it && m.kind === 'cuts' ? $t('cm.menu.headCut', { name: nm, label: lab(it), t: fmt(t) }) : $t('cm.menu.head', { name: nm, t: fmt(t) }))}</div>`;
    if (m.kind === 'cuts') {
      if (!m.items.length) h += `<button data-cm="first">${$t('cm.menu.first')}</button>`;
      else if (it) {
        const i = m.items.indexOf(it);
        h += `<button data-cm="split">${$t('cm.menu.split', { t: fmt(t) })}</button>`
          + `<button data-cm="joinp" ${i ? '' : 'disabled'}>${$t('cm.menu.joinp')}</button>`
          + `<button data-cm="joinn" ${i < m.items.length - 1 ? '' : 'disabled'}>${$t('cm.menu.joinn')}</button>`
          + (mismatch(it) ? `<button data-cm="align">${$t('cm.menu.align')}</button>` : '')
          + `<button data-cm="label">${$t('cm.menu.label')}</button>`
          + `<button data-cm="del" ${m.items.length > 1 ? '' : 'disabled'}>${$t('cm.menu.del')}</button>`;
      } else h += `<div class="tdim">${$t('cm.menu.noCut')}</div>`;
      h += `<div class="tdim">${$t('cm.menu.note')}</div>`;
    } else {
      h += `<button data-cm="add">${$t('cm.menu.add', { t: fmt(t), name: esc(nm) })}</button>`;
      if (it) h += `<button data-cm="edit">${$t('cm.menu.edit')}</button><button data-cm="delit">${$t('cm.menu.delit')}</button>`;
    }
    menu = document.createElement('div'); menu.id = 'ctxMenu'; menu.innerHTML = h; document.body.appendChild(menu);
    const w = menu.offsetWidth, hh = menu.offsetHeight;
    menu.style.left = Math.min(e.clientX, innerWidth - w - 6) + 'px'; menu.style.top = Math.min(e.clientY, innerHeight - hh - 6) + 'px';
    menu.addEventListener('click', ev => {
      const b = ev.target.closest('[data-cm]'); if (!b || b.disabled) return; closeMenu(); const k = b.dataset.cm;
      if (k === 'first') firstCut();
      else if (k === 'split' || k === 'add') addAt(m, t);
      else if (k === 'joinp') join(m, it, -1);
      else if (k === 'joinn') join(m, it, 1);
      else if (k === 'del') remove(m, it);
      else if (k === 'align') alignVideo([it]);
      else if (k === 'label') { selectMeta(m, it); const r = document.querySelector('#metaBody .mrow.picked .mlabel'); if (r) { r.focus(); r.select(); } }
      else if (k === 'edit') { selectMeta(m, it); focusRow(it); }
      else if (k === 'delit') { S.metaSel = { m: m.id, it }; deleteMetaSel(); }
    });
  });
  document.addEventListener('mousedown', e => { if (menu && !e.target.closest('#ctxMenu')) closeMenu(); });
  window.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });

  // 欄に出す「この範囲をカットにする」（映像・🎬 のクリップ。plan.js・warp.js が使う）と、🎬 の「採用するときカットも足す」
  function clipHTML(c) {
    if (c.type === 'video' && c.cut != null) return '';
    const p = rangePlan(cutsMeta(), c.start, c.start + c.dur);
    const st = p.err ? `<span class="tdim">${esc($t('cm.paren', { x: p.err }))}</span>` : p.kind === 'exist' ? `<span class="tdim">${esc($t('cm.rangeIs', { label: lab(p.it) }))}</span>` : '';
    return `<div class="btns cutfrom"><button data-cutfrom ${p.err || (p.kind === 'exist' && c.type !== 'video') ? 'disabled' : ''} title="${esc($t(c.type === 'video' ? 'cm.cutFrom.tipV' : 'cm.cutFrom.tip'))}">${$t('cm.cutFrom')}</button>${st}</div>`
      + (c.type === 'plan' ? `<label class="tdim cutadopt"><input type="checkbox" data-cutadopt ${onAdopt() ? 'checked' : ''}> ${$t('cm.cutAdopt')}</label>` : '');
  }
  function bindClip(el, c) {
    const b = el.querySelector('[data-cutfrom]'); if (b) b.onclick = () => cutFromClip(c.id);
    const k = el.querySelector('[data-cutadopt]'); if (k) k.onchange = () => setOnAdopt(k.checked);
  }

  window.MITTLER_CUTMETA = { nextLabel, edgeRange, moveEdge, setTimes, split, splitAtPlayhead, join, remove, rename, firstCut, ensureCuts, ensureNotes, addLane, addAt, mismatch, warnText, syncPerCut,
    rangePlan, rangeIn, cutFromClip, adoptIn, setOnAdopt, clipHTML, bindClip, alignVideo, alignAll };
})();
