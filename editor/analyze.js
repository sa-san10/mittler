// Mittler 編集画面：🔬 クリップの解析（タイムラインのクリップを右クリック）。editor.js のあとに読む。
// サーバーの /api/analyze に頼む → サーバーの PC の解析用の python（PC の設定 mittler.analysis.python・settings.analysis_python。GPU の torch などを入れたもの）で pyengine/mittler/analyze.py → 作品の assets/analysis/<…>/ に書く。
// 終わったら、タイムラインに入れられるものは入れる（拍→ビートのメタデータ、文字起こし→歌詞・セリフのメタデータ、ボーカルと伴奏→ミュートの音のトラック）。
// 入れられないもの（ポーズ・マスク・切り抜き）は「アセットに回収した」と知らせる。Claude Code から tools/mittler_api.py の analyze で頼んだものも、ここが入れる。
// 画面の言葉は辞書の an2.*。解析の種類の名前は analyze_kinds.json の labels（日本語）・labels_en（英語）
'use strict';
(() => {
  // 解析の種類（クリップの種類ごと）とメニューの名前：一覧は pyengine/mittler/analyze_kinds.json の1か所。サーバーの GET /api/analyze の kinds・labels・labels_en で受け取る
  const LABEL = {}, LABEL_EN = {}, BY_TYPE = {};
  const takeKinds = d => { if (d && d.kinds) Object.assign(BY_TYPE, d.kinds); if (d && d.labels) Object.assign(LABEL, d.labels); if (d && d.labels_en) Object.assign(LABEL_EN, d.labels_en); };
  const lab = k => (MITTLER_I18N.lang === 'en' && LABEL_EN[k]) || LABEL[k] || k;  // 今の言葉の名前
  (async function loadKinds(n) {
    try { takeKinds(await (await fetch('/api/analyze', { cache: 'no-store' })).json()); } catch (e) { if (n < 20) setTimeout(() => loadKinds(n + 1), 3000); }
  })(0);
  const uid = p => p + '_' + Math.random().toString(36).slice(2, 8);
  let menu = null, timer = null; const applying = new Set();

  // ---------- 右クリックのメニュー ----------
  function closeMenu() { if (menu) { menu.remove(); menu = null; } }
  $('lanes').addEventListener('contextmenu', e => {
    const cl = e.target.closest('.clip'); if (!cl || !S.tl) return;
    e.preventDefault(); const f = findClip(cl.dataset.id); if (!f) return;
    if (!(S.multi && S.multi.has(f.clip.id))) select(f.clip.id);
    const ks = BY_TYPE[f.clip.type] || [];
    closeMenu(); menu = document.createElement('div'); menu.id = 'ctxMenu';
    menu.innerHTML = `<div class="cmh">${esc($t('an2.menuHead', { name: '' }))}${esc(clipLabel(f.clip)).slice(0, 40)}</div>`
      + (ks.length ? ks.map(k => `<button data-an="${k}">${esc(lab(k))}</button>`).join('') : `<div class="tdim">${$t('an2.none')}</div>`)
      + `<div class="tdim">${$t('an2.note')}</div>`;
    document.body.appendChild(menu);
    const w = menu.offsetWidth, h = menu.offsetHeight;
    menu.style.left = Math.min(e.clientX, innerWidth - w - 6) + 'px'; menu.style.top = Math.min(e.clientY, innerHeight - h - 6) + 'px';
    menu.addEventListener('click', ev => { const b = ev.target.closest('[data-an]'); if (!b) return; closeMenu(); request(f.clip.id, b.dataset.an); });
  });
  document.addEventListener('mousedown', e => { if (menu && !e.target.closest('#ctxMenu')) closeMenu(); });
  window.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });

  async function request(id, kind) {
    const f = findClip(id); if (!f) return;
    const r = await api('/api/analyze', { method: 'POST', body: JSON.stringify({ clip: f.clip, kind }), headers: { 'Content-Type': 'application/json' } });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) { const m = $L('an2.reqFail', { err: j.error || r.status }); setStatus(m, 'bad', { toast: false }); toast(m, true); return; }
    setStatus($L('an2.requested', { kind: { toString: () => lab(kind) } })); poll();
  }

  // ---------- 進み具合・終わったものを入れる ----------
  async function poll() {
    clearTimeout(timer);
    let d; try { d = await (await fetch('/api/analyze', { cache: 'no-store' })).json(); } catch (e) { timer = setTimeout(poll, 5000); return; }
    takeKinds(d);
    const jobs = d.jobs || [];
    for (const j of jobs) {
      if (j.applied || applying.has(j.id)) continue;
      if (j.state === 'done') { applying.add(j.id); apply(j); }
      else if (j.state === 'failed') { applying.add(j.id); const m = $L('an2.failed', { kind: { toString: () => lab(j.kind) }, err: String(j.error || '').slice(-240) }); setStatus(m, 'bad', { toast: false }); toast(m, true); markApplied(j); }
    }
    const active = jobs.filter(j => j.state === 'queued' || j.state === 'running');
    if (active.length) { setStatus($L('an2.running', { list: { toString: () => active.map(j => lab(j.kind) + (j.state === 'queued' ? $t('an2.queued') : '')).join($t('sep.list')) } }), 'busy'); timer = setTimeout(poll, 3000); }
  }
  function markApplied(j) { afterSaved(() => api(`/api/analyze/${j.id}/applied`, { method: 'POST' })); }  // 印はタイムラインの保存のあと（editor.js の afterSaved）
  function apply(j) {
    const f = findClip(j.clip), res = j.result || {}, data = res.data || {}, files = res.files || {};
    const base = f ? f.clip : { start: j.clipStart, dur: j.clipDur, label: j.label }, T = t => +(base.start + t).toFixed(4);
    const name = (f ? clipLabel(f.clip) : j.label || j.clip).slice(0, 24);
    let msg = '';
    // メタデータ・トラックの名前（作品の中身）は、取り込むときの画面の言葉で
    if (j.kind === 'beats' && Array.isArray(data.beats)) {
      const items = data.beats.filter(b => b[0] <= base.dur + 1e-6).map(b => [T(b[0]), !!b[1], 0.5]);
      const mname = $t('an2.beatsName', { name });
      change(() => { S.tl.meta = S.tl.meta || []; S.tl.meta.push({ id: uid('m_beats'), kind: 'beats', name: mname, from_analysis: j.out, items }); }, { keepForm: true });
      msg = $L('an2.beatsMsg', { n: items.length, mname });
    } else if (j.kind === 'transcribe' && Array.isArray(data.segments)) {
      const isLine = base.type === 'tts' || j.clipType === 'tts';
      const who = isLine && f ? ((charOf(f.clip.character) || {}).name || '') : '';
      const items = data.segments.filter(s => s.start <= base.dur + 1e-6).map(s => Object.assign({ start: T(s.start), end: T(Math.min(base.dur, Math.max(s.end, s.start + 0.1))), text: s.text }, isLine ? { who } : {}));
      const mname = $t('an2.trName', { name });
      change(() => { S.tl.meta = S.tl.meta || []; S.tl.meta.push({ id: uid('m_tr'), kind: isLine ? 'dialogue' : 'lyrics', name: mname, from_analysis: j.out, items }); }, { keepForm: true });
      msg = $L('an2.trMsg', { n: items.length, mname, file: files.transcript });
      if (window.buildMetaPanel) buildMetaPanel();
    } else if (j.kind === 'stems' && files.vocals && files.no_vocals) {
      change(() => {
        const T0 = S.tl.tracks, ref = T0.findIndex(t => t.role === 'reference');
        for (const [k, nm] of [['vocals', $t('an2.vocals')], ['no_vocals', $t('an2.accomp')]]) {
          const tr = { id: uid('t_audio'), name: $t('an2.stemTrack', { nm, name }), kind: 'audio', role: 'sfx', muted: true,
            clips: [{ id: uid('stem'), type: 'audio', src: files[k], start: base.start, dur: base.dur, in: 0, gain: f ? (f.clip.gain || 0) : 0, fade_in: 0, fade_out: 0, label: $t('an2.stemClip', { nm, name }) }] };
          T0.splice(ref >= 0 ? ref : T0.length, 0, tr);
        }
      });
      msg = $L('an2.stemsMsg');
    } else {
      msg = $L('an2.collected', { files: Object.values(files).join($t('sep.list')), how: $L(j.kind === 'cutout' ? 'an2.fromImages' : 'an2.forEffects') });
    }
    const m = $L('an2.done', { kind: { toString: () => lab(j.kind) }, summary: res.summary || '', msg });
    setStatus(m); toast(m); markApplied(j);
    if (window.MITTLER_ASSETS) window.MITTLER_ASSETS.load();
  }

  // ---------- 知らせ（右下に少しのあいだ出す） ----------
  function toast(text, bad) {
    // 知らせの部品は ui.js（MITTLER_NOTIFY）。失敗は閉じるまで残る（前は 12 秒で消えた）。同じ失敗は上のバーの知らせ（setStatus）と 1 つにまとまる（同じ鍵）
    MITTLER_NOTIFY(text, bad ? 'bad' : 'ok', bad ? { key: 'st:' + ((text && text.k) || String(text).slice(0, 12)) } : { ms: 12000 });
  }

  const prev = window.MITTLER_ON_CHANGE;
  window.MITTLER_ON_CHANGE = kinds => { if (prev) prev(kinds); if (kinds.includes('analyze')) poll(); };
  window.MITTLER_ANALYZE = { request, poll, LABEL, BY_TYPE };
  setTimeout(() => { if (S.tl) poll(); }, 2000);  // 開いたとき：終わっていてまだ入れていないもの（Claude Code が頼んだもの・閉じていたあいだのもの）
})();
