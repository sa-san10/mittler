// Mittler 編集画面：API の見える操作（tools/mittler_api.py の ui）と、AI を追う（オートモード）。editor.js・export.js・state.js のあとに読む。
// 1) 見える操作（2026-11-15。人の操作が要る所は、Suno の採用と H3 の生成のほか、全部 API から頼めるようにする。
//    Claude Code が Mittler を動かしながら録画するとき、computer use を使わない代わりに、画面の操作も API から）：
//    サーバーの変更通知（/api/events）の 'ui' で届いた頼みを、ボタンと同じ関数でして、/api/ui/<id>/done で答える（今の再生位置・選び・タブ・拡大・言葉）。
//    どれも作品を変えない（取り消しの記録に入らない。undo・redo だけは取り消しそのもの）。
// 2) AI を追う（2026-11-15。AI が直した所へタイムラインの再生位置を飛ばして、AI の作業の進み具合を画面で見る。
//    クリップを直したら、そのクリップの真ん中へ。上のバーに、オートモードの入・切のボタン）：
//    外（AI・API・ファイルの書きかえ）でタイムラインが変わって読み直したとき、変わったクリップ（editor/ops.js の changedClips）の真ん中の時刻へ再生位置を飛ばし、
//    見える所までタイムラインを動かし、そのクリップを数秒光らせる。選んでいるもの（人の選択）は変えない。止まっているときだけ飛ばす（再生中・ドラッグ・入力の最中は印だけ）。
//    続けて来たら、まとめて最後の 1 回（0.4 秒あけて）。いくつも変わったら、いちばんあとの時刻のもの。API で「飛ぶ・選ぶ」と頼まれた直後（3 秒）はそちらを優先して飛ばない。
//    上のバーの「オート」で切り替え（既定はオン。この画面が覚える）。
'use strict';
(() => {
  // ---------- AI を追う ----------
  const F = { on: (() => { try { return localStorage.getItem('mittler.followAi') !== '0'; } catch (e) { return true; } })(), timer: null, pending: null, remoteAt: 0, flash: null };
  const btn = $('followBtn');
  function paintBtn() {
    if (!btn) return;
    btn.classList.toggle('on', F.on); btn.setAttribute('aria-pressed', F.on ? 'true' : 'false');
    btn.title = $t(F.on ? 'bar.follow.tipOn' : 'bar.follow.tipOff');
  }
  function setFollow(on) {
    F.on = !!on; try { localStorage.setItem('mittler.followAi', F.on ? '1' : '0'); } catch (e) { }
    paintBtn(); setStatus($L(F.on ? 'st.followOn' : 'st.followOff'));
    if (!F.on) { F.pending = null; clearTimeout(F.timer); }
  }
  if (btn) btn.addEventListener('click', () => setFollow(!F.on));
  paintBtn(); MITTLER_I18N.onChange(paintBtn);
  const typing = () => { const a = document.activeElement; return !!(a && /^(TEXTAREA|INPUT|SELECT)$/.test(a.tagName) && a.type !== 'range' && a.type !== 'checkbox' && a.type !== 'radio'); };
  function onExternal(prev, next) {
    if (!F.on) return;
    const ch = OPS.changedClips(prev, next); if (!ch.length) return;
    F.pending = ch.reduce((a, b) => (b.start >= a.start ? b : a));  // いちばんあとの時刻のもの
    clearTimeout(F.timer); F.timer = setTimeout(go, 400);
  }
  function go() {
    const x = F.pending; F.pending = null; if (!x || !F.on || !S.tl) return;
    F.flash = { id: x.id, start: x.start, dur: x.dur, gone: x.gone, until: Date.now() + 2600 };
    paint(); setTimeout(paint, 2700);
    const busy = S.playing || S.drag || S.dragging || S.marq || typing() || Date.now() - F.remoteAt < 3000;
    if (busy) return;  // 印だけ（再生中・人が触っている最中・API で飛ぶ／選ぶと頼まれた直後）
    const fpsv = S.tl.fps || 30, mid = Math.round(Math.min(S.tl.duration || 10, Math.max(0, x.start + x.dur / 2)) * fpsv) / fpsv;
    S.seek(mid);
    reveal(x);
  }
  // そのクリップが見える所までタイムラインを動かす（拡大はそのまま）
  function reveal(x) {
    const wr = $('lanesWrap'); if (!wr) return;
    const L = x.start * S.pps, R = (x.start + x.dur) * S.pps, W = wr.clientWidth;
    if (L < wr.scrollLeft || R > wr.scrollLeft + W - 24) wr.scrollLeft = Math.max(0, R - L < W - 80 ? (L + R) / 2 - W / 2 : L - 40);
    const el = document.querySelector(`#laneList .clip[data-id="${CSS.escape(x.id)}"]`) || document.querySelector(`#laneList .aiflash`);
    if (el) { const b = el.getBoundingClientRect(), w = wr.getBoundingClientRect(); if (b.top < w.top + 20 || b.bottom > w.bottom) wr.scrollTop += b.top - w.top - 40; }
  }
  // 光らせる印（タイムラインを作り直しても付け直す。消えたクリップは前の場所に枠だけ）
  function paint() {
    document.querySelectorAll('#laneList .aiflash').forEach(el => { if (el.classList.contains('aigone')) el.remove(); else el.classList.remove('aiflash'); });
    const f = F.flash; if (!f || Date.now() > f.until || !S.tl) return;
    const el = document.querySelector(`#laneList .clip[data-id="${CSS.escape(f.id)}"]`);
    if (el) { el.classList.add('aiflash'); return; }
    const lane = document.querySelector('#laneList .lane[data-track]'); if (!lane || !f.gone) return;
    const g = document.createElement('div'); g.className = 'aiflash aigone'; g.style.left = (f.start * S.pps) + 'px'; g.style.width = Math.max(3, f.dur * S.pps) + 'px'; lane.appendChild(g);
  }
  window.MITTLER_FOLLOW = { onExternal, paint, set: setFollow, get on() { return F.on; } };

  // ---------- 見える操作 ----------
  const r3 = x => Math.round(x * 1000) / 1000;
  function snapshot() {
    const wr = $('lanesWrap');
    return { t: r3(S.t), frame: Math.round(S.t * (S.tl.fps || 30)), playing: !!S.playing, sel: S.sel || null, multi: [...(S.multi || [])], track: S.selTrack || null, pane: S.pane,
      pps: r3(S.pps), view: wr ? { from: r3(wr.scrollLeft / S.pps), to: r3((wr.scrollLeft + wr.clientWidth) / S.pps) } : null, lang: MITTLER_I18N.lang, follow: F.on,
      export_open: !!(window.MITTLER_EXPORT && MITTLER_EXPORT.isOpen), undo: S.undo.length, redo: (S.redo || []).length };
  }
  const PANES = { clip: 'sel', sel: 'sel', color: 'grade', grade: 'grade', meta: 'meta', metadata: 'meta' };
  const num = v => { const x = +v; if (!isFinite(x)) throw new Error('bad number: ' + v); return x; };
  const CMDS = {
    play: () => { if (!S.playing) S.setPlaying(true); },
    pause: () => { if (S.playing) S.setPlaying(false); },
    stop: () => { if (S.playing) S.setPlaying(false); },
    toggle: () => S.setPlaying(!S.playing),
    seek: a => { F.remoteAt = Date.now(); if (S.playing) S.setPlaying(false); S.seek(snapFrame(num(a.t))); S.followPlayhead(); },
    step: a => { F.remoteAt = Date.now(); S.stepFrames(Math.round(num(a.n != null ? a.n : 1))); },
    select: a => {
      F.remoteAt = Date.now();
      const ids = (a.ids || []).filter(Boolean);
      if (a.track) { const tr = S.tl.tracks.find(t => t.id === a.track); if (!tr) throw new Error($t('rm.noTrack', { id: a.track })); S.select(null); S.selTrack = tr.id; buildTimeline(); showSel(); S.showPane('sel'); return; }
      if (!ids.length) { S.select(null); return; }
      for (const id of ids) if (!findClip(id)) throw new Error($t('rm.noClip', { id }));
      S.select(ids[0]); for (const id of ids.slice(1)) S.select(id, true);
      if (a.pane !== false) S.showPane('sel');
      if (a.seek) { const c = findClip(ids[0]).clip; S.seek(snapFrame(c.start + c.dur / 2)); }
      const c = findClip(ids[0]).clip; reveal({ id: c.id, start: c.start, dur: c.dur });
    },
    pane: a => { const p = PANES[String(a.name || '')]; if (!p) throw new Error($t('rm.badPane', { name: a.name })); S.showPane(p); },
    zoom: a => { if (a.fit) S.zoomFit(); else S.setZoom(num(a.pps)); },
    fit: () => S.zoomFit(),
    scroll: a => { const wr = $('lanesWrap'); wr.scrollLeft = Math.max(0, num(a.t) * S.pps - (a.center === false ? 40 : wr.clientWidth / 2)); },
    lang: a => { if (!MITTLER_I18N.LANGS.includes(a.lang)) throw new Error($t('rm.badLang', { lang: a.lang })); MITTLER_I18N.set(a.lang); },
    'open-export': () => MITTLER_EXPORT.open(false),
    'open-master': () => MITTLER_EXPORT.open(true),
    'close-export': () => MITTLER_EXPORT.close(),
    undo: () => S.undoNow(),
    redo: () => S.redoNow(),
    follow: a => setFollow(a.on !== false && a.on !== 'off'),
    state: () => { },
    reload: () => { },  // 下の run で（答えてから読み直す）
  };
  async function run(m) {
    const { id, cmd, args } = m || {}; if (!id) return;
    let r;
    try {
      const fn = CMDS[cmd]; if (!fn) throw new Error($t('rm.badCmd', { cmd, list: Object.keys(CMDS).join(', ') }));
      if (!S.tl) throw new Error($t('rm.notReady'));
      await fn(args || {});
      if (cmd !== 'state') setStatus($L('rm.status', { what: cmd + (args && Object.keys(args).length ? ' ' + JSON.stringify(args) : '') }));
      if (window.MITTLER_STATE && MITTLER_STATE.push) await MITTLER_STATE.push();  // 選び・時刻を .mittler/state.json（フック）にもすぐ
      r = { ok: true, cmd, state: snapshot() };
    } catch (e) { r = { ok: false, cmd, error: String(e.message || e) }; }
    try { await api(`/api/ui/${id}/done`, { method: 'POST', body: JSON.stringify(r), headers: { 'Content-Type': 'application/json' } }); } catch (e) { }
    if (r.ok && cmd === 'reload') $('reloadBtn').click();
  }
  window.MITTLER_REMOTE = { run, snapshot, CMDS };
})();
