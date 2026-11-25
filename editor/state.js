// Mittler 編集画面：今の状態を Claude Code に知らせる（サーバーの /api/state → 作品の状態フォルダ（.mittler。古い作品は .claude-cut）の state.json と current_frame.jpg）。
// Claude Code のフック（tools/mittler_state.py、作品の .claude/settings.json）が、ユーザーが話しかけるたびに要約をそえる。
// 「これ」「ここ」＝選んでいるクリップ・今の時刻・その時刻に映っているもの。変わったら（0.5 秒ごとに見て）送る。
'use strict';
(() => {
  let last = '';
  const r3 = x => Math.round(x * 1000) / 1000;
  const brief = c => {
    const o = { id: c.id, type: c.type, label: clipLabel(c), start: r3(c.start), dur: r3(c.dur), end: r3(c.start + c.dur) };
    if (c.cut != null) o.cut = String(c.cut);
    if (c.effect) o.effect = c.effect;
    if (c.disabled) o.disabled = true;
    return o;
  };
  function collect() {
    const tl = S.tl; if (!tl) return null;
    const t = S.t, fpsv = tl.fps || 30, cu = typeof cutAt === 'function' ? cutAt(t) : null;
    const f = S.sel && findClip(S.sel);
    const st = {
      name: tl.name || '', format: tl.format, fps: fpsv, duration: tl.duration, width: tl.width, height: tl.height,
      time: { t: r3(t), frame: Math.round(t * fpsv), cut: cu ? String(cu.label) : null, playing: !!S.playing },
      selection: f ? Object.assign(brief(f.clip), { track: { id: f.track.id, name: f.track.name, kind: f.track.kind }, clip: f.clip }) : null,
      selected_track: !f && S.selTrack ? (tr => tr && { id: tr.id, name: tr.name, kind: tr.kind, clips: (tr.clips || []).length })(tl.tracks.find(x => x.id === S.selTrack)) : null,
      pane: S.pane,
      // この時刻にかかっているクリップ（上のトラックから。非表示のトラックは hidden）
      at_time: (tl.tracks || []).flatMap(tr => (tr.clips || []).filter(c => c.start <= t && t < c.start + c.dur)
        .map(c => Object.assign(brief(c), { track: tr.name || tr.id, kind: tr.kind }, tr.hidden || tr.muted ? { hidden: true } : {}))),
      // この時刻のメタデータ（歌詞・セリフ・ト書きなど）
      meta_at_time: (tl.meta || []).flatMap(m => (Array.isArray(m.items) ? m.items : []).filter(it => it && it.start != null && it.start <= t && t < (it.end != null ? it.end : it.start + 0.001))
        .map(it => ({ kind: m.kind, name: m.name, start: it.start, end: it.end, text: it.text || it.label || '', who: it.who }))),
      view: (() => { const wr = $('lanesWrap'); return wr ? { from: r3(wr.scrollLeft / S.pps), to: r3((wr.scrollLeft + wr.clientWidth) / S.pps) } : null; })(),
      unsaved: !!(S.saveTimer || S.saving),
      // 止めていて、今のタイムラインで描いた1コマが出ているときだけ、その絵をサーバーが current_frame.jpg に書く
      frame_t: !S.playing && S.exactT != null && Math.abs(S.exactT - snapFrame(t)) < 1e-6 && S.shownVer === S.ver ? S.exactT : null,
    };
    // 🎵 Suno の曲のクリップ（music があるときだけ書く）：採用待ち（adopt）があれば、フック（tools/mittler_state.py）が AI に知らせる
    const mus = (tl.tracks || []).flatMap(tr => (tr.clips || []).filter(c => c.type === 'audio' && c.music).map(c => {
      const m = c.music, ad = m.adopt, k = ad && (m.takes || []).find(x => x.id === ad.take);
      return { id: c.id, label: c.label || '', track: tr.name || tr.id, takes: (m.takes || []).length, adopted: m.adopted || null, src: c.src || null,
        adopt: ad ? Object.assign({}, ad, k ? { suno_id: k.suno_id, song_url: k.song_url, title: k.title || '' } : {}) : null };
    }));
    if (mus.length) st.music = mus;
    // 編集画面に出ている描画のエラー（その時刻の1コマが描けなかった。全文。フックが AI に伝える）
    if (S.renderErr) st.render_error = { t: r3(S.renderErr.t), text: S.renderErr.text.slice(-6000) };
    return st;
  }
  async function tick() {
    try {
      const st = collect();
      if (st) {
        const key = JSON.stringify(st);
        if (key !== last) { last = key; await api('/api/state', { method: 'POST', body: key, headers: { 'Content-Type': 'application/json' } }); }
      }
    } catch (e) { }
    setTimeout(tick, 500);
  }
  const wait = setInterval(() => { if (S.tl) { clearInterval(wait); tick(); } }, 300);
  // すぐ送る（API の見える操作で選んだ・飛んだとき。editor/remote.js）
  async function push() {
    try { const st = collect(); if (!st) return; const key = JSON.stringify(st); if (key !== last) { last = key; await api('/api/state', { method: 'POST', body: key, headers: { 'Content-Type': 'application/json' } }); } } catch (e) { }
  }
  window.MITTLER_STATE = { collect, push };
})();
