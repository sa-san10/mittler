// Mittler 編集画面：🎵 Suno の曲（音のクリップの music。機能追加案02 v2「Suno 連携は AI 主導・拡張は倉庫に徹する」）。media.js・plan.js のあとに読む。
// 拡張は Suno を呼ばない。Suno を呼ぶのは Claude Code（AI）だけ。ここは：プロンプトの欄（AI が書いたものを人が確かめる・直す）・テイクの一覧
// （「▶ suno.com で聞く」＝ユーザーの既定のブラウザで曲のページ。試聴は suno.com のページだけ）・「採用」（ダウンロード用のクレジットを1つ使うことを確かめてから、
// 採用待ちの印 music.adopt を付ける → AI がフック（tools/mittler_state.py）か mittler_api.py music --pending で知って、wav を取ってきて納品する）・
// 届いたもの（サーバーの /api/music。tools/mittler_api.py の music-take）をテイクに入れる・採用待ちのファイルが届いたらクリップの src にして拍と構成をメタデータに入れる。
// 形は docs/タイムライン形式.md の「🎵 Suno の曲」、受け渡しは docs/Suno受け渡し契約.md の「Mittler 側の受け渡し」。画面の言葉は辞書の mu.*
'use strict';
(() => {
  const uid = p => p + '_' + Math.random().toString(36).slice(2, 8);
  const SONG_URL = /^https:\/\/suno\.com\/song\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;  // サーバー（server/music.js）も同じ形だけを開く
  const blank = () => ({ prompt: '', lyrics: '', title: '', style: '', instrumental: false, takes: [], activeTake: null });
  const takeOf = (c, id) => (((c.music || {}).takes) || []).find(k => k.id === id);
  const safe = s => String(s).replace(/[^A-Za-z0-9_-]/g, '_');
  let armed = null;  // 採用の確かめを出しているテイク：{clip, take}
  let player = null;
  const T = (k, v) => $t('mu.' + k, v);

  // ---------- 拍と構成をメタデータに（Suno の解析 → kind beats [秒, 小節の頭か, 強さ]・kind song_sections {start, end, text}）----------
  // 曲の秒 → タイムラインの秒（クリップの start と in で）。クリップが使っている区間だけ。同じクリップから入れたもの（from_music）は置きかえる
  function putMeta(c, k) {
    const a = k.analysis || {}, i0 = +c.in || 0, i1 = i0 + c.dur, Ts = s => +(c.start + s - i0).toFixed(4);
    const name = (c.label || k.title || c.id).slice(0, 24);
    S.tl.meta = (S.tl.meta || []).filter(m => m.from_music !== c.id);
    const beats = (a.beats || []).filter(b => b[0] >= i0 - 1e-6 && b[0] <= i1 + 1e-6).map(b => [Ts(b[0]), b[1] === 1, 0.5]);
    const secs = (a.sections || []).filter(s => s.end > i0 && s.start < i1).map(s => ({ start: Ts(Math.max(s.start, i0)), end: Ts(Math.min(s.end, i1)), text: s.label || '' }));
    // メタデータの名前（作品の中身）は、入れるときの画面の言葉で
    if (beats.length) S.tl.meta.push(Object.assign({ id: uid('m_beats'), kind: 'beats', name: T('beatsName', { name }), from_music: c.id, from_suno: k.suno_id, items: beats },
      a.bpm != null ? { bpm: a.bpm } : {}, a.time_signature != null ? { time_signature: a.time_signature } : {}));
    if (secs.length) S.tl.meta.push(Object.assign({ id: uid('m_song'), kind: 'song_sections', name: T('secsName', { name }), from_music: c.id, from_suno: k.suno_id, items: secs },
      a.key != null ? { key: a.key } : {}));
    // 歌詞の時刻（Suno の audio-lyrics-alignment。2026-11-15）：行ごとに kind lyrics の項目 {start, end, text, words: [[始め, 終わり, 字, 置けたか], …]}。
    // 置けなかった単語（success: false。隣からの推定）がある行は uncertain に数。インスト曲・歌詞の時刻が無いテイクは入れない。リリックの演出（字幕・動く文字）はこれを読む
    const al = k.lyrics_alignment, ws = (al && al.words) || [];
    const lines = k.instrumental || !al ? [] : (al.lines || []).filter(l => l.end > i0 && l.start < i1).map(l => Object.assign({ start: Ts(Math.max(l.start, i0)), end: Ts(Math.min(l.end, i1)), text: l.text },
      l.bad ? { uncertain: l.bad } : {}, { words: ws.slice((l.w || [])[0] || 0, (l.w || [])[1] || 0).filter(w => w[1] > i0 && w[0] < i1).map(w => [Ts(w[0]), Ts(w[1]), String(w[2]).replace(/\n/g, ''), !!w[3]]) }));
    if (lines.length) S.tl.meta.push({ id: uid('m_lyrics'), kind: 'lyrics', name: T('lyricsName', { name }), from_music: c.id, from_suno: k.suno_id, items: lines });
    return { beats: beats.length, sections: secs.length, lyrics: lines.length };
  }
  // 採用（ファイルのあるテイク）：クリップの音をそのテイクのファイルに（頭から。テイクのほうが短ければ長さもテイクに）、拍と構成をメタデータに
  function adoptInto(c, k) {
    c.src = k.src; c.in = 0;
    if (+k.dur > 0 && k.dur < c.dur) c.dur = +(+k.dur).toFixed(6);
    c.music.adopted = k.id; c.music.activeTake = k.id;
    if (c.music.adopt) delete c.music.adopt;
    return putMeta(c, k);
  }
  const metaNote = n => $LJ(n && n.beats ? $L('mu.metaNote', { b: n.beats, s: n.sections }) : '', n && n.lyrics ? $L('mu.lyricsNote', { n: n.lyrics }) : '');
  function adopt(c, k) {
    if (!k.src) {  // ファイルがまだ無い：ダウンロード用のクレジットを使うことを確かめる（下の欄）
      armed = { clip: c.id, take: k.id }; refreshSel(); return;
    }
    let n = null; change(() => { n = adoptInto(c, k); });
    setStatus($L('mu.adopted', { id: k.id, src: k.src, meta: metaNote(n) }));
  }
  function requestAdopt(c, k) {  // ユーザーが OK した：採用待ちの印（AI がダウンロードして納品する）
    armed = null;
    change(() => { c.music.adopt = { take: k.id, format: 'wav', requested: new Date().toISOString() }; c.music.activeTake = k.id; });
    setStatus($L('mu.requested', { id: k.id }));
  }
  const refreshSel = () => { const f = S.sel && findClip(S.sel); if (f && f.clip.type === 'audio' && window.MITTLER_INSPECT) window.MITTLER_INSPECT(f.clip, f); };

  // ---------- 右の欄（音のクリップ：music があるか、🎵 音楽のトラックのとき） ----------
  const prevInspect = window.MITTLER_INSPECT;
  window.MITTLER_INSPECT = (c, f) => {
    const r = prevInspect ? prevInspect(c, f) : false;
    if (c.type === 'audio' && (c.music || (f.track && f.track.role === 'bgm'))) section(c);
    return r;
  };
  const fmtTake = k => {
    const a = k.analysis || {};
    return [k.title || '', +k.dur ? $t('as.sec', { s: (+k.dur).toFixed(1) }) : '', a.bpm != null ? `${Math.round(a.bpm)} BPM` : '', a.key || '', k.model || ''].filter(Boolean).map(esc).join($t('sep.list'));
  };
  function section(c) {
    const el = $('sel'); if (!el) return;
    const box = document.createElement('div'); box.className = 'planSec musicSec'; box.dataset.clip = c.id;
    const m = c.music;
    if (!m) {
      box.innerHTML = `<h3>${T('title')}</h3><div class="tdim">${esc(T('intro1', { id: c.id }))}
        ${esc(T('intro2', { src: c.src || T('none') }))}</div><div class="btns"><button class="muMake">${T('make')}</button></div>`;
      el.appendChild(box);
      box.querySelector('.muMake').onclick = () => change(() => { c.music = blank(); });
      return;
    }
    const ad = m.adopt, adk = ad && takeOf(c, ad.take);
    const rows = (m.takes || []).map(k => {
      const using = m.adopted === k.id && c.src && c.src === k.src, waiting = ad && ad.take === k.id;
      return `<div class="vtake mtake${using ? ' on' : ''}" data-take="${esc(k.id)}" title="${esc(k.prompt || '')}">
        <span><b>${esc(k.id)}</b> ${fmtTake(k)}${k.src ? '' : `${$t('sep.list')}<i class="tdim">${T('noFile')}</i>`}</span>
        ${SONG_URL.test(k.song_url || '') ? `<button class="muOpen" title="${esc(T('open.tip'))}">${T('open')}</button>` : ''}
        ${k.src ? `<button class="muPlay" title="${esc(T('play.tip'))}">${T('play')}</button>` : ''}
        ${(k.analysis && (k.analysis.beats || []).length) ? `<button class="muBeats" title="${esc(T('beats.tip'))}">${MITTLER_ICON('drum')}</button>` : ''}
        <button class="adopt muAdopt" ${using || waiting ? 'disabled' : ''}>${$t(using ? 'pl.adopted' : waiting ? 'mu.waiting' : 'pl.adopt')}</button></div>`
        + (armed && armed.clip === c.id && armed.take === k.id ? `<div class="muConfirm"><div>${T('confirm1')}<b>${T('confirm2')}</b>${T('confirm3')}
          ${T('confirm4')}</div>
          <div class="btns"><button class="primary muYes">${T('yes')}</button><button class="muNo">${$t('an.cancel')}</button></div></div>` : '');
    }).join('');
    box.innerHTML = `<h3>${T('title')}</h3>
      <label class="mlab">${T('prompt')}</label><textarea data-m="prompt" spellcheck="false">${esc(m.prompt || '')}</textarea>
      <label class="mlab">${T('lyrics')}</label><textarea data-m="lyrics" spellcheck="false" class="short">${esc(m.lyrics || '')}</textarea>
      <div class="form"><label>${T('style')}</label><input data-m="style" type="text" value="${esc(m.style || '')}" placeholder="lo-fi piano / electro swing">
        <label>${T('songTitle')}</label><input data-m="title" type="text" value="${esc(m.title || '')}">
        <label>${T('inst')}</label><input data-m="instrumental" type="checkbox" ${m.instrumental ? 'checked' : ''}>
        <label>${T('dur')}</label><input data-m="duration" type="number" min="15" max="360" step="1" value="${m.duration != null ? esc(m.duration) : ''}" placeholder="${esc(T('dur.ph'))}"></div>
      <div class="tdim">${esc(T('who', { id: c.id }))}</div>
      ${ad ? `<div class="muWait">${esc(T('wait', { id: ad.take, title: adk && adk.title ? $t('cm.q', { x: adk.title }) : '' }))}<button class="muCancel">${T('cancelWait')}</button></div>` : ''}
      ${rows ? `<div class="vtakes">${rows}</div>` : `<div class="empty">${T('noTakes')}</div>`}
      <div class="mplayer" hidden></div>
      <div class="tdim">${T('stems')}</div>`;
    el.appendChild(box);
    box.querySelectorAll('[data-m]').forEach(inp => inp.onchange = () => change(() => {
      c.music = Object.assign(blank(), c.music || {});
      const k = inp.dataset.m;
      if (inp.type === 'checkbox') c.music[k] = inp.checked;
      else if (inp.type === 'number') { const v = parseFloat(inp.value); if (isFinite(v) && v > 0) c.music[k] = Math.round(v); else delete c.music[k]; }
      else c.music[k] = inp.value;
    }, { keepForm: true }));
    const cancel = box.querySelector('.muCancel');
    if (cancel) cancel.onclick = () => { change(() => { delete c.music.adopt; }); setStatus($L('mu.cancelled')); };
    box.querySelectorAll('.mtake').forEach(row => {
      const k = takeOf(c, row.dataset.take); if (!k) return;
      const on = (sel, fn) => { const b = row.querySelector(sel); if (b) b.onclick = e => { e.stopPropagation(); fn(); }; };
      on('.muOpen', () => openSong(k));
      on('.muPlay', () => {
        const pl = box.querySelector('.mplayer'), same = !pl.hidden && pl.dataset.take === k.id;
        if (player) { player.pause(); player = null; }
        pl.hidden = same; pl.dataset.take = same ? '' : k.id; pl.innerHTML = '';
        if (!same) { if (S.playing && typeof setPlaying === 'function') setPlaying(false); pl.innerHTML = `<audio src="${rootUrl(k.src)}" controls autoplay></audio><div class="tdim">${esc(k.id)}（${esc(k.src)}）</div>`; player = pl.querySelector('audio'); }
      });
      on('.muBeats', () => { let n = null; change(() => { n = putMeta(c, k); }, { keepForm: true }); setStatus($L('mu.beatsPut', { id: k.id, b: n.beats, s: n.sections })); if (window.buildMetaPanel) buildMetaPanel(); });
      on('.muAdopt', () => adopt(c, k));
    });
    const yes = box.querySelector('.muYes'), no = box.querySelector('.muNo');
    if (yes) yes.onclick = () => { const k = takeOf(c, armed.take); if (k) requestAdopt(c, k); };
    if (no) no.onclick = () => { armed = null; refreshSel(); };
  }
  async function openSong(k) {
    if (!SONG_URL.test(k.song_url || '')) { setStatus($L('mu.badUrl')); return; }
    let j = {};
    try { j = await (await api('/api/music/open', { method: 'POST', body: JSON.stringify({ url: k.song_url }), headers: { 'Content-Type': 'application/json' } })).json(); } catch (e) { j = { ok: false, error: String(e) }; }
    if (j.ok) setStatus($L('mu.opened', { id: k.id })); else setStatus($L('mu.openFail', { err: j.error || '' }));
  }

  // ---------- タイムラインのしるし（音のクリップの右下） ----------
  function badge(c) {
    const m = c.music; if (!m) return '';
    const t = m.adopt ? T('badge.waiting') : m.adopted && c.src ? `{icon:music} ${m.adopted}` : (m.takes || []).length ? T('badge.takes', { n: m.takes.length }) : T('badge.none');
    return `<span class="badge">${esc(t)}</span>`;
  }

  // ---------- 🎵 音楽のトラックの空いたところをダブルクリック：Suno の曲のクリップ（音はまだ無い） ----------
  const prevDbl = window.MITTLER_LANE_DBL;
  window.MITTLER_LANE_DBL = (tr, t) => {
    if (!tr || tr.kind !== 'audio' || tr.role !== 'bgm') return prevDbl && prevDbl(tr, t);
    const c = { id: uid('music'), type: 'audio', src: null, start: t, dur: 30, in: 0, gain: -6, fade_in: 0, fade_out: 1, label: T('title'), music: blank() };  // ラベル（作品の中身）は作るときの画面の言葉で
    change(() => { tr.clips.push(c); tr.clips.sort((a, b) => a.start - b.start); });
    select(c.id); if (S.pane !== 'sel') showPane('sel');
    setStatus($L('mu.placed'));
  };

  // ---------- 届いたもの（サーバーの /api/music）をテイクに入れる ----------
  let busy = false;
  async function poll() {
    if (busy || !S.tl) return; busy = true;
    try {
      const ds = ((await (await fetch('/api/music', { cache: 'no-store' })).json()).deliveries || []).filter(d => !d.applied);
      for (const d of ds) apply(d);
    } catch (e) { } finally { busy = false; }
  }
  function apply(d) {
    const f = findClip(d.clip), c = f && f.clip;
    if (!c || c.type !== 'audio') { setStatus($L('mu.noClip', { clip: d.clip, take: d.take, src: d.src ? $t('sep.list') + d.src : '' })); return mark(d); }
    if (d.kind === 'take') {
      const dup = (((c.music || {}).takes) || []).some(k => k.id === d.take || (d.data && k.suno_id === d.data.suno_id));
      if (!dup) {
        change(() => { c.music = Object.assign(blank(), c.music || {}); c.music.takes = (c.music.takes || []).concat([Object.assign({}, d.data, { id: d.take })]); c.music.activeTake = d.take; });
        setStatus($L('mu.takeArrived', { name: c.label || c.id, take: d.take }));
      }
    } else if (d.kind === 'file') {
      const k = takeOf(c, d.take);
      if (!k) { setStatus($L('mu.noTake', { id: c.id, take: d.take, src: d.src })); return mark(d); }
      let n = null; const was = !!(c.music.adopt && c.music.adopt.take === k.id);
      change(() => { k.src = d.src; k.format = d.format; if (+d.dur > 0) k.dur = d.dur; k.downloaded = d.created; if (was) n = adoptInto(c, k); });
      setStatus(was ? $L('mu.fileAdopted', { id: k.id, src: d.src, meta: metaNote(n) }) : $L('mu.fileArrived', { id: k.id, src: d.src }));
      if (window.buildMetaPanel) buildMetaPanel();
    }
    return mark(d);
  }
  function mark(d) { d.applied = true; afterSaved(() => api(`/api/music/${d.id}/applied`, { method: 'POST' })); }  // 印はタイムラインの保存のあと（editor.js の afterSaved）

  const prevChange = window.MITTLER_ON_CHANGE;
  window.MITTLER_ON_CHANGE = kinds => { if (prevChange) prevChange(kinds); if (kinds.includes('music')) poll(); };
  const wait = setInterval(() => { if (S.tl) { clearInterval(wait); setTimeout(poll, 800); } }, 300);  // 開いたとき：閉じていたあいだに届いたもの
  window.MITTLER_MUSIC = { badge, poll, putMeta, adopt, requestAdopt, openSong };
})();
