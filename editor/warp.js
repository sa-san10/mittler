// Mittler 編集画面：映像クリップ（🎞️）の右の欄と、速さ・音ハメ（時間の付け替え warp）。plan.js のあとに読む。
// 映像クリップ：{type:'video', src, start, dur, in（素材の頭）, speed（一定の速さ）, land, curve, label, upscale（🏆 のアップスケール anime・real。無ければ作品の設定）,
//   grade（🎨 クリップの色 {b, c, v, s}。欄とつまみは editor.js の clipGradeHTML・bindClipGrade）,
//   warp: 文字列（表のファイル。偽マリアMV の取り込み。読むだけ）か
//         {points:[[クリップの頭からの秒, 動画の秒], …], smooth（秒）, auto:{音ハメの設定}, accents:[[動画の秒, 強さ, 種類], …], pairs:[[動画の秒, クリップの頭からの秒], …]}}
// 点のあいだは直線、外は端の傾きでのばし、smooth の幅で9点の平均（計算は editor/calc.js の warpMap＝server.js と同じもの。pyengine/mittler/warp.py と同じ式）。点の warp があるときは in・speed は使わない。
// 🎵 音ハメ（自動）：サーバーの /api/warp/auto → 描画サーバーの /warp（pyengine/mittler/onbeat.py：Attention の beatwarp.py。動きの止まり・切り返しを拍に合わせる）。
'use strict';
(() => {
  const W = window.MITTLER_WARP = {};
  const isPts = c => !!(c && c.warp && typeof c.warp === 'object' && Array.isArray(c.warp.points) && c.warp.points.length);
  W.isPts = isPts;
  // 点の計算は editor/calc.js（サーバーの server.js と同じもの。Python の pyengine/mittler/warp.py と同じことは tools/smoke_same.py が確かめる）
  const { sorted, lin } = window.MITTLER_CALC;
  W.map = window.MITTLER_CALC.warpMap;
  // 表のファイル（読むだけ）：一度読んで覚えておく。np.interp と同じく表の外は端の値、in を足す
  const tabs = {};
  function table(rel) {
    if (tabs[rel] !== undefined) return tabs[rel];
    tabs[rel] = null;
    fetch(rootUrl(rel)).then(r => r.json()).then(d => { tabs[rel] = (d.table || []).map(r => [+r[0], +r[1]]); buildTimeline(); if (S.sel) showSelSafe(); }).catch(() => { tabs[rel] = []; });
    return null;
  }
  function interp(a, u) { if (!a.length) return 0; if (u <= a[0][0]) return a[0][1]; if (u >= a[a.length - 1][0]) return a[a.length - 1][1]; return lin(a, u); }
  // クリップの頭から t 秒で映す動画の秒（分からなければ null）
  W.srcAt = (c, t) => {
    if (isPts(c)) return W.map(c.warp, t);
    if (typeof c.warp === 'string') { const a = table(c.warp); return a && a.length ? interp(a, t) + (c.in || 0) : null; }
    return (c.in || 0) + t * (c.speed || 1);
  };
  W.speedAt = (c, t) => { const h = 1 / 240, a = W.srcAt(c, t - h), b = W.srcAt(c, t + h); return a == null || b == null ? null : (b - a) / (2 * h); };

  // ---------- タイムラインのクリップに速さの線（0.5×〜2× を下〜上、真ん中の点線が 1×） ----------
  W.lane = c => {
    if (!c.warp && (c.speed || 1) === 1) return '';
    if (!c.warp) return `<span class="spdb">${+(c.speed || 1).toFixed(3)}×</span>`;
    const w = Math.max(3, c.dur * S.pps), n = Math.max(2, Math.min(240, Math.round(w / 3)));
    const pts = []; let lo = Infinity, hi = 0;
    for (let i = 0; i <= n; i++) {
      const t = c.dur * i / n, v = W.speedAt(c, t); if (v == null) return `<span class="spdb">${MITTLER_ICON('music')}</span>`;
      lo = Math.min(lo, v); hi = Math.max(hi, v);
      const y = 50 - Math.max(-1, Math.min(1, Math.log2(Math.max(v, 1e-3)))) * 40;
      pts.push(`${(100 * i / n).toFixed(2)},${y.toFixed(1)}`);
    }
    return `<svg class="spd" viewBox="0 0 100 100" preserveAspectRatio="none"><line x1="0" y1="50" x2="100" y2="50"/><polyline points="${pts.join(' ')}"/></svg>`
      + `<span class="spdb">${MITTLER_ICON('music')} ${lo.toFixed(2)}–${hi.toFixed(2)}×</span>`;
  };

  // ---------- 拍（タイムラインのビート → クリップの頭からの秒） ----------
  // 拍の計算・音ハメの設定の既定と並びは editor/ops.js（API の onbeat と同じもの）
  const clipBeats = (c, half) => OPS.clipBeats(S.tl, c, half);

  // ---------- 右の欄 ----------
  const { AUTO_DEF, AUTO_FIELDS, advOf } = OPS;  // 欄の名前は辞書の wp.a.<鍵>
  window.addEventListener('mouseup', () => W._up && W._up());
  const energy = {};  // 素材ごとの動きの量（音ハメのときにもらう。グラフの右に出す）
  const prevInspect = window.MITTLER_INSPECT;
  window.MITTLER_INSPECT = (c, f) => {
    if (c.type !== 'video') return prevInspect ? prevInspect(c, f) : false;
    inspect(c, f); return true;
  };
  const r3 = v => +(+v).toFixed(3);
  // ---------- ⟷ フッテージを伸ばす：次のクリップの頭まで・動画化予定の長さ・秒数 に、ゆっくりにして（速さ）か、最後のコマで止めて ----------
  // 次のクリップの頭までの長さ・予定の終わりまでの長さ・伸ばし方は editor/ops.js の clipEdit（API の stretch と同じ）
  const nextTo = x => CE().nextTo(x), planTo = x => CE().planTo(x);
  const selVideos = () => selIds().map(findClip).filter(g => g && g.clip.type === 'video' && g.clip.cut == null).map(g => g.clip);
  function stretchHTML(c) {
    const nt = nextTo(c), pt = planTo(c), def = nt && nt > c.dur + 1e-6 ? 'next' : pt && pt > c.dur + 1e-6 ? 'plan' : 'sec', n = selVideos().length;
    const T = (k, v) => $t('wp.' + k, v);
    return `<div class="planSec stretch"><h3>${T('stretch')}</h3>
      <div class="form"><label>${T('to')}</label><select data-x="to">
          <option value="next" ${nt ? '' : 'disabled'} ${def === 'next' ? 'selected' : ''}>${esc(T('toNext', { v: nt ? $t('as.sec', { s: r3(nt) }) : T('noNext') }))}</option>
          <option value="plan" ${pt ? '' : 'disabled'} ${def === 'plan' ? 'selected' : ''}>${esc(T('toPlan', { v: pt ? $t('as.sec', { s: r3(pt) }) : T('noPlan') }))}</option>
          <option value="sec" ${def === 'sec' ? 'selected' : ''}>${T('toSec')}</option></select>
        <label>${T('lenSec')}</label><input data-x="sec" type="number" step="${1 / fps()}" min="${1 / fps()}" value="${r3(def === 'next' ? nt : def === 'plan' ? pt : c.dur)}"></div>
      <div class="btns"><button data-x="slow" ${c.warp ? `disabled title="${esc(T('slowNo'))}"` : ''}>${T('slow')}</button>
        <button data-x="hold">${T('hold')}</button></div>
      <div class="empty xhint"></div>
      ${n > 1 ? `<div class="btns"><button data-x="slowAll">${T('slowAll', { n })}</button><button data-x="holdAll">${T('holdAll', { n })}</button></div>` : ''}
    </div>`;
  }
  // x を長さ T に（how：slow＝速さを落として同じ中身を T に／hold＝そのまま長くして、素材が尽きたら最後のコマで止まる。リンクした音も同じ終わりまで）
  const stretch = (x, T, how) => CE().stretch(x, T, how, S.linkOn);
  function bindStretch(el, c) {
    const sec = el.querySelector('.stretch'); if (!sec) return;
    const to = sec.querySelector('[data-x="to"]'), inp = sec.querySelector('[data-x="sec"]'), hint = sec.querySelector('.xhint');
    const target = () => { const v = to.value === 'next' ? nextTo(c) : to.value === 'plan' ? planTo(c) : parseFloat(inp.value); return isFinite(v) ? v : null; };
    const show = () => {
      const T = target(); if (to.value !== 'sec' && T) inp.value = r3(T);
      if (!T) { hint.textContent = ''; return; }
      const sp = (c.speed || 1) * c.dur / T, d = srcDur(c), have = d != null ? d - (c.in || 0) : null;
      const left = have != null ? have / (c.speed || 1) : null;
      hint.textContent = $t('wp.hint', { a: r3(c.dur), b: r3(T), s0: r3(c.speed || 1), s1: r3(sp) }) +
        (left != null ? (left < T ? $t('wp.hintShort', { left: r3(left), miss: r3(T - left) }) : $t('wp.hintEnough', { left: r3(left) })) : '');
    };
    to.onchange = show; inp.oninput = () => { to.value = 'sec'; show(); }; show();
    const linkedAudio = x => linkGroup(x.id).some(id => { const g = findClip(id); return g && g.clip.type === 'audio'; });
    const one = how => {
      const T = target(); if (!T) return;
      change(() => { stretch(c, T, how); });
      setStatus($LJ($L(how === 'slow' ? 'wp.stretchedSlow' : 'wp.stretchedHold', { t: r3(T), s: r3(c.speed || 1) }), how === 'slow' && linkedAudio(c) ? $L('wp.audioKept') : ''));
    };
    sec.querySelector('[data-x="slow"]').onclick = () => one('slow');
    sec.querySelector('[data-x="hold"]').onclick = () => one('hold');
    const all = how => {
      const xs = selVideos().map(x => [x, nextTo(x)]).filter(([x, T]) => T && Math.abs(T - x.dur) > 1e-6 && !(how === 'slow' && x.warp));
      if (!xs.length) { setStatus($L('wp.nothing')); return; }
      change(() => { for (const [x, T] of xs) stretch(x, T, how); });
      setStatus($L(how === 'slow' ? 'wp.stretchedAllSlow' : 'wp.stretchedAllHold', { n: xs.length }));
    };
    const sa = sec.querySelector('[data-x="slowAll"]'), ha = sec.querySelector('[data-x="holdAll"]');
    if (sa) sa.onclick = () => all('slow'); if (ha) ha.onclick = () => all('hold');
  }
  // 素材の長さ（アセットの一覧・波形の情報から。分からなければ null）
  const srcDur = c => (window.MITTLER_CUT && MITTLER_CUT.srcDur) ? MITTLER_CUT.srcDur(c) : null;
  // 作品のアップスケール（🏆 の窓で選ぶ。タイムラインの settings.master.upscale。書いてなければ PC の設定＝ふつうはアニメ）。
  // 作品が「なし（60fps だけ）」なら、ここでアニメ・実写を選んでも使われない（2026-10-31）
  // 言葉は 🏆 の窓の「画質」と同じ（標準／高画質（アニメ）／高画質（実写）。2026-10-31 夜、窓の作り直し）
  const upWork = () => $t({ anime: 'wp.up.anime', real: 'wp.up.real', none: 'wp.up.noneWork' }[((S.tl.settings || {}).master || {}).upscale] || 'wp.up.anime');
  function inspect(c, f) {
    const el = $('sel'); el.className = '';
    const pts = isPts(c), file = typeof c.warp === 'string', a = Object.assign({}, AUTO_DEF, (pts && c.warp.auto) || {});
    const movable = c.cut == null;
    const src = Array.isArray(c.src) ? c.src.join(', ') : c.src;
    const T = (k, v) => $t('wp.' + k, v);
    el.innerHTML = `<div class="metaRow"><b>${T('title')}</b>${esc(f.track.name || f.track.id)}${c.cut != null ? esc($t('sep.bar') + $t('cut.label', { label: c.cut })) : ''}</div>
      <div class="btns"><button data-act="off">${$t(c.disabled ? 'sel.enable' : 'sel.disable')}</button><button data-act="del">${$t('sel.delete')}</button></div>
      <img class="ithumb" src="/api/thumb?clip=${encodeURIComponent(c.id)}&v=${S.edits}&token=${TOKEN}">
      <div class="metaRow"><b>${$t('au.src')}</b>${esc(src)}</div>
      <div class="form"><label>${$t('trk.name')}</label><input data-k="label" type="text" value="${esc(c.label || '')}">
        ${movable ? `<label>${$t('f.start')}</label><input data-k="start" type="number" step="${1 / fps()}" value="${r3(c.start)}">
        <label>${$t('f.dur')}</label><input data-k="dur" type="number" step="${1 / fps()}" min="${1 / fps()}" value="${r3(c.dur)}">` : ''}
        <label>${T('in')}</label><input data-k="in" type="number" step="0.01" min="0" value="${r3(c.in || 0)}" ${pts ? `disabled title="${esc(T('inNo'))}"` : ''}>
        <label>${T('speed')}</label><input data-k="speed" type="number" step="0.05" min="0.05" value="${r3(c.speed || 1)}" ${c.warp ? `disabled title="${esc(T('speedNo'))}"` : ''}>
        <label title="${esc(T('upscale.tip1'))}">${T('upscale')}</label><select data-k="upscale" title="${esc(T('upscale.tip2'))}">
          ${[['', T('up.work', { v: upWork() })], ['anime', T('up.anime')], ['real', T('up.real')]].map(([v, n]) => `<option value="${v}" ${(c.upscale || '') === v ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
      </div>
      ${clipGradeHTML(c)}
      ${window.MITTLER_CUTMETA ? MITTLER_CUTMETA.clipHTML(c) : ''}
      ${movable ? stretchHTML(c) : ''}
      <div class="planSec"><h3>${T('beatSync')}</h3>
        ${pts && c.warp.auto && c.warp.auto.note ? `<div class="empty">${MITTLER_ICON('sticky-note')} ${esc(c.warp.auto.note)}</div>` : ''}
        ${!c.warp ? `<div class="empty">${T('constant', { s: r3(c.speed || 1) })}</div>` : ''}
        ${file ? `<div class="empty">${T('file1')}<code>${esc(c.warp)}</code>${T('file2')}</div>` : ''}
        ${c.warp ? `<canvas class="wgraph" height="256"></canvas><div class="wread empty">&nbsp;</div>` : ''}
        ${pts ? `<div class="empty whelp">${T('help')}</div>` : ''}
        <div class="btns">
          <button class="primary" data-act="auto">${T(pts && c.warp.auto ? 'redo' : 'auto')}</button>
          ${!c.warp ? `<button data-act="manual">${T('manual')}</button>` : ''}
          ${file ? `<button data-act="topts">${T('topts')}</button>` : ''}
          ${c.warp ? `<button data-act="clear">${T('clear')}</button>` : ''}
          <span class="jobst"></span></div>
        <details class="wauto"${pts ? '' : ' open'}><summary class="empty">${T('settings')}</summary><div class="form">
          ${AUTO_FIELDS.map(([k, st]) => `<label>${T('a.' + k)}</label><input data-a="${k}" type="number" step="${st}" value="${a[k]}">`).join('')}
          <label>${T('a.half')}</label><input data-a="half" type="checkbox" ${a.half ? 'checked' : ''}>
          <label>${T('a.end')}</label><input data-a="end" type="checkbox" ${a.end ? 'checked' : ''}>
        </div><label class="mlab">${T('adv')}</label>
        <textarea data-adv rows="3" spellcheck="false">${esc(JSON.stringify(advOf(a)))}</textarea>
        <div class="empty">${T('advNote', { s: r3(c.speed || 1), n: clipBeats(c, false).length })}</div></details>
      </div>
      <details><summary class="empty">${T('json')}</summary><pre>${esc(JSON.stringify(c, null, 2))}</pre></details>`;
    el.querySelector('[data-act="off"]').onclick = () => change(() => { if (c.disabled) delete c.disabled; else c.disabled = true; });
    el.querySelector('[data-act="del"]').onclick = () => deleteClip(c.id);
    if (movable) bindStretch(el, c);
    bindClipGrade(el, c);  // 🎨 クリップの色（editor.js）
    if (window.MITTLER_CUTMETA) MITTLER_CUTMETA.bindClip(el, c);  // ✂ この範囲をカットにする（cutmeta.js）
    el.querySelector('[data-k="label"]').onchange = ev => change(() => { c.label = ev.target.value; }, { keepForm: true });
    // 🏆 アップスケール（クリップの upscale。空＝作品の設定 settings.master.upscale）
    el.querySelector('[data-k="upscale"]').onchange = ev => change(() => { if (ev.target.value) c.upscale = ev.target.value; else delete c.upscale; }, { keepForm: true });
    for (const k of ['start', 'dur', 'in', 'speed']) {
      const inp = el.querySelector(`[data-k="${k}"]`); if (!inp) continue;
      inp.onchange = () => {
        const v = parseFloat(inp.value); if (!isFinite(v)) return;
        if (k === 'start') change(() => setClipStart(c, v));  // コマにそろえる・0 より前にしない（editor.js）
        else if (k === 'dur') change(() => setClipDur(c, v));  // コマにそろえる・1 コマより短くしない
        else change(() => { c[k] = +Math.max(k === 'speed' ? 0.05 : 0, v).toFixed(6); if (k === 'speed' && c[k] === 1) delete c.speed; });
      };
    }
    // 音ハメの設定：前の設定（取り込んだ元の値・メモ）に、欄の値と「そのほかの設定」を重ねる
    // 重ね方は editor/ops.js の warpAutoOpts（API の onbeat と同じ）
    const opts = () => {
      const fields = {};
      for (const inp of el.querySelectorAll('[data-a]')) fields[inp.dataset.a] = inp.type === 'checkbox' ? inp.checked : parseFloat(inp.value);
      const ta = el.querySelector('[data-adv]'); let adv = {};
      try { adv = ta.value.trim() ? JSON.parse(ta.value) : {}; ta.classList.remove('bad'); } catch (e) { ta.classList.add('bad'); return null; }
      return OPS.warpAutoOpts(c, fields, adv);
    };
    el.querySelector('[data-act="auto"]').onclick = () => { const o = opts(); if (o) runAuto(c, o, el); else el.querySelector('.jobst').textContent = $t('wp.advBad'); };
    el.querySelector('[data-adv]').onchange = () => { const o = opts(); if (o && isPts(c)) change(() => { c.warp.auto = o; }, { keepForm: true }); };
    const bm = el.querySelector('[data-act="manual"]');
    if (bm) bm.onclick = () => change(() => { const s0 = c.in || 0, v = c.speed || 1; c.warp = { points: [[0, s0], [r3(c.dur), r3(s0 + v * c.dur)]], smooth: 0 }; });
    const bt = el.querySelector('[data-act="topts"]');
    if (bt) bt.onclick = () => {
      const tb = table(c.warp); if (!tb || !tb.length) return;
      const pts2 = simplify(tb.map(r => [r[0], r[1] + (c.in || 0)]), 0.25 / fps());
      change(() => { c.warp = { points: pts2.map(p => [r3(p[0]), +p[1].toFixed(4)]), smooth: 0, from_file: c.warp }; });
    };
    const bc = el.querySelector('[data-act="clear"]');
    if (bc) bc.onclick = () => change(() => { const s0 = W.srcAt(c, 0); if (s0 != null) c.in = +Math.max(0, s0).toFixed(6); delete c.warp; });
    if (c.warp) graph(c, el);
  }

  async function runAuto(c, o, el) {
    const st = el.querySelector('.jobst'), btn = el.querySelector('[data-act="auto"]');
    // 頼みの中身（拍・頭の秒：前の音ハメのときの値 auto.in。やり直すたびに前の結果の頭へずれていかないように）と結果の入れ方は editor/ops.js（API の onbeat と同じ）
    const q = OPS.warpAutoQuery(S.tl, c, o);
    if (!q) { st.textContent = $t('wp.noBeats'); return; }
    btn.disabled = true; st.textContent = $t('wp.working');
    let r;
    try { r = await (await api('/api/warp/auto', { method: 'POST', body: JSON.stringify({ q }), headers: { 'Content-Type': 'application/json' } })).json(); }
    catch (e) { r = { ok: false, error: String(e) }; }
    btn.disabled = false;
    if (!r.ok) { st.textContent = $t('np.failed', { err: r.error || '' }); return; }
    energy[q.src] = r.energy;
    const f = findClip(c.id); if (!f) return;
    const cc = f.clip;
    change(() => { OPS.warpAutoApply(cc, r, o); });
    setStatus($L(r.method === 'flow' ? 'wp.doneFlow' : 'wp.doneDiff', { n: r.pairs.length, where: r.where }));
  }

  // 折れ線を少ない点に（Ramer–Douglas–Peucker、縦のずれ eps 秒まで）
  function simplify(a, eps) {
    if (a.length <= 2) return a;
    let im = 0, dm = 0; const [x0, y0] = a[0], [x1, y1] = a[a.length - 1];
    for (let i = 1; i < a.length - 1; i++) { const y = y0 + (y1 - y0) * (a[i][0] - x0) / ((x1 - x0) || 1); const d = Math.abs(a[i][1] - y); if (d > dm) { dm = d; im = i; } }
    if (dm <= eps) return [a[0], a[a.length - 1]];
    return simplify(a.slice(0, im + 1), eps).slice(0, -1).concat(simplify(a.slice(im), eps));
  }

  // ---------- グラフ：上＝曲の時刻（横）と映す動画の秒（縦）、下＝速さ ----------
  function graph(c, el) {
    const cv = el.querySelector('.wgraph'), rd = el.querySelector('.wread'); if (!cv) return;
    const edit = isPts(c), dpr = window.devicePixelRatio || 1;
    const Wd = Math.max(200, cv.parentElement.clientWidth - 2), H = 256, TOP = 160, L = 34, R = 8, T = 8, SB = 22;
    cv.width = Wd * dpr; cv.height = H * dpr; cv.style.width = Wd + 'px'; cv.style.height = H + 'px';
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    let pts = edit ? sorted(c.warp.points) : null, drag = -1, hover = -1;
    const wObj = () => edit ? { points: pts, smooth: c.warp.smooth } : null;
    const srcAt = t => edit ? W.map(wObj(), t) : W.srcAt(c, t);
    const beats = clipBeats(c, !!(edit && c.warp.auto && c.warp.auto.half));
    const accents = (edit && c.warp.accents) || [];
    const pairs = (edit && c.warp.pairs) || [];
    let y0, y1;
    function range() {
      const vs = []; for (let i = 0; i <= 60; i++) { const v = srcAt(c.dur * i / 60); if (v != null) vs.push(v); }
      if (!vs.length) vs.push(0, 1);
      y0 = Math.min(...vs); y1 = Math.max(...vs); const pad = Math.max(0.15, (y1 - y0) * 0.08); y0 -= pad; y1 += pad;
    }
    range();
    const X = t => L + (Wd - L - R) * t / c.dur, Tx = x => (x - L) / (Wd - L - R) * c.dur;
    const Y = s => T + (TOP - T) * (1 - (s - y0) / (y1 - y0)), Sy = y => y0 + (1 - (y - T) / (TOP - T)) * (y1 - y0);
    const SY0 = TOP + 14, SY1 = H - 4;  // 速さの帯
    const VY = v => SY1 - (SY1 - SY0) * (Math.max(-1.2, Math.min(1.2, Math.log2(Math.max(v, 1e-3)))) + 1.2) / 2.4;
    const lo = (edit && c.warp.auto && c.warp.auto.min) || 0.5, hi = (edit && c.warp.auto && c.warp.auto.max) || 2.0;
    function draw() {
      // 色はテーマのトークンから（editor.css の頭。ライトでもダークでも読める）。テーマが変わったら描き直す（下の mittler-theme）
      const K = (n, fb) => (window.MITTLER_THEME ? MITTLER_THEME.token(n, fb) : fb);
      g.clearRect(0, 0, Wd, H); g.font = '10px Consolas, monospace';
      g.fillStyle = K('--inset', '#15161a'); g.fillRect(L, T, Wd - L - R, TOP - T); g.fillRect(L, SY0, Wd - L - R, SY1 - SY0);
      for (const [t, w, down] of beats) { if (t < 0 || t > c.dur) continue; g.strokeStyle = w < 1 ? K('--line', '#2c3340') : down ? K('--dim', '#5a6a88') : K('--line2', '#3a4558'); g.beginPath(); g.moveTo(X(t), T); g.lineTo(X(t), TOP); g.moveTo(X(t), SY0); g.lineTo(X(t), SY1); g.stroke(); }
      for (const [s, sc] of accents) { if (s < y0 || s > y1) continue; g.strokeStyle = `rgba(240,150,50,${0.25 + 0.6 * sc})`; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(L, Y(s)); g.lineTo(Wd - R, Y(s)); g.stroke(); g.setLineDash([]); }
      const en = energy[Array.isArray(c.src) ? c.src[0] : c.src];
      if (en && en.length) {  // 動きの量（右の端、素材の秒ごと）
        const em = Math.max(...en.map(e => e[1])) || 1; g.strokeStyle = 'rgba(90,160,255,.55)'; g.beginPath(); let st = false;
        for (const [s, e] of en) { if (s < y0 || s > y1) continue; const x = Wd - R - 26 * e / em; if (!st) { g.moveTo(x, Y(s)); st = true; } else g.lineTo(x, Y(s)); } g.stroke();
      }
      // 対応：曲の時刻 → 動画の秒
      g.strokeStyle = K('--info', '#4fc3f7'); g.lineWidth = 2; g.beginPath();
      for (let i = 0; i <= 200; i++) { const t = c.dur * i / 200, s = srcAt(t); if (s == null) continue; i ? g.lineTo(X(t), Y(s)) : g.moveTo(X(t), Y(s)); }
      g.stroke(); g.lineWidth = 1;
      for (const [s, t] of pairs) { g.strokeStyle = K('--ok', '#4caf50'); g.beginPath(); g.arc(X(t), Y(s), 7, 0, Math.PI * 2); g.stroke(); }
      if (pts) pts.forEach((p, i) => { g.fillStyle = i === drag ? K('--accent', '#ffd54f') : i === hover ? K('--focus', '#fff59d') : K('--strong', '#ffffff'); g.beginPath(); g.arc(X(p[0]), Y(p[1]), 4.5, 0, Math.PI * 2); g.fill(); });
      // 速さ
      g.strokeStyle = K('--faint', '#555c6a'); g.setLineDash([2, 3]); for (const v of [lo, 1, hi]) { g.beginPath(); g.moveTo(L, VY(v)); g.lineTo(Wd - R, VY(v)); g.stroke(); } g.setLineDash([]);
      g.beginPath(); let prev = null;
      for (let i = 0; i <= 200; i++) {
        const t = c.dur * i / 200, h = c.dur / 400, a = srcAt(t - h), b = srcAt(t + h); if (a == null || b == null) continue;
        const v = (b - a) / (2 * h); g.strokeStyle = (v < lo - 0.01 || v > hi + 0.01) ? K('--bad', '#ef5350') : K('--ok', '#81c784');
        if (prev) { g.beginPath(); g.moveTo(prev[0], prev[1]); g.lineTo(X(t), VY(v)); g.stroke(); } prev = [X(t), VY(v)];
      }
      g.fillStyle = K('--dim', '#8a90a0'); g.textAlign = 'right';
      g.fillText(y1.toFixed(1), L - 3, T + 8); g.fillText(y0.toFixed(1), L - 3, TOP); g.fillText($t('wp.g.src'), L - 3, (T + TOP) / 2);
      for (const v of [lo, 1, hi]) g.fillText(v + '×', L - 3, VY(v) + 3);
      g.textAlign = 'left'; g.fillText($t('wp.g.song', { t: c.start.toFixed(2) }), L + 2, TOP + 11); g.textAlign = 'right'; g.fillText(`${(c.start + c.dur).toFixed(2)} s`, Wd - R, TOP + 11); g.textAlign = 'left';
    }
    draw();
    // テーマ・言葉が変わったら描き直す（欄が作り直されて外れたら聞くのをやめる。canvas に描いた字も今の言葉に）
    const onTheme = () => { if (cv.isConnected) draw(); else { window.removeEventListener('mittler-theme', onTheme); window.removeEventListener('mittler-lang', onTheme); } };
    window.addEventListener('mittler-theme', onTheme); window.addEventListener('mittler-lang', onTheme);
    cv.mittlerMap = { X: t => X(t), Y: s => Y(s), pts: () => pts };  // 動作確認（tools/smoke_warp.py）が点の場所を知る用
    const pos = e => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    const near = (x, y) => { if (!pts) return -1; let best = -1, bd = 9; pts.forEach((p, i) => { const d = Math.hypot(X(p[0]) - x, Y(p[1]) - y); if (d < bd) { bd = d; best = i; } }); return best; };
    const read = (x, y) => {
      const t = Math.max(0, Math.min(c.dur, Tx(x))), s = srcAt(t), v = W.speedAt(edit ? { warp: wObj() } : c, t);
      rd.textContent = $t('wp.g.read', { t: (c.start + t).toFixed(3), s: s == null ? '?' : s.toFixed(3), v: v == null ? '?' : v.toFixed(2) });
    };
    cv.addEventListener('mousemove', e => {
      const [x, y] = pos(e); read(x, y);
      if (drag < 0) { const h = near(x, y); if (h !== hover) { hover = h; cv.style.cursor = h >= 0 ? 'grab' : 'crosshair'; draw(); } return; }
      let t = Tx(x), s = Sy(y);
      if (!e.altKey) {  // 拍・アクセントに吸いつく（6px 以内）
        for (const [bt] of beats) if (Math.abs(X(bt) - x) < 6) { t = bt; break; }
        for (const [as] of accents) if (Math.abs(Y(as) - y) < 6) { s = as; break; }
      }
      const pv = pts[drag - 1], nx = pts[drag + 1], dt = 1 / fps();
      t = Math.max(pv ? pv[0] + dt : -c.dur, Math.min(nx ? nx[0] - dt : c.dur * 2, t));
      s = Math.max(pv ? pv[1] + 0.001 : 0, Math.min(nx ? nx[1] - 0.001 : Infinity, s));  // 戻らない（逆再生しない）
      pts[drag] = [+t.toFixed(4), +s.toFixed(4)]; draw();
    });
    cv.addEventListener('mousedown', e => { if (!pts || e.button !== 0) return; const [x, y] = pos(e); drag = near(x, y); if (drag >= 0) { cv.style.cursor = 'grabbing'; e.preventDefault(); } });
    const commit = () => {
      const p2 = pts.map(p => [+p[0].toFixed(4), +p[1].toFixed(4)]), f = findClip(c.id); if (!f || !isPts(f.clip)) return;
      const cc = f.clip; c = cc;
      change(() => { cc.warp.points = p2; cc.in = +Math.max(0, W.map(cc.warp, 0)).toFixed(6); }, { keepForm: true });
      range(); draw();
    };
    W._up = () => { if (drag < 0) return; drag = -1; cv.style.cursor = 'grab'; commit(); };  // ドラッグの終わり（グラフの外で離しても）
    cv.addEventListener('dblclick', e => {
      if (!pts) return; const [x] = pos(e); const t = Math.max(0, Math.min(c.dur, Tx(x)));
      if (pts.some(p => Math.abs(X(p[0]) - x) < 6)) return;
      pts.push([+t.toFixed(4), +srcAt(t).toFixed(4)]); pts = sorted(pts); commit();
    });
    cv.addEventListener('contextmenu', e => {
      if (!pts) return; const [x, y] = pos(e); const i = near(x, y); if (i < 0) return; e.preventDefault();
      if (pts.length <= 2) { setStatus($L('wp.min2'), 'warn'); return; }
      pts.splice(i, 1); commit();
    });
    cv.addEventListener('mouseleave', () => { if (drag < 0 && hover >= 0) { hover = -1; draw(); } });
  }
})();
