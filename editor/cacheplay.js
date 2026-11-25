// ためた絵（2026-11-16。pyengine/mittler/fcache.py・bake.py、server.js の /api/cachemap・/api/cframe・/api/bake）。
// 編集画面の側でやること：
// - 目盛りの下に、ためてあるコマの印（今のタイムラインの絵がためてある区間）。
// - 止めて手を離すと（IDLE_MS）、サーバーに裏で先に描いてもらう（再生位置から先。優先度の低いプロセス。直す・書き出すと止まる）。
// - ▶：再生位置から先 AHEAD_S 秒のコマがだいたいためてあり、音のトラックがあれば、書き出し版の動画ではなく、ためた絵（小さな JPEG）を時計で流す。
// - プレビューの下の「裏で描く」ボタン（裏で描くのを止められる。既定は切）：押すと切（今描いているものをすぐ止めて、
//   入に戻すまで自分では始めない。この PC のこの画面で覚える）・もう一度押すと入。描いているあいだは進み具合（一時停止中はそう出る）。
//   ためていないコマは、今までの「描けたコマから」と同じく描画サーバーに頼む。
(function () {
  const IDLE_MS = 2500, AHEAD_S = 2, NEED = 0.8, PRELOAD = 45, POLL_MS = 3000;
  const C = { map: null, stamp: '', bake: null, lastInput: Date.now(), lastAsk: 0, imgs: new Map(), refreshing: false, timer: null };
  // 既定は切。ボタンで入にしたら覚える（'0'）
  C.off = (() => { try { return localStorage.getItem('cc.bakeOff') !== '0'; } catch (e) { return true; } })();
  const stampNow = () => `${S.edits}:${S.ver}`;
  const url = k => `/api/cframe?k=${k}&token=${TOKEN}`;

  async function refresh() {
    if (C.refreshing || !S.tl) return;
    C.refreshing = true;
    const stamp = stampNow();
    try {
      const r = await api(`/api/cachemap?from=0&to=${dur()}`, { cache: 'no-store' });
      const j = await r.json();
      if (j && Array.isArray(j.keys)) { C.map = j; C.stamp = stamp; C.bake = j.bake || null; drawBar(); showBtn(); }
    } catch (e) { }
    finally { C.refreshing = false; }
    clearTimeout(C.timer);
    if (C.bake && C.bake.state === 'running') C.timer = setTimeout(refresh, POLL_MS);  // 裏で描いているあいだは、印を伸ばしていく
  }
  const fresh = () => C.map && C.stamp === stampNow();

  // 目盛りの下の印（ためてある続きの区間ごとに 1 本）
  function drawBar() {
    const ru = $('ruler'); if (!ru) return;
    ru.querySelectorAll('.cbar').forEach(e => e.remove());
    if (!C.map || !fresh()) return;
    const { fps, n0, keys } = C.map; let h = '', a = -1;
    for (let i = 0; i <= keys.length; i++) {
      const on = i < keys.length && !!keys[i];
      if (on && a < 0) a = i;
      if (!on && a >= 0) { h += `<div class="cbar" style="left:${(n0 + a) / fps * S.pps}px;width:${Math.max(1, (i - a) / fps * S.pps)}px"></div>`; a = -1; }
    }
    if (h) ru.insertAdjacentHTML('beforeend', h);
    const n = keys.filter(Boolean).length;
    ru.title = $t('cache.barTip', { n, total: keys.length }) + (C.bake && C.bake.state === 'running' ? $t('cache.baking', { done: C.bake.done, total: C.bake.total }) : '');
  }

  // 止めて手を離したら、裏で先に描いてもらう（サーバーが動いているものは続ける。直す・書き出すとサーバーが止める）
  // 操作した瞬間に、裏で描いているものを一時停止してもらう（シーク・ドラッグの絵を先に。サーバーは静かになって 2.5 秒で続ける。プレビューの絵の頼みでも止まる）
  let lastPause = 0;
  const pauseBake = () => {
    C.lastInput = Date.now();
    if (!C.bake || C.bake.state !== 'running' || Date.now() - lastPause < 800) return;
    lastPause = Date.now();
    api('/api/bake/pause', { method: 'POST' }).catch(() => { });
  };
  ['pointerdown', 'pointermove', 'keydown', 'wheel'].forEach(ev => window.addEventListener(ev, e => {
    if (e.type === 'pointermove' && !e.buttons) return;  // ドラッグ（押したまま動かす）だけ
    pauseBake();
  }, { capture: true, passive: true }));
  setInterval(async () => {
    if (!S.tl || S.playing || S.dragging || S.saveTimer || S.saving) return;
    if (Date.now() - C.lastInput < IDLE_MS || Date.now() - C.lastAsk < 5000) return;
    if (C.off || (C.bake && (C.bake.state === 'running' || C.bake.off))) return;
    if (fresh() && C.map.keys.every(Boolean)) return;  // 全部ためてある
    C.lastAsk = Date.now();
    try {
      const j = await (await api('/api/bake', { method: 'POST', body: JSON.stringify({ from: S.t }), headers: { 'Content-Type': 'application/json' } })).json();
      C.bake = j; showBtn(); if (j.ok) refresh();
    } catch (e) { }
  }, 1000);

  // ▶ でためた絵を流せるか（今のタイムラインの地図で、再生位置から先 AHEAD_S 秒の NEED 以上がためてある）
  function canPlay(t) {
    if (!fresh()) return false;
    const { fps, n0, keys } = C.map, a = Math.round(t * fps) - n0, b = Math.min(keys.length, a + Math.round(AHEAD_S * fps));
    if (a < 0 || b <= a) return false;
    let n = 0; for (let i = a; i < b; i++) if (keys[i]) n++;
    return n / (b - a) >= NEED;
  }
  // 再生中の 1 コマ：ためてあれば（読めていれば）出して true、ためていなければ false（呼ぶ側が描画サーバーに頼む）
  function show(t) {
    if (!C.map) return false;
    const { fps, n0, keys } = C.map, i = Math.round(t * fps) - n0, k = keys[i];
    for (let j = i; j < Math.min(keys.length, i + PRELOAD); j++) {  // 先読み
      if (keys[j] && !C.imgs.has(j)) { const im = new Image(); im.src = url(keys[j]); C.imgs.set(j, im); }
    }
    for (const j of C.imgs.keys()) if (j < i - 5) C.imgs.delete(j);
    if (!k) return false;
    const im = C.imgs.get(i);
    if (im && im.complete && im.naturalWidth) { const img = $('frameImg'); if (img.getAttribute('src') !== im.src) img.src = im.src; img.hidden = false; }
    return true;
  }
  function stopPlay() { C.imgs.clear(); }

  // 「裏で描く」ボタン：入・切と、描いているあいだの進み具合
  function showBtn() {
    const b = $('bakeBtn'); if (!b) return;
    const bk = C.bake || {}, cfgOff = !!bk.off, run = !C.off && !cfgOff && bk.state === 'running';
    const pct = run && bk.total ? Math.floor(100 * bk.done / bk.total) : null;
    // ボタンはアイコン（再生の操作の並びを狭くしない）。描いているあいだだけ %・一時停止は ‖、切は斜線。状態の言葉はツールチップと aria-label
    $('bakeTxt').textContent = run ? (bk.paused ? '‖' : (pct == null ? '…' : pct + '%')) : '';
    const word = C.off || cfgOff ? $t('bake.off') : run ? (bk.paused ? $t('bake.paused') : $t('bake.run', { p: pct == null ? '…' : pct })) : $t('bake.on');
    b.classList.toggle('off', C.off || cfgOff); b.classList.toggle('run', run);
    b.disabled = cfgOff;
    b.title = word + ' — ' + (cfgOff ? $t('bake.cfgOff') : (C.off ? $t('bake.tipOff') : $t('bake.tipOn')) + (run ? $t('cache.baking', { done: bk.done, total: bk.total }) : ''));
    b.setAttribute('aria-label', word);
  }
  async function setOff(off) {
    C.off = !!off;
    try { localStorage.setItem('cc.bakeOff', C.off ? '1' : '0'); } catch (e) { }
    if (C.off) { try { const j = await (await api('/api/bake/stop', { method: 'POST' })).json(); C.bake = j; } catch (e) { } }
    else C.lastAsk = 0;
    showBtn();
    setStatus($L(C.off ? 'bake.stOff' : 'bake.stOn'), 'ok');
  }
  $('bakeBtn').addEventListener('click', () => setOff(!C.off));
  setInterval(() => { if (C.bake && C.bake.state === 'running') showBtn(); }, 1000);

  const prev = window.MITTLER_ON_CHANGE;
  window.MITTLER_ON_CHANGE = kinds => { if (prev) prev(kinds); C.lastInput = Date.now(); clearTimeout(C.timer); C.timer = setTimeout(refresh, 1500); };
  window.MITTLER_CACHE = { refresh, drawBar, canPlay, show, stopPlay, setOff, state: () => ({ map: C.map, fresh: fresh(), bake: C.bake, off: C.off }) };
  if (window.MITTLER_I18N) MITTLER_I18N.onChange(() => { showBtn(); drawBar(); });  // 言葉を切り替えたら入れ直す
  showBtn();
  setTimeout(refresh, 1500);
})();
