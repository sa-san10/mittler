// Mittler 編集画面：✏️ 書き込み（止めた画面にペンで描いて、その画像を横の Claude Code に渡す。
// 渡すのは画像だけ：どのみち Claude Code に話しかけるので、文章の欄は無し）。
// 「AI に渡す」（Claude Code ならフックが添える・ほかの AI には、クリップボードにコピーした文を貼る。state.json の annotations_pending にも載る）→ サーバーの /api/annotate が作品の状態フォルダ（.mittler。前からの作品は .claude-cut）の annotations/<id>/ に after.jpg（書き込んだ画面）・before.jpg（書き込み前）・
// annotation.json（時刻・その時刻のクリップ・線の範囲）を置き、VS Code の中なら拡張が Claude Code の入力欄にフォーカスする。
// 次に Claude Code に話しかけると、フック（tools/mittler_state.py）がまだ渡していない書き込みの画像を添える（1回添えたら delivered にする）。
// 画面の言葉は辞書の an.*。言葉を切り替えたら、道具の帯・ボタン・縮小を作り直す
'use strict';
(() => {
  const TOOLS = [['pen', 'pencil'], ['arrow', 'move-up-right'], ['ellipse', 'circle'], ['rect', 'rectangle-horizontal']];  // 名前は辞書の an.tool.<道具>。印は Lucide のアイコン
  const COLORS = ['#ff3b30', '#ffd60a', '#32d2ff', '#ffffff'];
  const WIDTHS = [[4, 'thin'], [8, 'mid'], [16, 'thick']];  // 名前は辞書の an.w.<太さ>
  const A = { on: false, tool: 'pen', color: COLORS[0], width: 8, strokes: [], cur: null, before: null, t: 0 };
  window.MITTLER_ANNOT = A;

  // ---- 画面の部品（header のボタン、screen の上の canvas、下の欄） ----
  const btn = document.createElement('button');
  btn.id = 'annotBtn'; btn.className = 'ib';
  $('redo').after(btn);  // ↶ ↷ の右（前は ↶ と ↷ のあいだに入っていた）
  const cv = document.createElement('canvas'); cv.id = 'annotCv'; cv.hidden = true; $('screen').appendChild(cv);
  const bar = document.createElement('div'); bar.id = 'annotBar'; bar.hidden = true; $('stage').appendChild(bar);
  function paint() {
    btn.innerHTML = MITTLER_ICO('pencil', $t('an.btn')); btn.title = $t('an.btn.tip');
    bar.innerHTML = `<div class="atools">
      ${TOOLS.map(([k, i]) => `<button data-tool="${k}" title="${esc($t('an.tool.' + k))}">${MITTLER_ICON(i)}</button>`).join('')}
      <span class="sep"></span>${COLORS.map(c => `<button data-color="${c}" class="sw" style="background:${c}" title="${c}"></button>`).join('')}
      <span class="sep"></span>${WIDTHS.map(([w, n]) => `<button data-width="${w}" title="${esc($t('an.wTip', { w: $t('an.w.' + n) }))}">${esc($t('an.w.' + n))}</button>`).join('')}
      <span class="sep"></span><button data-act="undo" title="${esc($t('an.undo'))}">${MITTLER_ICON('undo-2')}</button><button data-act="clear" title="${esc($t('an.clear'))}">${MITTLER_ICON('eraser')}</button>
      <span class="ainfo"></span></div>
    <div class="abtns"><span class="ahint">${$t('an.hint')}</span><span class="sp"></span><button data-act="cancel">${$t('an.cancel')}</button><button data-act="send" class="primary">${$t('an.send')}</button></div>`;
  }
  paint();

  const W = () => (S.tl && S.tl.width) || 1920, H = () => (S.tl && S.tl.height) || 1080;
  function refreshBar() {
    bar.querySelectorAll('[data-tool]').forEach(b => b.classList.toggle('on', b.dataset.tool === A.tool));
    bar.querySelectorAll('[data-color]').forEach(b => b.classList.toggle('on', b.dataset.color === A.color));
    bar.querySelectorAll('[data-width]').forEach(b => b.classList.toggle('on', +b.dataset.width === A.width));
    bar.querySelector('.ainfo').textContent = $t('an.info', { t: fmt(A.t), f: Math.round(A.t * fps()), n: A.strokes.length });
  }

  // ---- 描く ----
  function drawStroke(g, s) {
    g.strokeStyle = s.color; g.lineWidth = s.width; g.lineCap = 'round'; g.lineJoin = 'round';
    const p = s.pts; if (!p.length) return;
    g.beginPath();
    if (s.tool === 'pen') { g.moveTo(p[0][0], p[0][1]); for (const q of p) g.lineTo(q[0], q[1]); g.stroke(); return; }
    const [a, b] = [p[0], p[p.length - 1]];
    if (s.tool === 'rect') { g.strokeRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])); return; }
    if (s.tool === 'ellipse') { g.ellipse((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, Math.max(1, Math.abs(b[0] - a[0]) / 2), Math.max(1, Math.abs(b[1] - a[1]) / 2), 0, 0, Math.PI * 2); g.stroke(); return; }
    // 矢印：線と頭
    g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
    const ang = Math.atan2(b[1] - a[1], b[0] - a[0]), L = Math.max(18, s.width * 3.5);
    g.beginPath(); g.moveTo(b[0], b[1]); g.lineTo(b[0] - L * Math.cos(ang - 0.45), b[1] - L * Math.sin(ang - 0.45));
    g.moveTo(b[0], b[1]); g.lineTo(b[0] - L * Math.cos(ang + 0.45), b[1] - L * Math.sin(ang + 0.45)); g.stroke();
  }
  function redraw() {
    const g = cv.getContext('2d'); g.clearRect(0, 0, cv.width, cv.height);
    for (const s of A.strokes) drawStroke(g, s);
    if (A.cur) drawStroke(g, A.cur);
    refreshBar();
  }
  const pos = e => { const r = cv.getBoundingClientRect(); return [+((e.clientX - r.left) / r.width * cv.width).toFixed(1), +((e.clientY - r.top) / r.height * cv.height).toFixed(1)]; };
  cv.addEventListener('pointerdown', e => {
    if (e.button !== 0) return; cv.setPointerCapture(e.pointerId);
    A.cur = { tool: A.tool, color: A.color, width: A.width, pts: [pos(e)] }; redraw();
  });
  cv.addEventListener('pointermove', e => {
    if (!A.cur) return; const p = pos(e);
    if (A.cur.tool === 'pen') A.cur.pts.push(p); else A.cur.pts[1] = p;
    redraw();
  });
  cv.addEventListener('pointerup', () => {
    if (!A.cur) return; const s = A.cur; A.cur = null;
    if (s.pts.length > 1 || s.tool === 'pen') A.strokes.push(s);
    redraw();
  });

  // ---- 始める・やめる ----
  async function frameImage(t) {  // 書き込み前の絵（いま止めているコマ、元の大きさ）
    const r = await api(`/api/frame?t=${t}&q=95`); if (!r.ok) throw new Error($t('an.frameFail', { code: r.status }));
    const url = URL.createObjectURL(await r.blob()); const img = new Image(); img.src = url; await img.decode(); return img;
  }
  async function start() {
    if (A.on) return;
    if (S.playing) setPlaying(false);
    A.t = S.t; A.strokes = []; A.cur = null; A.before = null;
    cv.width = W(); cv.height = H(); cv.hidden = false; bar.hidden = false; A.on = true; btn.classList.add('on');
    $('stage').classList.add('annot'); fitScreen();  // 道具の帯のぶん、絵を上に小さく
    redraw();
    setStatus($L('an.st.on'));
    try { A.before = await frameImage(A.t); } catch (e) { setStatus($L('an.st.noBefore', { err: e.message })); }
  }
  function stop() { A.on = false; cv.hidden = true; bar.hidden = true; btn.classList.remove('on'); A.strokes = []; A.cur = null; $('stage').classList.remove('annot'); fitScreen(); }
  btn.onclick = () => (A.on ? stop() : start());

  // その時刻に映っているクリップ（線の下にあるかもしれないもの）
  function clipsAt(t) {
    const out = [];
    for (const tr of S.tl.tracks || []) {
      if (tr.hidden || tr.muted) continue;
      for (const c of tr.clips || []) {
        if (c.disabled || !(c.start <= t && t < c.start + c.dur)) continue;
        out.push({ id: c.id, type: c.type, effect: c.effect || undefined, track: tr.name || tr.id, label: clipLabel(c), start: c.start, dur: c.dur, cut: c.cut });
      }
    }
    return out;
  }
  function bbox() {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const s of A.strokes) for (const [x, y] of s.pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    return isFinite(x0) ? [Math.round(x0), Math.round(y0), Math.round(x1), Math.round(y1)] : null;
  }
  async function send() {
    if (!A.strokes.length) { setStatus($L('an.st.empty')); return; }
    const sb = bar.querySelector('[data-act="send"]'); sb.disabled = true;
    try {
      if (!A.before) A.before = await frameImage(A.t);
      const mk = () => { const k = document.createElement('canvas'); k.width = W(); k.height = H(); return k; };
      const before = mk(); before.getContext('2d').drawImage(A.before, 0, 0, W(), H());
      const after = mk(); const ga = after.getContext('2d'); ga.drawImage(before, 0, 0); for (const s of A.strokes) drawStroke(ga, s);
      const sel = S.sel && findClip(S.sel);
      const body = { t: A.t, frame: Math.round(A.t * fps()), strokes: A.strokes, bbox: bbox(), width: W(), height: H(),
        clips: clipsAt(A.t), selection: sel ? { id: sel.clip.id, type: sel.clip.type, effect: sel.clip.effect, track: sel.track.name || sel.track.id, label: clipLabel(sel.clip) } : null,
        before: before.toDataURL('image/jpeg', 0.92), after: after.toDataURL('image/jpeg', 0.92) };
      const r = await (await api('/api/annotate', { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } })).json();
      if (!r.ok) throw new Error(r.error || $t('st.codeSaveFailed'));
      // どの AI にも渡せるように、描いた画面の場所と短い頼みの文をクリップボードに（Claude Code はフックが添えるので、貼らなくてもよい。2026-11-22）
      let copied = false;
      if (r.path) {
        const txt = $t('an.clip', { path: r.path, t: fmt(A.t), frame: Math.round(A.t * fps()), meta: r.meta || '' });
        try { await navigator.clipboard.writeText(txt); copied = true; } catch (e) {
          try { const ta = document.createElement('textarea'); ta.value = txt; document.body.appendChild(ta); ta.select(); copied = document.execCommand('copy'); ta.remove(); } catch (e2) { }
        }
      }
      stop(); setStatus(copied ? $LJ($L('an.st.sent', { id: r.id }), $L('an.st.copied')) : $L('an.st.sent', { id: r.id }), 'ok');
      addPip({ id: r.id, image: r.image, t: A.t });
    } catch (e) { setStatus($L('an.st.sendFail', { err: e.message || e })); }
    finally { sb.disabled = false; }
  }

  bar.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.tool) A.tool = b.dataset.tool;
    else if (b.dataset.color) A.color = b.dataset.color;
    else if (b.dataset.width) A.width = +b.dataset.width;
    else if (b.dataset.act === 'undo') A.strokes.pop();
    else if (b.dataset.act === 'clear') A.strokes = [];
    else if (b.dataset.act === 'cancel') { stop(); setStatus($L('an.st.cancel')); return; }
    else if (b.dataset.act === 'send') { send(); return; }
    redraw();
  });
  // 書き込み中のキー：Ctrl+Z は線を戻す（タイムラインの取り消しにしない）、Esc でやめる、Enter で渡す。再生・コマ送りはしない
  window.addEventListener('keydown', e => {
    if (!A.on) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); stop(); setStatus($L('an.st.cancel')); return; }
    if (e.key === 'Enter') { e.preventDefault(); e.stopImmediatePropagation(); send(); return; }
    if (e.key === 'z' && (e.ctrlKey || e.metaKey)) { A.strokes.pop(); redraw(); }
    e.preventDefault(); e.stopImmediatePropagation();
  }, true);
  window.addEventListener('resize', () => { if (A.on) redraw(); });

  // ---- 渡した画面の縮小（プレビューの右下）。❌ で閉じる、絵を押すとその時刻へ。Claude に届いたか（フックが添えたら delivered）を出す ----
  // Claude Code に画像を渡したあと、画面の端に、✕ で閉じられる小さな絵を残す
  const pipBox = document.createElement('div'); pipBox.id = 'annotPips'; $('stage').appendChild(pipBox);
  const pipKey = () => 'cc.annotPips:' + (S.file || '');
  let pips = [], pipTimer = null;
  function loadPips() { try { pips = JSON.parse(localStorage.getItem(pipKey()) || '[]'); } catch (e) { pips = []; } }
  function savePips() { try { localStorage.setItem(pipKey(), JSON.stringify(pips)); } catch (e) { } }
  function drawPips() {
    pipBox.innerHTML = pips.map(p => `<div class="pip" data-id="${esc(p.id)}">
        <button class="pipx" data-close="${esc(p.id)}" title="${esc($t('ui.close'))}">${MITTLER_ICON('x')}</button>
        <img src="/api/annotation?id=${encodeURIComponent(p.id)}&file=after.jpg" title="${esc($t('an.pipSeek', { t: fmt(p.t) }))}" data-seek="${p.t}">
        <div class="pipcap">${MITTLER_ICON('pencil')} ${fmt(p.t)}${$t('sep.list')}${p.delivered ? `<span class="ok">${$t('an.delivered')}</span>` : `<span class="wait">${$t('an.waiting')}</span>`}</div></div>`).join('');
    pipBox.hidden = !pips.length;
  }
  function addPip(p) { pips = [p].concat(pips.filter(x => x.id !== p.id)).slice(0, 3); savePips(); drawPips(); watchPips(); }
  // 届いたか（annotation.json の delivered）を見る。消された書き込みは縮小も外す
  async function checkPips() {
    let changed = false;
    for (const p of pips.slice()) {
      if (p.delivered) continue;
      try {
        const r = await fetch(`/api/annotation?id=${encodeURIComponent(p.id)}&file=annotation.json`, { cache: 'no-store' });  // /project/ は状態フォルダ（.mittler・.claude-cut）を配らない
        if (r.status === 404) { pips = pips.filter(x => x.id !== p.id); changed = true; continue; }
        if (r.ok && (await r.json()).delivered) { p.delivered = true; changed = true; }
      } catch (e) { }
    }
    if (changed) { savePips(); drawPips(); }
    watchPips();
  }
  function watchPips() { clearTimeout(pipTimer); if (pips.some(p => !p.delivered)) pipTimer = setTimeout(checkPips, 3000); }
  pipBox.addEventListener('click', e => {
    const c = e.target.closest('[data-close]');
    if (c) { pips = pips.filter(x => x.id !== c.dataset.close); savePips(); drawPips(); return; }
    const s = e.target.closest('[data-seek]'); if (s) { if (S.playing) setPlaying(false); seek(+s.dataset.seek); }
  });
  window.MITTLER_PIPS = { add: addPip, get list() { return pips; } };  // 動作確認用
  const waitTl = setInterval(() => { if (!S.tl) return; clearInterval(waitTl); loadPips(); drawPips(); checkPips(); }, 200);
  // 言葉を切り替えたら作り直す（書き込み中でも、描いた線はそのまま）
  MITTLER_I18N.onChange(() => { paint(); if (A.on) refreshBar(); drawPips(); });
})();
