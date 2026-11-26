// Mittler：編集画面のボタンと API（server/server.js の /api/op・tools/mittler_api.py）で同じタイムラインの書きかえ（2026-11-15）。
// 人の操作が要る所は、Suno の採用と H3 の生成のほか、全部 API から頼めるようにする。
// 前は編集画面の中（media.js・plan.js・cutedit.js・warp.js・cutmeta.js・editor.js の change）だけにあった計算を、ここの1か所に移した。
// ブラウザ（editor/index.html が calc.js のあとに読む → window.MITTLER_OPS）と Node（server/server.js が require）の両方で使う。
// どれもタイムライン（JSON）を受け取って直す純粋な関数。画面のこと（setStatus・選ぶ・描き直す）は呼ぶ側。
// 呼ぶ側が渡すもの E（env）：
//   uid(頭)         新しい id（頭_ランダム 6 字）
//   t(鍵, 値)       作品の中身に書く名前（トラックの名前など）を今の言葉で
//   L(鍵, 値)       あとで訳す知らせの文（編集画面は $L、サーバーは今の言葉）
//   name(クリップ)  知らせの中のクリップの名前（「名前」）
//   isPerCut(c)     窓が per_cut のエフェクトか（エフェクトの META が要る）
//   srcDur(c)       素材の長さ（秒。分からなければ null）
// 同じことは tools/smoke_api.py が確かめる（ボタンで押した結果と API の結果が同じタイムライン）。
'use strict';
(function (root) {
  const CALC = typeof module === 'object' && module.exports ? require('./calc') : root.MITTLER_CALC;
  const r6 = x => +(+x).toFixed(6);
  const EPS = 1e-6;
  const fpsOf = tl => tl.fps || 30;
  const durOf = tl => tl.duration || 10;
  const snapF = (fps, t) => Math.round(t * fps) / fps;
  const isPts = c => !!(c && c.warp && typeof c.warp === 'object' && Array.isArray(c.warp.points) && c.warp.points.length);
  const allClips = tl => (tl.tracks || []).flatMap(tr => (tr.clips || []).map(c => ({ c, tr })));
  const findClip = (tl, id) => { for (const tr of tl.tracks || []) for (const c of tr.clips || []) if (c.id === id) return { clip: c, track: tr }; return null; };
  function fmt(t) { const m = Math.floor(t / 60), s = t - m * 60; return `${m}:${s.toFixed(3).padStart(6, '0')}`; }

  // ---------- 時刻の決まり（editor.js の change と同じ。コマに乗っている時刻は n / fps のまま書く） ----------
  const onFrame = (fps, x) => { const f = snapF(fps, x); return Math.abs(f - x) < EPS ? f : null; };
  const snapT = (fps, x) => { const f = onFrame(fps, x); return f == null ? x : f; };
  const rT = (fps, x) => { const f = onFrame(fps, x); return f == null ? +(+x).toFixed(6) : f; };
  const _f64 = new Float64Array(1), _u64 = new BigUint64Array(_f64.buffer);
  const prevDouble = v => { _f64[0] = v; _u64[0] -= 1n; return _f64[0]; };
  function durTo(s, f) { let v = f - s; while (v > 0 && s + v > f) v = prevDouble(v); return v; }
  // 直し（fn）のあと：この操作で頭か長さが変わったクリップと、新しく出てきたメタデータの時刻を、上の決まりにそろえる
  function normalizeTimes(tl, before) {
    const fps = fpsOf(tl), old = JSON.parse(before), was = new Map();
    for (const tr of old.tracks || []) for (const c of tr.clips || []) was.set(c.id, c);
    for (const tr of tl.tracks || []) for (const c of tr.clips || []) {
      if (typeof c.start !== 'number' || typeof c.dur !== 'number') continue;
      const o = was.get(c.id), ns = !o || o.start !== c.start, nd = !o || o.dur !== c.dur;
      if (!ns && !nd) continue;
      const e = c.start + c.dur;
      if (ns) c.start = snapT(fps, c.start);
      const f = onFrame(fps, e); if (f != null && f > c.start) c.dur = durTo(c.start, f);
    }
    const oldMeta = new Map((old.meta || []).map(m => [m.id, m]));
    for (const m of tl.meta || []) {
      if (!Array.isArray(m.items)) continue;
      const om = oldMeta.get(m.id), vals = new Set();
      for (const it of (om && Array.isArray(om.items) ? om.items : [])) if (it && !Array.isArray(it) && typeof it === 'object') { vals.add(it.start); vals.add(it.end); }
      for (const it of m.items) {
        if (!it || Array.isArray(it) || typeof it !== 'object') continue;
        for (const k of ['start', 'end']) if (typeof it[k] === 'number' && !vals.has(it[k])) it[k] = snapT(fps, it[k]);
      }
    }
  }
  // クリップの終わりのいちばん後ろ（withAudio が false なら音のクリップは入れない）
  function contentEnd(tl, withAudio) {
    let e = 0;
    for (const tr of tl.tracks || []) for (const c of tr.clips || []) if (withAudio || c.type !== 'audio') e = Math.max(e, (+c.start || 0) + (+c.dur || 0));
    return e;
  }
  // 直しのあと（editor.js の change と同じ）：時刻をそろえて、動画の外に置いたら動画の長さを伸ばす。伸ばしたら true
  function finish(tl, before, opts) {
    const d0 = durOf(tl);
    normalizeTimes(tl, before);
    if (!(opts && opts.noExtend)) { const need = contentEnd(tl, false), fps = fpsOf(tl); if (need > durOf(tl) + 1e-6) tl.duration = +(Math.ceil(need * fps - 1e-6) / fps).toFixed(6); }
    return durOf(tl) > d0 + 1e-9;
  }

  // ---------- セリフ（TTS） ----------
  const GEMINI_MODELS = ['gemini-3.8-flash-tts', 'gemini-3.8-flash-lite-tts'];
  const nonEmpty = o => Object.fromEntries(Object.entries(o || {}).filter(([, v]) => v !== '' && v !== null && v !== undefined));
  // クリップの声の設定（クリップに無ければキャラ設定 characters.json の値）
  function ttsEffective(c, chars) {
    const ch = (chars || []).find(x => x.id === c.character) || {}; const t = ch.tts || {};
    return { gemini: Object.assign({ model: GEMINI_MODELS[0], voice: 'Kore', style: '' }, nonEmpty(t.gemini), nonEmpty(c.gemini)),
      voicevox: Object.assign({}, nonEmpty(t.voicevox), nonEmpty(c.voicevox)), ch };
  }
  const ttsEngine = (c, chars) => c.engine || (ttsEffective(c, chars).ch.tts || {}).default_engine || 'gemini';
  // 生成の頼み（サーバーの /api/tts → tools/tts_gen.py）。このシーンの演技 delivery_style は Gemini のスタイルのあとに「 / 」でつなぐ
  function ttsRequest(c, chars) {
    const e = ttsEffective(c, chars), engine = ttsEngine(c, chars);
    const ds = String(c.delivery_style || '').trim();
    const gem = ds ? Object.assign({}, e.gemini, { style: e.gemini.style ? `${e.gemini.style} / ${ds}` : ds }) : e.gemini;
    const r = { engine, text: c.text || '', gemini: gem, voicevox: e.voicevox };
    const tp = ttsTempo(c, chars); if (tp !== 1) r.tempo = tp;  // 生成のあとの速さ（tools/tts_gen.py が ffmpeg の atempo）
    return r;
  }
  // 生成のあとの速さ（atempo。0.5〜2）：クリップの tempo → キャラ設定の tts.tempo → 1（2026-11-14 使ってみた知らせ：プリセットのメモに「生成したあと atempo=1.15」）
  function ttsTempo(c, chars) {
    const ch = (chars || []).find(x => x.id === c.character) || {}, v = c.tempo != null && c.tempo !== '' ? +c.tempo : (ch.tts || {}).tempo != null ? +(ch.tts || {}).tempo : 1;
    return isFinite(v) && v > 0 ? Math.max(0.5, Math.min(2, v)) : 1;
  }
  // できた声 j（{id, src, dur}）を新しいテイクにして選ぶ
  function ttsAddTake(c, j, request, now) {
    const engine = request.engine;
    c.takes = c.takes || [];
    c.takes.push(Object.assign({ id: j.id, src: j.src, dur: j.dur, engine, text: request.text, [engine]: request[engine] }, request.tempo ? { tempo: request.tempo } : {}, { created: now }));
    c.activeTake = j.id; c.in = 0; c.dur = +(+j.dur).toFixed(6);
  }
  // 同じ TTS のトラックで重なっているセリフ → Map(id → 重なっている相手の id)。声の長さでクリップが伸びて、次のセリフに重なったのを知らせる
  // （2026-11-14 使ってみた知らせ：「となりのセリフと重なっても知らせが無い」）。別のトラック（別のキャラ）との重なりは、掛け合いでわざと重ねることがあるので見ない
  function ttsOverlaps(tl) {
    const out = new Map();
    for (const tr of (tl.tracks || []).filter(t => t.kind === 'tts')) {
      const cs = (tr.clips || []).filter(c => c.type === 'tts' && !c.disabled).slice().sort((a, b) => a.start - b.start);
      for (let i = 0; i < cs.length; i++) for (let j = i + 1; j < cs.length && cs[j].start < cs[i].start + cs[i].dur - 1e-6; j++) {
        if (!out.has(cs[i].id)) out.set(cs[i].id, cs[j].id);
        if (!out.has(cs[j].id)) out.set(cs[j].id, cs[i].id);
      }
    }
    return out;
  }
  // テイクを選ぶ（長さもそのテイクに）。無ければ null
  function ttsSelectTake(c, id) {
    const k = (c.takes || []).find(x => x.id === id); if (!k) return null;
    c.activeTake = k.id; c.in = 0; c.dur = +(+k.dur).toFixed(6); return k;
  }
  // まとめて生成するセリフ（時間の順）：all＝文の入っているもの全部、pending＝そのうちテイクが1つも無いもの
  function ttsLines(tl, mode) {
    const all = (tl.tracks || []).filter(tr => tr.kind === 'tts').flatMap(tr => tr.clips || [])
      .filter(c => c.type === 'tts' && String(c.text || '').trim()).sort((a, b) => a.start - b.start);
    return mode === 'all' ? all : all.filter(c => !(c.takes || []).length);
  }
  // セリフから字幕：しゃべる文（text）から演技タグを外し、無音だけの行は作らない
  const cleanLine = t => String(t || '').replace(/<[A-Za-z][A-Za-z ]*>/g, '').replace(/\[[A-Za-z][A-Za-z ]*\]/g, '').replace(/[ \t　]+/g, ' ').replace(/ *\n */g, '\n').trim();
  const silentOnly = t => !t.replace(/[\s…・。、．.,!?！？ー〜～「」『』（）()]/g, '');
  // 字幕にするセリフ：選んでいるセリフ（sel：クリップの並び）があればそれだけ、無ければ見えている TTS のトラックの全部
  function subLines(tl, sel) {
    const s = (sel || []).filter(c => c && c.type === 'tts');
    return (s.length ? s : (tl.tracks || []).filter(t => t.kind === 'tts' && !t.muted && !t.hidden).flatMap(t => t.clips || []))
      .filter(c => c.type === 'tts' && !c.disabled && !silentOnly(cleanLine(c.text))).sort((a, b) => a.start - b.start);
  }
  // 字幕を作る・前に作った字幕（from_tts）の時間を合わせ直す（手で直した文はそのまま）→ {made, upd, kept}
  function subsFromLines(tl, lines, E) {
    let made = 0, upd = 0, kept = 0;
    const subs = () => tl.tracks.filter(t => t.kind === 'subtitle');
    let tr = subs().find(t => t.clips.some(c => c.from_tts)) || subs().find(t => !t.clips.length);
    if (!tr) { tr = { id: E.uid('t_subtitle'), name: E.t('track.subFromLines'), kind: 'subtitle', clips: [] }; tl.tracks.splice(0, 0, tr); }
    const style = (tr.clips.find(c => c.style) || subs().flatMap(t => t.clips).find(c => c.style) || {}).style;
    for (const c of lines) {
      const text = cleanLine(c.text), ex = subs().flatMap(t => t.clips).find(x => x.from_tts === c.id);
      if (ex) {
        if (ex.text === ex.from_tts_text) ex.text = text; else kept++;
        ex.from_tts_text = text; ex.start = c.start; ex.dur = c.dur; upd++;
      } else {
        const x = { id: E.uid('sub'), type: 'subtitle', start: c.start, dur: c.dur, text, from_tts: c.id, from_tts_text: text };
        if (style) x.style = JSON.parse(JSON.stringify(style));
        tr.clips.push(x); made++;
      }
    }
    for (const t of subs()) t.clips.sort((a, b) => a.start - b.start);
    return { made, upd, kept };
  }

  // ---------- 動画化予定（🎬 のテイクを選ぶ・採用） ----------
  const blankFrame = () => ({ src: null, prompt: '', takes: [], activeTake: null });
  // 開始・終了の絵のテイクを選ぶ（その絵を使う）。無ければ null
  function planFrameTake(c, which, id) {
    const k = ((c[which] || {}).takes || []).find(x => x.id === id); if (!k) return null;
    c[which].src = k.src; c[which].activeTake = k.id; return k;
  }
  // 動画のテイクを選ぶ（採用の前でも、その場所に映る）。無ければ null
  function planVideoTake(c, id) {
    const k = ((c.video || {}).takes || []).find(x => x.id === id); if (!k) return null;
    c.video.activeTake = k.id; return k;
  }
  // 置く長さ：テイクが予定より 2 コマ未満だけ短いときは予定の長さいっぱい
  const adoptDur = (c, k, fps) => (k.dur && k.dur < c.dur - 2 / fps ? +(+k.dur).toFixed(6) : c.dur);
  const latestTake = v => { const ts = (v.takes || []).filter(k => k.src); return ts.reduce((a, k) => (!a || String(k.created || '') >= String(a.created || '') ? k : a), null); };
  // 採用を待っているもの [[予定のクリップ, テイク], …]（tr：そのトラックだけ。latest：いちばん新しいテイク）
  function pendingAdopt(tl, tr, latest) {
    const out = [];
    for (const c of (tr ? tr.clips : (tl.tracks || []).filter(t => t.kind === 'plan').flatMap(t => t.clips)) || []) {
      const v = c.video || {}, k = latest ? latestTake(v) : (v.takes || []).find(x => x.id === v.activeTake); if (!k || !k.src) continue;
      const ad = v.adopted && findClip(tl, v.adopted); if (ad && ad.clip.src && ad.clip.src[0] === k.src) continue;
      out.push([c, k]);
    }
    return out;
  }
  // 採用：🎞️ 映像トラックの同じ時間に映像クリップを置く（採用済みならその映像クリップを差しかえる）。作品の設定 cuts_on_adopt ならカットも足す。
  // pairs：[[予定のクリップ, テイク], …]。→ {cuts：カットの結果の並び}。映像トラックが無ければ null
  function adopt(tl, pairs, E) {
    const vt = (tl.tracks || []).find(t => t.kind === 'video'); if (!vt) return null;
    const fps = fpsOf(tl), K = cuts(tl, E), cutsDone = [];
    for (const [c, k] of pairs) {
      c.video.activeTake = k.id;
      const dur = adoptDur(c, k, fps), prev = c.video.adopted && findClip(tl, c.video.adopted);
      let vc = prev && prev.clip;
      if (prev) { prev.clip.src = [k.src]; prev.clip.dur = dur; prev.clip.in = 0; }
      else {
        vc = { id: E.uid('video'), type: 'video', src: [k.src], start: c.start, dur, in: 0, speed: 1, label: (c.label || E.t('clip.keyframes')) + E.t('sep.list') + k.id, from_plan: c.id };
        if (c.grade) vc.grade = Object.assign({}, c.grade);
        vt.clips.push(vc); c.video.adopted = vc.id;
      }
      cutsDone.push(K.adoptIn(c, vc));
    }
    vt.clips.sort((a, b) => a.start - b.start);
    return { cuts: cutsDone };
  }

  // ---------- 動画の音（動画から取り出した WAV を「動画の音」のトラックにリンクして置く） ----------
  function audioTrackFor(tl, E) {
    let tr = tl.tracks.find(t => t.kind === 'audio' && t.from_video);
    if (!tr) {
      tr = { id: E.uid('t_audio'), name: E.t('track.videoAudio'), kind: 'audio', role: 'sfx', from_video: true, clips: [] };
      const ref = tl.tracks.findIndex(t => t.role === 'reference'); tl.tracks.splice(ref >= 0 ? ref : tl.tracks.length, 0, tr);
    }
    return tr;
  }
  const audioClipFor = (c, a, lk, E) => ({ id: E.uid('vau'), type: 'audio', src: a.path, start: c.start, dur: c.dur, in: c.in || 0, gain: 0, fade_in: 0, fade_out: 0, label: c.label || a.path.split('/').pop(), link: lk });
  const vaSrc = c => (Array.isArray(c.src) ? (c.src.length === 1 ? c.src[0] : null) : c.src);
  // 置けないわけ（置けるなら ''）：もう音がある・速さや音ハメのある動画
  function vaWhy(tl, c) {
    if (c.link && allClips(tl).some(({ c: x }) => x !== c && x.link === c.link && x.type === 'audio')) return 'ce.vaHas';
    if (c.warp || (c.speed || 1) !== 1) return 'ce.vaSpeed';
    return '';
  }
  // 取り出した音 a（/api/video_audio の {path}）を、動画クリップ c にリンクして置く
  function vaPlace(tl, c, a, E) {
    const lk = c.link || E.uid('lk'); c.link = lk; const at = audioTrackFor(tl, E); at.clips.push(audioClipFor(c, a, lk, E)); at.clips.sort((x, y) => x.start - y.start);
  }
  // 動画クリップ c をトラック tr に置く（音 a があればリンクして一緒に）
  function placeVideo(tl, tr, c, a, E) {
    tr.clips.push(c); tr.clips.sort((x, y) => x.start - y.start);
    if (a && a.ok && !a.none) { const lk = E.uid('lk'); c.link = lk; const at = audioTrackFor(tl, E); at.clips.push(audioClipFor(c, a, lk, E)); at.clips.sort((x, y) => x.start - y.start); }
  }

  // ---------- 音ハメ（自動）：拍・頼みの中身・結果の入れ方（warp.js と同じ） ----------
  function songBeats(tl) {
    const m = (tl.meta || []).find(x => x.kind === 'beats');
    if (m && Array.isArray(m.items) && m.items.length) return m.items.map(b => [+b[0], !!b[1]]);
    const times = (m && m.times) || [];
    if (times.length) return times.map(t => [+t, false]);
    if (tl.bpm) { const per = 60 / tl.bpm, out = []; for (let t = tl.downbeat || 0; t < durOf(tl) + 1; t += per) out.push([+t.toFixed(4), false]); return out; }
    return [];
  }
  function clipBeats(tl, c, half) {
    const b = songBeats(tl), out = [];
    for (let i = 0; i < b.length; i++) {
      out.push([b[i][0] - c.start, 1, b[i][1]]);
      if (half && i + 1 < b.length) out.push([(b[i][0] + b[i + 1][0]) / 2 - c.start, 0.5, false]);
    }
    return out.filter(x => x[0] > -0.5 && x[0] < c.dur + 0.5);
  }
  const AUTO_DEF = { min: 0.5, max: 2.0, lam: 2.5, jerk: 1.5, slip: 0.2, half: false, end: false, thr: 0.30, smooth: 0.08 };
  const AUTO_FIELDS = [['min', 0.05], ['max', 0.05], ['lam', 0.5], ['jerk', 0.5], ['slip', 0.05], ['thr', 0.05], ['smooth', 0.01]];
  const ADV_KEYS = ['in_rng', 'out_rng', 'fit', 'pins', 'grid_extra', 'until'];
  const advOf = a => Object.fromEntries(ADV_KEYS.filter(k => a[k] !== undefined && a[k] !== null && !(Array.isArray(a[k]) && !a[k].length) && a[k] !== false).map(k => [k, a[k]]));
  // 音ハメの設定（映像の欄と同じ並び）：前の設定（auto）に、欄の値 fields と「そのほかの設定」adv を重ねる。
  // fields・adv を渡さなければ、欄に出る値（既定 AUTO_DEF＋前の設定）のまま
  function warpAutoOpts(c, fields, adv) {
    const prev = (isPts(c) && c.warp.auto) || {}, a = Object.assign({}, AUTO_DEF, prev), f = fields || {}, o = {};
    for (const [k, v] of Object.entries(prev)) if (!ADV_KEYS.includes(k)) o[k] = v;
    for (const [k] of AUTO_FIELDS) o[k] = f[k] != null ? +f[k] : +a[k];
    o.half = f.half != null ? !!f.half : !!a.half; o.end = f.end != null ? !!f.end : !!a.end;
    const ad = adv || advOf(a);
    for (const k of ADV_KEYS) if (ad[k] !== undefined && ad[k] !== null) o[k] = ad[k];
    return o;
  }
  // 頼みの中身 q（/api/warp/auto）。o.in を決める（やり直すたびに前の結果の頭へずれていかないように前の値）。拍が無ければ null
  function warpAutoQuery(tl, c, o) {
    const beats = clipBeats(tl, c, o.half).map(b => [b[0], b[1]]);
    if (!beats.length) return null;
    const s0 = o.in != null ? +o.in : isPts(c) ? CALC.warpMap(c.warp, 0) : (c.in || 0);
    o.in = +Math.max(0, s0).toFixed(6);
    return Object.assign({ src: Array.isArray(c.src) ? c.src[0] : c.src, dur: c.dur, speed: c.speed || 1, beats }, o);
  }
  function warpAutoApply(c, r, o) {
    c.warp = { points: r.points, smooth: r.smooth, auto: o, accents: r.accents, pairs: r.pairs, method: r.method };
    c.in = +Math.max(0, CALC.warpMap(c.warp, 0)).toFixed(6);
  }

  // ---------- 書き出し ----------
  const pad = n => String(n).padStart(2, '0');
  // 書き出しの名前の初め（<タイムラインの名前>_<年月日-時分>。マスターは _master_ を挟む）
  function exportName(file, d, master) {
    const stem = String(file || 'export').split(/[\\/]/).pop().replace(/\.cut\.json$/, '').replace(/\.test$/, '');
    const n = `${stem}_${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
    return master ? n.replace(/_(\d{8}-\d{4})$/, '_master_$1') : n;
  }
  // マスターの窓で初めに選ばれている画質（作品の settings.master.upscale。無ければ PC の設定のモデルから）
  function masterUpscale(tl, settings, kinds) {
    const wup = ((tl.settings || {}).master || {}).upscale || '', K = kinds || { anime: 'realesr-animevideov3', real: 'realesrgan-x4plus' }, m = (settings || {}).esrganModel;
    return wup || (m === K.real ? 'real' : m === K.anime || !m ? 'anime' : '');
  }
  // 再生用の動画（MP4）をプレビューに使う
  function applyProxy(tl, proxy, note) { tl.preview = Object.assign({}, tl.preview || {}, { proxy, proxy_note: note }); }
  // 音のクリップのステム（Suno の audio-stems の歌・伴奏・楽器ごとの WAV など。2026-11-16）を、ミュートした音のトラックに 1 本ずつ置く
  // （解析の「ボーカルと伴奏に分ける」と同じ形：参照のトラックの前・同じ時刻と長さ・in と音量はもとのクリップと同じ＝曲の頭からのステム）。stems：[{src, name}]
  function placeStems(tl, c, stems, E) {
    const T0 = tl.tracks, ref = T0.findIndex(t => t.role === 'reference'), name = String(c.label || (c.src || '').split('/').pop() || c.id).slice(0, 24), ids = [];
    for (const s of stems) {
      const nm = String(s.name || '').slice(0, 24);
      const tr = { id: E.uid('t_audio'), name: E.t('an2.stemTrackPlaced', { nm, name }), kind: 'audio', role: 'sfx', muted: true, from_stems: c.id,
        clips: [{ id: E.uid('stem'), type: 'audio', src: s.src, start: c.start, dur: c.dur, in: c.in || 0, gain: c.gain || 0, fade_in: 0, fade_out: 0, label: E.t('an2.stemClip', { nm, name }) }] };
      T0.splice(ref >= 0 ? ref + ids.length : T0.length, 0, tr);
      ids.push(tr.id);
    }
    return ids;
  }

  // ---------- カットの段（cutmeta.js の中身。どれもタイムライン tl を直す） ----------
  function cuts(tl, E) {
    const fps = fpsOf(tl), FR = 1 / fps, snapFrame = t => snapF(fps, t);
    const TEXT_KEYS = ['lyric', 'togaki', 'text'];
    const isPic = c => c.type === 'video' || c.type === 'image' || c.type === 'plan';
    const isPerCut = c => c.type === 'effect' && !!E.isPerCut(c);
    const lab = it => String(it.label);
    const refs = label => allClips(tl).filter(({ c }) => c.cut != null && String(c.cut) === String(label));
    const cutsMeta = () => (tl.meta || []).find(m => m.kind === 'cuts');
    const sortItems = m => m.items.sort((a, b) => a.start - b.start);
    function nextLabel(m, it) {
      const used = new Set(m.items.map(lab)), L = lab(it);
      const ints = m.items.every(x => /^\d+$/.test(lab(x)));
      if (ints && m.items[m.items.length - 1] === it) {
        let s = String(Math.max(...m.items.map(x => +lab(x))) + 1); if (/^0\d/.test(L)) s = s.padStart(L.length, '0'); if (!used.has(s)) return s;
      }
      const mm = L.match(/^(\S*\d)([a-y])?(\s.*)?$/);
      if (mm) for (let ch = mm[2] ? mm[2].charCodeAt(0) + 1 : 98; ch <= 122; ch++) { const s = mm[1] + String.fromCharCode(ch) + (mm[3] || ''); if (!used.has(s)) return s; }
      for (let n = 2; ; n++) { const s = L + '-' + n; if (!used.has(s)) return s; }
    }
    function syncPerCut(m, labels) {
      const want = new Set(labels.map(String));
      for (const { c } of allClips(tl)) {
        if (!isPerCut(c) || c.cut == null || !want.has(String(c.cut))) continue;
        const it = m.items.find(x => lab(x) === String(c.cut)); if (!it) continue;
        c.start = r6(it.start); c.dur = r6(it.end - it.start);
      }
    }
    function mismatch(it) {
      const ps = refs(lab(it)).filter(({ c }) => isPic(c) && !c.disabled).map(({ c }) => c); if (!ps.length) return null;
      const m = cutsMeta(), i = m ? m.items.indexOf(it) : -1, nx = m && m.items[i + 1], tol = 0.5 / fps;
      const lo = Math.min(...ps.map(c => c.start)), hi = Math.max(...ps.map(c => c.start + c.dur));
      const out = (i > 0 && lo < it.start - tol) || (nx && hi > nx.start + tol);
      const hole = lo > it.start + tol || hi < (nx ? nx.start : it.end) - tol;
      return out || hole ? { lo, hi } : null;
    }
    const E_ = (k, c, v) => E.L('cm.err.' + k, Object.assign({ c: E.name(c) }, v || {}));
    function prepHead(c, dt) {
      if (c.dur - dt < FR - EPS) return { err: E_('outside', c) };
      if (c.type === 'plan') return { err: E_('plan', c) };
      if (c.type === 'image') {
        if (c.pop) return { err: E_('popHead', c) };
        return { apply: () => { if (Array.isArray(c.camera)) c.camera = c.camera.map(k => [r6(k[0] - dt), ...k.slice(1)]); c.start = r6(c.start + dt); c.dur = r6(c.dur - dt); } };
      }
      if (typeof c.warp === 'string') return { err: E_('tableHead', c) };
      if (c.land) return { err: E_('landHead', c) };
      if (isPts(c)) {
        const pts = c.warp.points.map(p => [r6(p[0] - dt), p[1]]), s0 = CALC.warpMap({ points: pts, smooth: c.warp.smooth }, 0);
        if (s0 < -1e-6) return { err: E_('shortHead', c, { t: fmt(c.start + dt) }) };
        return { apply: () => { c.warp.points = pts; c.in = r6(Math.max(0, s0)); c.start = r6(c.start + dt); c.dur = r6(c.dur - dt); } };
      }
      const nin = (c.in || 0) + dt * (c.speed || 1);
      if (nin < -1e-6) return { err: E_('shortHeadIn', c, { t: fmt(c.start + dt), in: (+(c.in || 0)).toFixed(3) }) };
      return { apply: () => { c.in = r6(Math.max(0, nin)); c.start = r6(c.start + dt); c.dur = r6(c.dur - dt); } };
    }
    function prepTail(c, e) {
      const nd = r6(e - c.start);
      if (nd < FR - EPS) return { err: E_('outside', c) };
      if (c.type === 'plan') return { err: E_('plan', c) };
      const apply = () => { c.dur = r6(e - c.start); };
      if (c.type === 'image') return c.pop && nd > c.dur ? { err: E_('pop', c) } : { apply };
      if (c.land) return { err: E_('landTail', c) };
      if (nd > c.dur + EPS) {
        if (typeof c.warp === 'string') return { err: E_('tableTail', c) };
        const L = E.srcDur(c); if (L == null) return { err: E_('noLen', c) };
        const end = isPts(c) ? CALC.warpMap(c.warp, nd) : (c.in || 0) + nd * (c.speed || 1);
        if (end > L + 0.5 / fps) return { err: E_('shortTail', c, { t: fmt(e), need: end.toFixed(3), have: (+L).toFixed(3) }) };
      }
      return { apply };
    }
    function prepAlign(m, it) {
      const ps = refs(lab(it)).filter(({ c }) => isPic(c) && !c.disabled).map(({ c }) => c); if (!ps.length) return { ops: [] };
      const i = m.items.indexOf(it), nx = m.items[i + 1], tol = 0.5 / fps;
      const lo = Math.min(...ps.map(c => c.start)), hi = Math.max(...ps.map(c => c.start + c.dur)), End = nx ? nx.start : it.end;
      const ops = [], what = [];
      if ((i > 0 && lo < it.start - tol) || lo > it.start + tol) {
        for (const c of ps.filter(c => Math.abs(c.start - lo) < tol)) { const p = prepHead(c, it.start - c.start); if (p.err) return p; ops.push(p.apply); }
        what.push(E.L('cm.whatHead', { a: fmt(lo), b: fmt(it.start) }));
      }
      if ((nx && hi > nx.start + tol) || hi < End - tol) {
        for (const c of ps.filter(c => Math.abs(c.start + c.dur - hi) < tol)) { const p = prepTail(c, End); if (p.err) return p; ops.push(p.apply); }
        what.push(E.L('cm.whatTail', { a: fmt(hi), b: fmt(End) }));
      }
      return { ops, what: { toString: () => what.map(String).join(E.t('sep.list')) } };
    }
    // 映像をカットに合わせる準備：{todo:[[it, p], …]} か {err（そのカットのラベル label と理由）}。直すのは applyAlign
    function planAlign(items) {
      const m = cutsMeta(); if (!m) return { todo: [] };
      const todo = [];
      for (const it of items) {
        if (!m.items.includes(it) || !mismatch(it)) continue;
        const p = prepAlign(m, it); if (p.err) return { err: p.err, label: lab(it) };
        if (p.ops.length) todo.push([it, p]);
      }
      return { todo };
    }
    function applyAlign(todo) { for (const [, p] of todo) for (const f of p.ops) f(); for (const tr of tl.tracks) if (tr.kind === 'video' || tr.kind === 'media') tr.clips.sort((a, b) => a.start - b.start); }
    function edgeRange(m, it, side) {
      const i = m.items.indexOf(it), pv = m.items[i - 1], nx = m.items[i + 1], mf = FR;
      if (side === 'l') {
        const adj = pv && Math.abs(pv.end - it.start) < mf / 2;
        return { lo: adj ? pv.start + mf : pv ? Math.min(pv.end, it.start) : 0, hi: it.end - mf, nb: adj ? pv : null };
      }
      const adj = nx && Math.abs(nx.start - it.end) < mf / 2;
      return { lo: it.start + mf, hi: adj ? nx.end - mf : nx ? Math.max(nx.start, it.end) : Math.max(durOf(tl), it.end), nb: adj ? nx : null };
    }
    function applyEdge(m, it, side, t) {
      const { lo, hi, nb } = edgeRange(m, it, side), v = r6(Math.max(lo, Math.min(hi, snapFrame(t))));
      if (Math.abs(v - (side === 'l' ? it.start : it.end)) < EPS) return null;
      if (side === 'l') { it.start = v; if (nb) nb.end = v; } else { it.end = v; if (nb) nb.start = v; }
      sortItems(m); syncPerCut(m, [lab(it)].concat(nb ? [lab(nb)] : []));
      return { v, nb, side };
    }
    function picSplittable(c) {
      if (c.type === 'video') return typeof c.warp !== 'string' && !c.land;
      if (c.type === 'image') return !c.pop;
      return false;
    }
    const whyNot = c => E.L(c.type === 'plan' ? 'cm.whyNot.plan' : c.pop ? 'cm.whyNot.pop' : typeof c.warp === 'string' ? 'cm.whyNot.table' : 'cm.whyNot.land');
    function splitPic(tr, c, t, nl) {
      const off = r6(t - c.start), R = JSON.parse(JSON.stringify(c));
      R.id = E.uid(c.type === 'video' ? 'vid' : c.type); R.start = r6(t); R.dur = r6(c.dur - off); R.cut = nl; delete R.link;
      c.dur = off;
      if (c.type === 'video') {
        if (isPts(c)) { R.warp.points = c.warp.points.map(p => [r6(p[0] - off), p[1]]); R.in = r6(Math.max(0, CALC.warpMap(R.warp, 0))); }
        else R.in = r6((c.in || 0) + off * (c.speed || 1));
      } else if (Array.isArray(c.camera)) R.camera = c.camera.map(k => [r6(k[0] - off), ...k.slice(1)]);
      tr.clips.splice(tr.clips.indexOf(c) + 1, 0, R);
    }
    function splitErr(it, t) {
      if (!(t >= it.start + FR - EPS && t <= it.end - FR + EPS)) return E.L('cm.splitInside', { label: lab(it) });
      const bad = refs(lab(it)).filter(({ c }) => c.start < t - EPS && c.start + c.dur > t + EPS && isPic(c) && !c.disabled && !picSplittable(c));
      return bad.length ? E.L('cm.splitNo', { label: lab(it), t: fmt(t), what: whyNot(bad[0].c), name: E.label(bad[0].c) }) : null;
    }
    function splitIn(m, it, t) {
      const old = lab(it), nl = nextLabel(m, it);
      const n = { moved: 0, dupFx: 0, splitPic: 0 };
      const ni = JSON.parse(JSON.stringify(it)); ni.label = nl; ni.start = t; for (const k of TEXT_KEYS) if (k in ni) ni[k] = '';
      delete ni.from_plan;
      it.end = t; m.items.push(ni); sortItems(m);
      for (const { c, tr } of refs(old)) {
        const s = c.start, e = c.start + c.dur;
        if (s >= t - EPS) { c.cut = nl; n.moved++; continue; }
        if (e <= t + EPS) continue;
        if (isPic(c)) { if (picSplittable(c)) { splitPic(tr, c, t, nl); n.splitPic++; } continue; }
        if (c.type !== 'effect' && c.type !== 'subtitle') continue;
        const d = JSON.parse(JSON.stringify(c)); d.id = E.uid(c.type === 'effect' ? (c.effect || 'fx') : c.type); d.cut = nl;
        tr.clips.splice(tr.clips.indexOf(c) + 1, 0, d); n.dupFx++;
      }
      syncPerCut(m, [old, nl]);
      return { ni, n };
    }
    // gone を隣の keep に吸わせる → {moved, dropped}
    function absorbIn(m, gone, keep) {
      const g = lab(gone), k = lab(keep); let moved = 0, dropped = 0;
      if (keep.start > gone.start) keep.start = gone.start; else keep.end = gone.end;
      m.items.splice(m.items.indexOf(gone), 1);
      const have = new Set(refs(k).filter(({ c }) => isPerCut(c)).map(({ c }) => c.effect));
      const sig = c => JSON.stringify([c.type, c.effect || '', r6(c.start), r6(c.dur), c.params || null, c.text || null]);
      const twins = new Set(refs(k).filter(({ c }) => (c.type === 'effect' || c.type === 'subtitle') && !isPerCut(c)).map(({ c, tr }) => tr.id + '|' + sig(c)));
      for (const { c, tr } of refs(g)) {
        if ((isPerCut(c) && have.has(c.effect)) || twins.has(tr.id + '|' + sig(c))) { tr.clips.splice(tr.clips.indexOf(c), 1); dropped++; }
        else { c.cut = k; moved++; }
      }
      syncPerCut(m, [k]);
      return { moved, dropped, g, k };
    }
    function renameIn(it, nl) { const old = lab(it); let n = 0; it.label = nl; for (const { c } of refs(old)) { c.cut = nl; n++; } return n; }
    const uniq = (m, want) => { const used = new Set(m.items.map(lab)); if (!used.has(want)) return want; for (let k = 2; ; k++) if (!used.has(want + '-' + k)) return want + '-' + k; };
    function autoLabel(m, name) {
      const w = String(name || '').replace(/[\r\n\t]+/g, ' ').trim().replace(/^カット\s*/, '').slice(0, 40).trim();
      if (w) return uniq(m, w);
      const nums = m.items.map(lab).filter(x => /^\d+$/.test(x)).map(Number);
      return uniq(m, String(nums.length ? Math.max(...nums) + 1 : m.items.length + 1));
    }
    function rangePlan(m, s, e) {
      const tol = 0.5 / fps;
      if (!(e - s >= FR - EPS)) return { err: E.L('cm.rangeShort') };
      if (!m) return { kind: 'new' };
      const ex = m.items.find(x => Math.abs(x.start - s) < tol && Math.abs(x.end - e) < tol); if (ex) return { kind: 'exist', it: ex };
      const ov = m.items.filter(x => x.start < e - tol && x.end > s + tol);
      if (!ov.length) return { kind: 'new' };
      const it = ov[0];
      if (ov.length > 1 || it.start > s + tol || it.end < e - tol) return { err: E.L('cm.rangeSpans', { a: fmt(s), b: fmt(e), labels: { toString: () => ov.map(lab).join(E.t('sep.list')) } }) };
      const s1 = r6(snapFrame(s)), e1 = r6(snapFrame(e));
      const er = (s1 > it.start + tol ? splitErr(it, s1) : null) || (e1 < it.end - tol ? splitErr(it, e1) : null);
      return er ? { err: er } : { kind: 'split', it };
    }
    function newMetaId(base) { const ids = new Set((tl.meta || []).map(m => m.id)); let id = base, k = 2; while (ids.has(id)) id = base + '_' + k++; return id; }
    function ensureCuts() {
      let m = cutsMeta(); if (m) { if (!Array.isArray(m.items)) m.items = []; return m; }
      m = { id: newMetaId('m_cuts'), kind: 'cuts', name: E.t('lane.cuts'), items: [] }; tl.meta = tl.meta || []; tl.meta.unshift(m); return m;
    }
    function ensureNotes() {
      let m = (tl.meta || []).find(x => x.kind === 'notes'); if (m) return m;
      m = { id: newMetaId('m_notes'), kind: 'notes', name: E.t('lane.notes'), items: [] }; tl.meta = tl.meta || [];
      const i = tl.meta.findIndex(x => x.kind === 'cuts'); tl.meta.splice(i < 0 ? tl.meta.length : i + 1, 0, m); return m;
    }
    function rangeIn(s, e, name, extra) {
      const m0 = cutsMeta(), p = rangePlan(m0, s, e); if (p.err) return p;
      if (p.kind === 'exist') return { it: p.it, kind: 'exist' };
      const m = ensureCuts(), tol = 0.5 / fps;
      if (p.kind === 'new') {
        const it = Object.assign({ label: autoLabel(m, name), start: r6(snapFrame(s)), end: r6(snapFrame(e)) }, extra || {});
        m.items.push(it); sortItems(m); return { it, kind: 'new' };
      }
      let it = p.it; const s1 = r6(snapFrame(s)), e1 = r6(snapFrame(e));
      if (s1 > it.start + tol) it = splitIn(m, it, s1).ni;
      if (e1 < it.end - tol) splitIn(m, it, e1);
      if (it !== p.it) { const nl = autoLabel(m, name); if (nl !== lab(it)) renameIn(it, nl); Object.assign(it, extra || {}); }
      return { it, kind: 'split' };
    }
    // クリップ c の範囲をカットにする（映像クリップなら cut もそのラベルに）→ rangeIn の結果
    function cutFromClipIn(c) {
      const plan = c.type === 'plan' ? c : c.from_plan && (findClip(tl, c.from_plan) || {}).clip;
      const r = rangeIn(c.start, c.start + c.dur, plan ? plan.label : c.type === 'video' ? '' : c.label, plan ? { from_plan: plan.id } : null);
      if (r.it && c.type === 'video') c.cut = lab(r.it);
      return r;
    }
    const onAdopt = () => !!((tl.settings || {}).cuts_on_adopt);
    // 🎬 採用のとき：作品の settings.cuts_on_adopt なら、予定のクリップの範囲をカットにして、映像クリップ vc の cut をそのラベルに（エフェクトの META が届いていなければしない）
    function adoptIn(plan, vc) {
      if (!onAdopt() || !E.fxReady) return null;
      const r = rangeIn(plan.start, plan.start + plan.dur, plan.label, { from_plan: plan.id }); if (r.err) return r;
      vc.cut = lab(r.it); return { label: lab(r.it), kind: r.kind };
    }
    function setOnAdoptIn(on) { tl.settings = tl.settings || {}; if (on) tl.settings.cuts_on_adopt = true; else delete tl.settings.cuts_on_adopt; }
    // 最初のカット（全体・ラベル 1）。カットの無いあいだに全体に置いた per_cut のエフェクトは、このカットのものに → {it, conv}（もうあれば null）
    function firstCutIn() {
      const m = ensureCuts(); if (m.items.length) return null;
      const it = { label: '1', start: 0, end: r6(durOf(tl)) }; m.items.push(it); let conv = 0;
      for (const { c } of allClips(tl)) if (isPerCut(c) && c.cut == null) { c.cut = '1'; c.start = 0; c.dur = r6(durOf(tl)); conv++; }
      return { it, conv };
    }
    const itemAt = (m, t) => m.items.find(x => t >= x.start && t < x.end);
    const byLabel = label => { const m = cutsMeta(); return m && m.items.find(x => lab(x) === String(label)); };
    return { lab, refs, cutsMeta, nextLabel, syncPerCut, mismatch, prepHead, prepTail, prepAlign, planAlign, applyAlign, edgeRange, applyEdge, picSplittable, whyNot,
      splitErr, splitIn, absorbIn, renameIn, autoLabel, rangePlan, rangeIn, ensureCuts, ensureNotes, cutFromClipIn, onAdopt, adoptIn, setOnAdoptIn, firstCutIn, itemAt, byLabel, snapFrame };
  }

  // ---------- クリップを動かす・伸び縮み・分ける・詰める・伸ばす（editor.js の moveClip・trimClip、cutedit.js、warp.js の「伸ばす」） ----------
  // クリップの窓（どこをつかめるか）：エフェクトは META の window（無ければ動かせない）、映像・画像はカットに付いていなければ動かせる
  const CLIP_WIN = { tts: { clip: true, trimIn: true }, audio: { clip: true, trimIn: true }, subtitle: { clip: true }, plan: { clip: true } };
  const clipWin = (c, fxMeta) => c.type === 'effect' ? ((fxMeta && fxMeta(c)) || {}).window || { fixed: true }
    : CLIP_WIN[c.type] || ((c.type === 'image' || c.type === 'video') ? (c.cut == null ? { clip: true, trimIn: c.type === 'video' } : { fixed: true }) : {});
  // E.fxMeta(c)：エフェクトの META（time_params・window）。linkOn：🔗 連動（リンクしたクリップも一緒に）
  function clipEdit(tl, E) {
    const fps = fpsOf(tl), FR = 1 / fps, fxMeta = c => (E.fxMeta && E.fxMeta(c)) || {};
    const win = c => clipWin(c, fxMeta), movable = c => { const w = win(c); return !w.fixed && !w.per_cut; };
    const clips = () => allClips(tl);
    function cutAt(t) { const m = (tl.meta || []).find(x => x.kind === 'cuts'); if (!m) return null; let c = m.items[0]; for (const x of m.items) if (t >= x.start) c = x; return c; }
    function shiftTimes(obj, paths, dt) {
      const walk = (o, segs) => {
        if (o == null) return o;
        if (!segs.length) {
          if (typeof o === 'number') return snapT(fps, o + dt);
          if (Array.isArray(o)) return o.map(v => typeof v === 'number' ? snapT(fps, v + dt) : (Array.isArray(v) && typeof v[0] === 'number' ? [snapT(fps, v[0] + dt), ...v.slice(1)] : v));
          return o;
        }
        const [h, ...rest] = segs;
        if (h === '*') { if (Array.isArray(o)) return o.map(v => walk(v, rest)); return o; }
        if (typeof o === 'object' && h in o) o[h] = walk(o[h], rest);
        return o;
      };
      for (const p of paths || []) walk(obj, p.split('.'));
    }
    function moveClip(c, dt) {
      c.start = +(c.start + dt).toFixed(6); if (c.type === 'effect') shiftTimes(c.params, fxMeta(c).time_params, dt);
      if (c.cut != null) { const w = win(c); const cu = cutAt(c.start + (w.lead || 0) + 1e-6); if (cu) c.cut = String(cu.label); }
    }
    function trimClip(c, side, dt) {
      const w = win(c), p = c.params || {}; let s = c.start, e = c.start + c.dur;
      if (side === 'l') s = Math.min(e - FR, s + dt); else e = Math.max(s + FR, e + dt);
      if (side === 'l' && w.trimIn && isPts(c)) {
        const di = s - c.start; c.warp.points = c.warp.points.map(q => [+(q[0] - di).toFixed(6), q[1]]); c.in = +Math.max(0, CALC.warpMap(c.warp, 0)).toFixed(6);
      } else if (side === 'l' && w.trimIn) { const di = Math.max(-(c.in || 0), s - c.start); s = c.start + di; c.in = +((c.in || 0) + di).toFixed(6); }
      c.start = +s.toFixed(6); c.dur = +(e - s).toFixed(6);
      if (w.start) p[w.start] = rT(fps, s + (w.lead || 0));
      if (w.end) p[w.end] = rT(fps, e);
      if (w.dur) p[w.dur] = rT(fps, e - s - (w.lead || 0) - (w.extra ? (p[w.extra] || 0) : 0));
    }
    function linkGroup(id, linkOn) {
      const f = findClip(tl, id); if (!f) return [];
      if (!linkOn || !f.clip.link) return [id];
      return clips().filter(({ c }) => c.link === f.clip.link).map(({ c }) => c.id);
    }
    const withLinks = (ids, linkOn) => { const out = new Set(); for (const id of ids) for (const x of linkGroup(id, linkOn)) out.add(x); return [...out]; };
    const SPLITTABLE = new Set(['video', 'image', 'audio', 'tts', 'subtitle']);
    const spans = (c, t) => t > c.start + 1e-6 && t < c.start + c.dur - 1e-6;
    const canSplit = c => SPLITTABLE.has(c.type) && movable(c) && typeof c.warp !== 'string';
    // c を時刻 t で2つに（c が左、右を新しく作って返す）。音・動画は右の素材の場所（in）を合わせる。フェードは外側だけ残す
    function splitClip(tr, c, t, linkMap) {
      const off = r6(t - c.start); if (off < FR - 1e-6 || c.dur - off < FR - 1e-6) return null;
      const R = JSON.parse(JSON.stringify(c)); R.id = E.uid(c.type === 'video' ? 'vid' : c.type); R.start = r6(t); R.dur = r6(c.dur - off);
      c.dur = off;
      if (c.fade_out) c.fade_out = 0; if (R.fade_in) R.fade_in = 0;
      if (c.fade_in > c.dur) c.fade_in = r6(c.dur); if (R.fade_out > R.dur) R.fade_out = r6(R.dur);
      if (isPts(c)) { R.warp.points = c.warp.points.map(p => [r6(p[0] - off), p[1]]); R.in = r6(Math.max(0, CALC.warpMap(R.warp, 0))); }
      else if (win(c).trimIn) R.in = r6((c.in || 0) + off * (c.type === 'video' ? (c.speed || 1) : 1));
      if (Array.isArray(c.ramp)) { const k = off / (off + R.dur), mid = c.ramp[0] + (c.ramp[1] - c.ramp[0]) * k; R.ramp = [r6(mid), c.ramp[1]]; c.ramp = [c.ramp[0], r6(mid)]; }
      if (c.link) R.link = linkMap[c.link] = linkMap[c.link] || E.uid('lk');
      tr.clips.push(R); tr.clips.sort((a, b) => a.start - b.start);
      return R;
    }
    // 分けられるもの（ids とそのリンク、t にかかるもの）を t で分ける → 分けた数（分けるものが無ければ 0。直さない）
    const splitList = (t, ids, linkOn) => withLinks(ids, linkOn).map(id => findClip(tl, id)).filter(f => f && canSplit(f.clip) && spans(f.clip, t));
    function splitAt(t, ids, linkOn) { const list = splitList(t, ids, linkOn), linkMap = {}; let n = 0; for (const f of list) if (splitClip(f.track, f.clip, t, linkMap)) n++; return n; }
    // 見えているトラックで t にかかるもの全部（再生位置で分ける・選んでいないとき）
    const idsAt = (t, hideShy) => clips().filter(({ c, tr }) => !tr.hidden && !(tr.shy && hideShy) && spans(c, t)).map(({ c }) => c.id);
    // リップル削除：消して、同じトラックの後ろのクリップを消した長さだけ前へ詰める → 消した数
    function rippleDelete(ids0, linkOn) {
      const ids = new Set(withLinks(ids0, linkOn).filter(id => { const f = findClip(tl, id); return f && movable(f.clip); })); if (!ids.size) return 0;
      for (const tr of tl.tracks) {
        const gone = tr.clips.filter(c => ids.has(c.id)).sort((a, b) => b.start - a.start); if (!gone.length) continue;
        for (const g of gone) {
          tr.clips = tr.clips.filter(c => c !== g);
          for (const c of tr.clips) if (c.start >= g.start + g.dur - 1e-6 && movable(c)) moveClip(c, -g.dur);
        }
        tr.clips.sort((a, b) => a.start - b.start);
      }
      return ids.size;
    }
    // 消す（リンクも）→ 消した数
    function deleteClips(ids0, linkOn) { const ids = new Set(withLinks(ids0, linkOn)); for (const tr of tl.tracks) tr.clips = tr.clips.filter(c => !ids.has(c.id)); return ids.size; }
    // 隙間を詰める：トラック trs（の並び）の最初のクリップから後ろを隙間なく並べる。リンクも同じだけ動かす → 動かした数
    function closeGaps(trs, linkOn) {
      let moved = 0;
      for (const tr of trs) {
        const cs = tr.clips.filter(movable).sort((a, b) => a.start - b.start); if (!cs.length) continue;
        let cur = cs[0].start + cs[0].dur;
        for (const c of cs.slice(1)) {
          if (c.start > cur + 1e-6) { const dt = cur - c.start; for (const id of linkGroup(c.id, linkOn)) { const g = findClip(tl, id); if (g && movable(g.clip)) moveClip(g.clip, dt); } moved++; }
          cur = Math.max(cur, c.start + c.dur);
        }
        tr.clips.sort((a, b) => a.start - b.start);
      }
      return moved;
    }
    // ⟷ フッテージを伸ばす（映像の欄）：次のクリップの頭まで・動画化予定の長さ
    function nextTo(x) {
      const f = findClip(tl, x.id); if (!f) return null; const end = x.start + x.dur;
      const nx = f.track.clips.filter(o => o !== x && o.start >= end - 1e-6).sort((a, b) => a.start - b.start)[0];
      return nx ? +(nx.start - x.start).toFixed(6) : null;
    }
    function planTo(x) { const p = x.from_plan && findClip(tl, x.from_plan); return p ? +(p.clip.start + p.clip.dur - x.start).toFixed(6) : null; }
    // x を長さ T に（slow＝速さを落として同じ中身を T に／hold＝そのまま長くして、素材が尽きたら最後のコマで止まる。リンクした音も同じ終わりまで）
    function stretch(x, T, how, linkOn) {
      if (!(T >= FR)) return false;
      if (how === 'slow') {
        if (x.warp) return false;
        x.speed = +((x.speed || 1) * x.dur / T).toFixed(6); if (Math.abs(x.speed - 1) < 1e-9) delete x.speed;
        x.dur = +T.toFixed(6); return true;
      }
      trimClip(x, 'r', T - x.dur);
      for (const id of linkGroup(x.id, linkOn)) {
        const g = findClip(tl, id); if (!g || g.clip === x || g.clip.type !== 'audio' || Math.abs(g.clip.start - x.start) > 1e-6) continue;
        trimClip(g.clip, 'r', x.start + x.dur - (g.clip.start + g.clip.dur));
      }
      return true;
    }
    return { win, movable, cutAt, shiftTimes, moveClip, trimClip, linkGroup, withLinks, spans, canSplit, splitClip, splitList, splitAt, idsAt, rippleDelete, deleteClips, closeGaps, nextTo, planTo, stretch };
  }

  // ---------- AI を追う（オートモード）：外の直しの前と後を比べて、変わったクリップを見つける ----------
  // → [{id, start, dur, gone}]（足された・動いた・長さや中身が変わったもの。消えたものは前の場所で gone）。並びはタイムラインの中の順
  function changedClips(before, after) {
    const was = new Map(), now = new Map();
    for (const tr of (before && before.tracks) || []) for (const c of tr.clips || []) was.set(c.id, { c, tr: tr.id });
    for (const tr of (after && after.tracks) || []) for (const c of tr.clips || []) now.set(c.id, { c, tr: tr.id });
    const out = [];
    for (const [id, x] of now) { const o = was.get(id); if (!o || o.tr !== x.tr || JSON.stringify(o.c) !== JSON.stringify(x.c)) out.push({ id, start: +x.c.start || 0, dur: +x.c.dur || 0, gone: false }); }
    for (const [id, o] of was) if (!now.has(id)) out.push({ id, start: +o.c.start || 0, dur: +o.c.dur || 0, gone: true });
    return out;
  }

  const api = { fmt, r6, isPts, findClip, allClips, onFrame, snapT, rT, durTo, normalizeTimes, contentEnd, finish,
    GEMINI_MODELS, ttsEffective, ttsEngine, ttsRequest, ttsTempo, ttsAddTake, ttsSelectTake, ttsOverlaps, ttsLines, cleanLine, silentOnly, subLines, subsFromLines,
    blankFrame, planFrameTake, planVideoTake, adoptDur, latestTake, pendingAdopt, adopt,
    audioTrackFor, audioClipFor, vaSrc, vaWhy, vaPlace, placeVideo,
    songBeats, clipBeats, AUTO_DEF, AUTO_FIELDS, ADV_KEYS, advOf, warpAutoOpts, warpAutoQuery, warpAutoApply,
    exportName, masterUpscale, applyProxy, placeStems, cuts, clipWin, clipEdit, changedClips };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.MITTLER_OPS = api;
})(this);
