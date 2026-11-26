// Mittler 編集画面：人の手でカット編集する道具（ふつうの動画編集ソフトのあれ）。editor.js のあとに読む。
// 道具：🖱 選択（V）・✂ カット（C。クリップを押したところで分ける、Shift で全部のトラック）・↔ スリップ（Y。位置と長さはそのまま素材の場所 in をずらす）
// 操作：再生位置で分割（Ctrl+K、Ctrl+Shift+K で全部のトラック）・削除（Delete）・リップル削除（Shift+Delete）・隙間を詰める・
//       コピー／貼り付け（Ctrl+C／Ctrl+V。再生位置に）・複製（Ctrl+D。すぐ後ろに）・全部選ぶ（Ctrl+A）・1コマずつ動かす（Alt+←→、Shift で10コマ）・
//       前／次の編集点へ（↑↓）・やり直し（Ctrl+Shift+Z・Ctrl+Y）
// リンク（c.link が同じクリップ）：動画とその音。🔗 連動がオンなら一緒に選ぶ・動かす・伸び縮み・切る・消す。
// 動画を置くと、音があれば WAV に取り出して（サーバーの /api/video_audio）「動画の音」のトラックにリンクして置く。
// 音のクリップ（音・TTS）には波形（/api/wave）とフェードのつまみ（上の角の白い丸をドラッグ）。
'use strict';
(() => {
  const uidc = p => p + '_' + Math.random().toString(36).slice(2, 8);
  const r6 = x => +(+x).toFixed(6);
  const FR = () => 1 / fps();
  const clips = () => (S.tl.tracks || []).flatMap(tr => (tr.clips || []).map(c => ({ c, tr })));
  const ok = c => movable(c);
  const spans = (c, t) => t > c.start + 1e-6 && t < c.start + c.dur - 1e-6;
  const withLinks = ids => { const out = new Set(); for (const id of ids) for (const x of linkGroup(id)) out.add(x); return [...out]; };
  const srcOf = c => c.type === 'tts' ? ((c.takes || []).find(k => k.id === c.activeTake) || {}).src : Array.isArray(c.src) ? (c.src.length === 1 ? c.src[0] : null) : c.src;

  // ---------- 素材の長さ（スリップの上限に使う。分からなければ上限なし） ----------
  function srcDur(c) {
    if (c.type === 'tts') { const k = (c.takes || []).find(x => x.id === c.activeTake); return k ? +k.dur : null; }
    const s = srcOf(c); if (!s) return null;
    const w = WAVE.get(s); if (w && w.dur) return w.dur;
    const A = S.assets || {};
    for (const k of ['videos', 'audio', 'bgm', 'voice']) { const it = (A[k] || []).find(x => x.path === s); if (it && it.dur) return +it.dur; }
    return null;
  }
  function slipIn(c, in0, dt) {
    const sp = c.type === 'video' ? (c.speed || 1) : 1, d = srcDur(c);
    let v = in0 - dt * sp; if (d != null) v = Math.min(v, Math.max(0, d - c.dur * sp)); return Math.max(0, v);
  }

  // ---------- 分ける ----------
  // 分け方（音・動画は右の素材の場所 in を合わせる・フェードは外側だけ残す・音量の傾き・音ハメの点・リンク）は editor/ops.js の clipEdit（API の split と同じ）
  function splitAt(t, ids) {
    if (!CE().splitList(t, ids, S.linkOn).length) { setStatus($L('ce.noSplit', { t: fmt(t) })); return 0; }
    let n = 0;
    change(() => { n = CE().splitAt(t, ids, S.linkOn); });
    setStatus($L('ce.split', { n, t: fmt(t) })); return n;
  }
  // 再生位置で分ける：選んでいるもの（再生位置にかかるもの）。選んでいなければ、見えているトラックで再生位置にかかるもの全部。all＝いつも全部
  function splitAtPlayhead(all) {
    const t = snapFrame(S.t);
    let ids = all ? [] : selIds().filter(id => spans(findClip(id).clip, t));
    if (!ids.length) ids = CE().idsAt(t, S.hideShy);
    splitAt(t, ids);
  }
  function razorTime(e) {
    const t = timeAt(e), hit = snapping(e) ? snapNear(t, snapTargets(null, true)) : null;
    return { t: hit ? hit[0] : snapFrame(t), hit };
  }
  function razorClick(e, f) {
    const { t } = razorTime(e);
    if (e.shiftKey) splitAt(t, CE().idsAt(t, S.hideShy));
    else splitAt(t, [f.clip.id]);
  }
  function razorHover(e) {
    if (!e.target.closest || !e.target.closest('#laneList .clip')) { showSnap(null); return; }
    const { t, hit } = razorTime(e); showSnap([t, hit ? $t('ce.splitHereSnap', { name: hit[1] }) : $t('ce.splitHere')]);
  }

  // ---------- 消す・詰める ----------
  // 消す・リップル削除（消して、同じトラックの後ろのクリップを消した長さだけ前へ詰める）・隙間を詰める：editor/ops.js の clipEdit（API の delete・ripple・gaps と同じ）
  function deleteSel() {
    const ids = selIds(); if (!ids.length) return;
    let n = 0;
    change(() => { n = CE().deleteClips(ids, S.linkOn); S.sel = null; S.multi = new Set(); });
    setStatus($L('ce.deleted', { n }), 'ok');
  }
  function rippleDelete() {
    const ids = selIds(); if (!CE().withLinks(ids, S.linkOn).some(id => ok(findClip(id).clip))) return;
    let n = 0;
    change(() => { n = CE().rippleDelete(ids, S.linkOn); S.sel = null; S.multi = new Set(); });
    setStatus($L('ce.ripple', { n }));
  }
  // 隙間を詰める：選んだクリップのトラック（なければ選んでいるトラック）で、最初のクリップから後ろを隙間なく並べる。リンクも同じだけ動かす
  function closeGaps() {
    const trs = new Set(selIds().map(id => findClip(id).track)); if (!trs.size && S.selTrack) { const t = S.tl.tracks.find(x => x.id === S.selTrack); if (t) trs.add(t); }
    if (!trs.size) { setStatus($L('ce.gapsPick')); return; }
    let moved = 0;
    change(() => { moved = CE().closeGaps([...trs], S.linkOn); });
    setStatus(moved ? $L('ce.gaps', { n: moved }) : $L('ce.noGaps'));
  }

  // ---------- コピー・貼り付け・複製 ----------
  function grab() {
    const ids = withLinks(selIds()).filter(id => ok(findClip(id).clip)); if (!ids.length) return null;
    const items = ids.map(id => { const f = findClip(id); return { track: f.track.id, kind: kindKey(f.track), clip: JSON.parse(JSON.stringify(f.clip)) }; });
    const t0 = Math.min(...items.map(x => x.clip.start)), t1 = Math.max(...items.map(x => x.clip.start + x.clip.dur));
    return { items, t0, t1 };
  }
  function put(cb, at) {
    const linkMap = {}, ids = [];
    change(() => {
      for (const it of cb.items) {
        const tr = S.tl.tracks.find(t => t.id === it.track) || S.tl.tracks.find(t => kindKey(t) === it.kind); if (!tr) continue;
        const c = JSON.parse(JSON.stringify(it.clip)), dt = r6(at + (it.clip.start - cb.t0)) - c.start;
        c.id = uidc(c.type === 'video' ? 'vid' : c.type); if (c.link) c.link = linkMap[c.link] = linkMap[c.link] || uidc('lk');
        moveClip(c, dt); tr.clips.push(c); tr.clips.sort((a, b) => a.start - b.start); ids.push(c.id);
      }
    });
    S.sel = ids[0] || null; S.multi = new Set(ids); markSel(); showSel();
    return ids.length;
  }
  function copy() { const cb = grab(); if (!cb) { setStatus($L('ce.copyPick')); return; } S.clipboard = cb; setStatus($L('ce.copied', { n: cb.items.length })); refresh(); }  // refresh：「貼り付け」をすぐ押せるように（前は、次に何か選ぶまで押せないままだった）
  function paste() { if (!S.clipboard) { setStatus($L('ce.copyFirst')); return; } const n = put(S.clipboard, snapFrame(S.t)); setStatus($L('ce.pasted', { n, t: fmt(snapFrame(S.t)) })); }
  function duplicate() { const cb = grab(); if (!cb) { setStatus($L('ce.dupPick')); return; } const n = put(cb, cb.t1); setStatus($L('ce.duplicated', { n }), 'ok'); }
  function selectAll() {
    const ids = clips().filter(({ c, tr }) => ok(c) && !(tr.shy && S.hideShy)).map(({ c }) => c.id);
    S.multi = new Set(ids); S.sel = ids[0] || null; if (S.sel) S.selTrack = null; markSel(); showSel(); setStatus($L('ce.selectedAll', { n: ids.length }));
  }

  // ---------- 少し動かす・編集点へ ----------
  function nudge(frames) {
    const ids = withLinks(selIds()).filter(id => ok(findClip(id).clip)); if (!ids.length) return;
    let dt = frames / fps(); const lo = Math.min(...ids.map(id => findClip(id).clip.start)); if (dt < -lo) dt = -lo; if (!dt) return;
    change(() => { for (const id of ids) moveClip(findClip(id).clip, dt); });
    setStatus($L('ce.nudged', { n: ids.length, f: (frames > 0 ? '+' : '') + frames }), 'ok');
  }
  function jumpEdit(dir) {
    const pts = [0, dur()]; for (const { c, tr } of clips()) { if (tr.hidden || (tr.shy && S.hideShy)) continue; pts.push(c.start, c.start + c.dur); }
    const t = S.t, h = 0.5 / fps(), cand = pts.map(snapFrame).filter(x => dir > 0 ? x > t + h : x < t - h).sort((a, b) => a - b);
    const to = dir > 0 ? cand[0] : cand[cand.length - 1]; if (to != null) seek(to);
  }

  // ---------- リンク ----------
  function setLinkOn(v) { S.linkOn = v; try { localStorage.setItem('cc.linkOn', v ? '1' : '0'); } catch (e) { } refresh(); setStatus($L(v ? 'ce.linkOn' : 'ce.linkOff')); }
  function link() {
    const ids = selIds(); if (ids.length < 2) { setStatus($L('ce.linkPick')); return; }
    const lk = uidc('lk'); change(() => { for (const id of ids) findClip(id).clip.link = lk; }); setStatus($L('ce.linked', { n: ids.length }), 'ok');
  }
  function unlink() {
    const ids = withLinks(selIds()).filter(id => findClip(id).clip.link); if (!ids.length) { setStatus($L('ce.unlinkPick')); return; }
    change(() => { for (const id of ids) delete findClip(id).clip.link; }); setStatus($L('ce.unlinked', { n: ids.length }), 'ok');
  }

  // ---------- 動画の音 ----------
  async function extractAudio(c) {
    const s = srcOf(c); if (!s) return { ok: false, error: $t('ce.joinedNoAudio') };
    const r = await api('/api/video_audio', { method: 'POST', body: JSON.stringify({ src: s }), headers: { 'Content-Type': 'application/json' } });
    return r.json();
  }
  // 「動画の音」のトラック（なければ作る。参考の音より上）・音のクリップ・置けないわけ・置き方は editor/ops.js（API の video-audio・place-video と同じ）。
  // ラベル（作品の中身）に絵文字は付けない（2026-11-14 アイコン化）
  // アセット窓の「映像に置く」：音があれば音もリンクして置く（1回の取り消しで両方消える）
  async function placeVideo(c, tr) {
    setStatus($L('ce.placing'));
    let a = null; try { a = await extractAudio(c); } catch (e) { a = { ok: false, error: e.message }; }
    const withAudio = a && a.ok && !a.none;
    change(() => { OPS.placeVideo(S.tl, tr, c, a, opsEnv()); });
    select(c.id); if (S.pane !== 'sel') showPane('sel');
    setStatus(withAudio ? $L('ce.placedLinked') : a && a.none ? $L('ce.placedSilent') : $L('ce.placedNoAudio', { err: (a && a.error) || '' }));
  }
  // 選んだ動画の音を取り出して置く（前に置いた動画・音が別になっていない動画）
  async function videoAudioSel() {
    const vs = selIds().map(findClip).filter(f => f && f.clip.type === 'video');
    if (!vs.length) { setStatus($L('ce.vaPick')); return; }
    let n = 0, skip = [];
    for (const f of vs) {
      const c = f.clip;
      const why = OPS.vaWhy(S.tl, c); if (why) { skip.push($t(why)); continue; }
      setStatus($L('ce.vaExtracting', { name: c.label || c.id }), 'busy');
      let a; try { a = await extractAudio(c); } catch (e) { a = { ok: false, error: e.message }; }
      if (!a.ok) { skip.push(a.error || $t('ce.vaFailed')); continue; } if (a.none) { skip.push($t('ce.vaSilent')); continue; }
      const g = findClip(c.id); if (!g) continue;
      change(() => { OPS.vaPlace(S.tl, g.clip, a, opsEnv()); });
      n++;
    }
    setStatus(skip.length ? $L('ce.vaPlacedSkip', { n, skip: [...new Set(skip)].join($t('sep.list')) }) : $L('ce.vaPlaced', { n }));
  }

  // ---------- 音のクリップの波形・フェード ----------
  const WAVE = new Map(); let waveTimer = null;  // 素材 → {dur, key} か 'wait'
  function wantWave(s) {
    if (WAVE.has(s)) return; WAVE.set(s, 'wait');
    api('/api/wave?src=' + encodeURIComponent(s), { cache: 'no-store' }).then(r => r.json()).then(j => {
      WAVE.set(s, j && j.ok ? j : { none: true });
      clearTimeout(waveTimer); waveTimer = setTimeout(() => { if (!S.drag) buildTimeline(); }, 120);
    }).catch(() => WAVE.set(s, { none: true }));
  }
  function audioLane(c) {
    let h = '';
    const s = srcOf(c);
    if (s) {
      const w = WAVE.get(s); if (!w) wantWave(s);
      if (w && w.key) h += `<div class="wave" style="background-image:url('/api/wave?png=1&k=${w.key}&src=${encodeURIComponent(s)}&token=${TOKEN}');background-size:${(w.dur * S.pps).toFixed(1)}px 100%;background-position:${(-(c.in || 0) * S.pps).toFixed(1)}px 0"></div>`;
    }
    if (movable(c)) {
      const fi = Math.min(c.fade_in || 0, c.dur), fo = Math.min(c.fade_out || 0, c.dur);
      h += `<div class="fade in" style="width:${fi * S.pps}px"></div><div class="fade out" style="width:${fo * S.pps}px"></div>`
        + `<i class="fh l" style="left:${fi * S.pps}px" title="${esc($t('ce.fadeInHandle'))}"></i><i class="fh r" style="right:${fo * S.pps}px" title="${esc($t('ce.fadeOutHandle'))}"></i>`;
    }
    return h;
  }

  // ---------- 道具のバー ----------
  const TOOLS = ['select', 'razor', 'slip'];  // 名前・説明は辞書の tool.<名前>・tool.<名前>.tip
  function setTool(t) {
    S.tool = t; document.body.classList.toggle('tool-razor', t === 'razor'); document.body.classList.toggle('tool-slip', t === 'slip');
    if (t !== 'razor') showSnap(null); refresh();
  }
  function build() {
    const bar = $('cutbar'); if (!bar) return;
    if (!S.tl) { bar.hidden = true; return; }
    // ボタン：data-act → 辞書の ce.btn.<act>（名前）・ce.btn.<act>.tip（ツールチップ）
    const B = a => `<button data-act="${a}" title="${esc($t('ce.btn.' + a + '.tip'))}">${esc($t('ce.btn.' + a))}</button>`;
    bar.innerHTML = `<span class="grp">${TOOLS.map(k => `<button data-tool="${k}" title="${esc($t('tool.' + k + '.tip'))}">${esc($t('tool.' + k))}</button>`).join('')}</span>
      <span class="grp">${B('split')}
        ${B('del')}${B('ripple')}
        ${B('gaps')}</span>
      <span class="grp">${B('copy')}${B('paste')}${B('dup')}</span>
      <span class="grp">${B('linkon')}${B('link')}${B('unlink')}
        ${B('vaudio')}</span>
      <span class="grp">${B('latest')}</span>
      <span class="hint" id="cutHint"></span>`;
    S.cutHintWhy = '';
    if (bar.dataset.bound) { refresh(); return; }  // 言葉を切り替えて作り直したとき：聞き手は付け直さない（バーの要素は同じ）
    bar.dataset.bound = '1';
    bar.addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b || b.disabled) return;
      if (b.dataset.tool) { setTool(b.dataset.tool); return; }
      ({ split: () => splitAtPlayhead(false), del: deleteSel, ripple: rippleDelete, gaps: closeGaps, copy, paste, dup: duplicate,
        linkon: () => setLinkOn(!S.linkOn), link, unlink, vaudio: videoAudioSel, latest: () => { if (window.MITTLER_PLAN) MITTLER_PLAN.adoptAll(null, true); } })[b.dataset.act]();
    });
    // 押せないボタンにマウスを乗せたら、理由をマウスのそばの浮いた札（ツールチップ）に出す。
    // 前は右の説明の欄に出していて、長い理由で行が折り返し、下の画面が押し下げられた（2026-11-26）。説明の欄は選択の数・道具の案内だけにする
    // 押せないボタンはマウスの合図を受けない（editor.css で pointer-events:none）ので、バーの上のマウスの位置から、どのボタンの上かを見る
    const why = e => {
      let t = '', host = null;
      if (e) for (const b of bar.querySelectorAll('button:disabled')) {
        const r = b.getBoundingClientRect();
        if (e.clientX >= r.left && e.clientX < r.right && e.clientY >= r.top && e.clientY < r.bottom) { t = b.dataset.why ? $t('ui.disabledWhy', { why: b.dataset.why }) : ''; host = b.parentElement; break; }
      }
      bar.querySelectorAll('.grp[title]').forEach(g => { if (g !== host) g.removeAttribute('title'); });
      if (host && t) host.title = t;
      S.cutHintWhy = t;
      let tip = $('whyTip');
      if (!tip) { tip = document.createElement('div'); tip.id = 'whyTip'; tip.className = 'whyTip'; tip.setAttribute('role', 'tooltip'); document.body.appendChild(tip); }
      if (!t) { tip.hidden = true; return; }
      tip.textContent = t; tip.hidden = false;
      const w = tip.offsetWidth, h = tip.offsetHeight;
      tip.style.left = Math.max(4, Math.min(innerWidth - w - 4, e.clientX + 12)) + 'px';
      tip.style.top = (e.clientY - h - 10 < 4 ? e.clientY + 18 : e.clientY - h - 10) + 'px';  // ふつうはマウスの上、上に余白が無ければ下
    };
    bar.addEventListener('mousemove', why); bar.addEventListener('mouseleave', () => why(null));
    refresh();
  }
  MITTLER_I18N.onChange(() => { if ($('cutbar') && $('cutbar').dataset.bound) build(); });  // 言葉を切り替えたら作り直す
  function refresh() {
    const bar = $('cutbar'); if (!bar || !bar.firstChild) return;
    const n = selIds().length, sel = selIds().map(findClip).filter(Boolean);
    bar.querySelectorAll('[data-tool]').forEach(b => b.classList.toggle('on', (S.tool || 'select') === b.dataset.tool));
    const q = a => bar.querySelector(`[data-act="${a}"]`);
    q('linkon').classList.toggle('on', !!S.linkOn);
    // 押せないボタンには理由を付ける（ツールチップの頭に「押せない：…」。マウスを乗せると右の説明の欄にも出る。ui.js の MITTLER_SET_DISABLED）
    const dis = (a, why) => MITTLER_SET_DISABLED(q(a), why);
    for (const a of ['del', 'ripple', 'copy', 'dup']) dis(a, n ? '' : $t('why.noSel'));
    dis('paste', S.clipboard ? '' : $t('why.noCopy'));
    dis('link', n < 2 ? $t('why.link2') : '');
    dis('unlink', sel.some(f => f.clip.link) ? '' : $t(n ? 'why.notLinked' : 'why.noLinkedSel'));
    dis('vaudio', sel.some(f => f.clip.type === 'video') ? '' : $t('why.noVideo'));
    dis('gaps', !n && !S.selTrack ? $t('why.noGapsSel') : '');
    const nl = window.MITTLER_PLAN && MITTLER_PLAN.pendingAdopt ? MITTLER_PLAN.pendingAdopt(null, true).length : 0;
    dis('latest', nl ? '' : $t('why.noNewTakes')); q('latest').textContent = nl ? $t('ce.btn.latestN', { n: nl }) : $t('ce.btn.latest');
    S.cutHintBase = n ? $t(n > 1 ? 'ce.selN' : 'ce.sel1', { n }) : (S.tool === 'razor' ? $t('ce.hintRazor') : S.tool === 'slip' ? $t('ce.hintSlip') : '');
    $('cutHint').textContent = S.cutHintBase;
  }

  window.MITTLER_CUT = { splitAt, splitAtPlayhead, razorClick, razorHover, deleteSel, rippleDelete, closeGaps, copy, paste, duplicate, selectAll, nudge, jumpEdit,
    link, unlink, setLinkOn, placeVideo, videoAudioSel, audioLane, slipIn, srcDur, setTool, refresh, waves: WAVE, init: build };
})();
