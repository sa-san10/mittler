// Mittler 編集画面：TTS（セリフ）・字幕・音・画像のクリップ、トラックの追加と設定、再生中の音（Web Audio）。editor.js のあとに読む。
// TTS のクリップ：{type:'tts', character, engine:'gemini'|'voicevox', text（タグもそのまま送る）, label（タイムラインの表示）,
//   gemini:{model, voice, style}, delivery_style（このシーンの演技。Gemini ではスタイルのあとに「 / 」でつないで送る）, voicevox:{speaker, speedScale…}（空ならキャラ設定 characters.json の値）, takes:[{id, src, dur, engine, text…}], activeTake,
//   gain（dB）, in, fade_in, fade_out}。生成ボタンはサーバーの /api/tts（tools/tts_gen.py）→ 新しいテイクにして選ぶ。
// 字幕のクリップ：{type:'subtitle', text, style:{…}}（effects/subtitle.py が描く。style が空なら下の真ん中の字幕の初期値）。
// 音のクリップ：{type:'audio', src, in, gain, norm, fade_in, fade_out, ramp}（効果音・BGM。書き出しは pyengine/mittler/mix.py）。
'use strict';
(() => {
  const GEMINI_VOICES = ['Zephyr', 'Puck', 'Charon', 'Kore', 'Fenrir', 'Leda', 'Orus', 'Aoede', 'Callirrhoe', 'Autonoe', 'Enceladus', 'Iapetus', 'Umbriel', 'Algieba',
    'Despina', 'Erinome', 'Algenib', 'Rasalgethi', 'Laomedeia', 'Achernar', 'Alnilam', 'Schedar', 'Gacrux', 'Pulcherrima', 'Achird', 'Zubenelgenubi', 'Vindemiatrix',
    'Sadachbia', 'Sadaltager', 'Sulafat'];
  const GEMINI_MODELS = OPS.GEMINI_MODELS;  // 生成の頼み・テイクの入れ方・まとめて生成するセリフ・セリフから字幕は editor/ops.js（API と同じもの）
  // VOICEVOX の欄：鍵・名前（$L）・下限・上限・刻み
  const VV_KEYS = [['speedScale', $L('vv.speed'), 0.5, 2, 0.05], ['pitchScale', $L('vv.pitch'), -0.15, 0.15, 0.01], ['intonationScale', $L('vv.inton'), 0, 2, 0.05],
    ['volumeScale', $L('vv.volume'), 0, 2, 0.05], ['prePhonemeLength', $L('vv.pre'), 0, 1.5, 0.05], ['postPhonemeLength', $L('vv.post'), 0, 1.5, 0.05]];
  const SUB_DEFAULT = { font: 'assets/fonts/NotoSerifJP-Regular.ttf', size: 56, color: [245, 243, 234], stroke: 2, stroke_color: [24, 32, 48], stroke_alpha: 0.44,
    shadow: 2, shadow_color: [24, 32, 48], shadow_alpha: 0.25, x: null, y: null, align: 'center', valign: 'bottom', line_gap: 8, spacing: 1, margin_v: 65 };
  let vvSpeakers = null;
  const nonEmpty = o => Object.fromEntries(Object.entries(o || {}).filter(([, v]) => v !== '' && v !== null && v !== undefined));
  const num = (v, d) => (v === '' || v == null || !isFinite(+v)) ? d : +v;
  const hex = v => '#' + (v || [255, 255, 255]).map(x => Math.round(x).toString(16).padStart(2, '0')).join('');
  const unhex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const uid = p => p + '_' + Math.random().toString(36).slice(2, 8);
  const chars = () => (S.chars && S.chars.characters) || [];
  async function speakers() {
    if (vvSpeakers) return vvSpeakers;
    try { const d = await (await fetch('/api/voicevox/speakers')).json(); vvSpeakers = d.flatMap(s => s.styles.map(st => ({ id: st.id, name: $t('vv.speakerStyle', { name: s.name, style: st.name }) }))); }
    catch (e) { vvSpeakers = []; }
    return vvSpeakers;
  }
  const effective = c => OPS.ttsEffective(c, chars());
  const takeOf = c => (c.takes || []).find(k => k.id === c.activeTake);
  function playUrl(url, from) { const a = new Audio(url); a.currentTime = from || 0; a.play().catch(() => { }); return a; }
  let previewAudio = null;
  function preview(url, from) { if (previewAudio) previewAudio.pause(); previewAudio = playUrl(url, from); }

  // ---------- 右の欄 ----------
  window.MITTLER_INSPECT = (c, f) => {
    if (c.type === 'tts') { inspectTts(c, f); return true; }
    if (c.type === 'subtitle') { inspectSub(c, f); return true; }
    if (c.type === 'audio') { inspectAudio(c, f); return true; }
    if (c.type === 'image') { inspectImage(c, f); return true; }
    return false;
  };
  const head = (c, f, title) => `<div class="metaRow"><b>${title}</b>${esc(f.track.name || f.track.id)}</div>
    <div class="btns"><button data-act="off">${$t(c.disabled ? 'sel.enable' : 'sel.disable')}</button><button data-act="del">${$t('sel.delete')}</button></div>`;
  function bindHead(el, c) {
    el.querySelector('[data-act="off"]').onclick = () => change(() => { if (c.disabled) delete c.disabled; else c.disabled = true; });
    el.querySelector('[data-act="del"]').onclick = () => deleteClip(c.id);
  }
  const timeFields = (c, withIn) => `<label>${$t('f.start')}</label><input data-k="start" type="number" step="${1 / fps()}" value="${+c.start.toFixed(3)}">
    <label>${$t('f.dur')}</label><input data-k="dur" type="number" step="${1 / fps()}" min="${1 / fps()}" value="${+c.dur.toFixed(3)}">
    ${withIn ? `<label>${$t('f.in')}</label><input data-k="in" type="number" step="0.01" min="0" value="${+(c.in || 0).toFixed(3)}">` : ''}`;
  function bindNums(el, c, keys) {
    for (const k of keys) {
      const inp = el.querySelector(`[data-k="${k}"]`); if (!inp) continue;
      // 開始・長さはコマにそろえる（開始は 0 より前にしない、長さは 1 コマより短くしない。editor.js の setClipStart・setClipDur）。素材の頭・フェードは 0 より小さくしない
      inp.onchange = () => {
        const v = parseFloat(inp.value); if (!isFinite(v)) return;
        change(() => { if (k === 'start') setClipStart(c, v); else if (k === 'dur') setClipDur(c, v); else c[k] = +(k === 'gain' ? v : Math.max(0, v)).toFixed(6); }, { keepForm: true });
        const now = +(+(c[k] || 0)).toFixed(3); if (+inp.value !== now) inp.value = now;  // そろえた・止めた値を欄にも出す
      };
    }
  }
  const soundFields = c => `<label>${$t('f.gain')}</label><input data-k="gain" type="number" step="0.5" value="${c.gain || 0}">
    <label>${$t('f.fadeIn')}</label><input data-k="fade_in" type="number" step="0.05" min="0" value="${c.fade_in || 0}">
    <label>${$t('f.fadeOut')}</label><input data-k="fade_out" type="number" step="0.05" min="0" value="${c.fade_out || 0}">
    ${['fade_in_curve', 'fade_out_curve'].map(k => `<label>${$t(k === 'fade_in_curve' ? 'f.fadeInCurve' : 'f.fadeOutCurve')}</label><select data-curve="${k}">${FADE_CURVES.map(v => `<option value="${v}" ${(c[k] || 'tri') === v ? 'selected' : ''}>${$t('curve.' + v)}</option>`).join('')}</select>`).join('')}`;
  // フェードの形（ffmpeg の afade の curve。pyengine/mittler/mix.py）。名前は辞書の curve.<形>
  const FADE_CURVES = ['tri', 'qsin', 'hsin', 'esin', 'log', 'exp', 'par', 'qua', 'cub'];
  function bindCurves(el, c) {
    for (const sel of el.querySelectorAll('[data-curve]')) sel.onchange = () => change(() => { const k = sel.dataset.curve; if (sel.value === 'tri') delete c[k]; else c[k] = sel.value; }, { keepForm: true });
  }

  async function inspectTts(c, f) {
    const el = $('sel'); el.className = ''; const e = effective(c); const engine = c.engine || (e.ch.tts || {}).default_engine || 'gemini';
    const spk = await speakers(); if (S.sel !== c.id) return;
    const takes = (c.takes || []).map(k => `<div class="take${k.id === c.activeTake ? ' on' : ''}" data-take="${esc(k.id)}">
        <input type="radio" name="tk" ${k.id === c.activeTake ? 'checked' : ''}><button class="play" title="${esc($t('tts.listen'))}">${MITTLER_ICON('play')}</button>
        <span class="tid">${esc(k.id)}</span><span class="tdim">${esc($t('tts.takeInfo', { engine: k.engine || '', sec: (+k.dur || 0).toFixed(2) }))}</span>
        <span class="ttext" title="${esc(k.text || k.note || '')}">${esc(k.text || k.note || '')}</span></div>`).join('') || `<div class="empty">${$t('tts.noTakes')}</div>`;
    const charSet = v => esc($t('tts.charSetting', { v }));  // 「キャラ設定（値）」
    el.innerHTML = head(c, f, $t('tts.title')) + `
      <div class="form">
        <label>${$t('tts.char')}</label><select data-k="character">${chars().map(ch => `<option value="${esc(ch.id)}" ${ch.id === c.character ? 'selected' : ''}>${esc(ch.name)}</option>`).join('')}${charOf(c.character) ? '' : `<option selected>${esc(c.character || '')}</option>`}</select>
        <label>${$t('tts.engine')}</label><select data-k="engine"><option value="gemini" ${engine === 'gemini' ? 'selected' : ''}>Gemini TTS</option><option value="voicevox" ${engine === 'voicevox' ? 'selected' : ''}>VOICEVOX</option></select>
        <label title="${esc($t('tts.tempo.tip'))}">${$t('tts.tempo')}</label><input data-k="tempo" type="number" min="0.5" max="2" step="0.05" value="${c.tempo ?? ''}" placeholder="${esc(String((e.ch.tts || {}).tempo ?? 1))}" title="${esc($t('tts.tempo.tip'))}">
      </div>
      <label class="mlab">${esc($t(engine === 'gemini' ? 'tts.lineGemini' : 'tts.lineVv'))}</label>
      <textarea class="ttsText" data-k="text" rows="3">${esc(c.text || '')}</textarea>
      <label class="mlab">${$t('tts.label')}</label><input class="wide" data-k="label" type="text" value="${esc(c.label || '')}">
      ${engine === 'gemini' ? `<details open><summary class="empty">${$t('tts.gemSettings')}</summary><div class="form">
        <label>${$t('tts.model')}</label><select data-g="model"><option value="">${charSet(e.gemini.model)}</option>${GEMINI_MODELS.map(m => `<option ${(c.gemini || {}).model === m ? 'selected' : ''}>${m}</option>`).join('')}</select>
        <label>${$t('tts.voice')}</label><select data-g="voice"><option value="">${charSet(((e.ch.tts || {}).gemini || {}).voice || 'Kore')}</option>${GEMINI_VOICES.map(v => `<option ${(c.gemini || {}).voice === v ? 'selected' : ''}>${v}</option>`).join('')}</select>
      </div><label class="mlab">${$t('tts.style')}</label><textarea data-g="style" rows="3" placeholder="${esc(((e.ch.tts || {}).gemini || {}).style || '')}">${esc((c.gemini || {}).style || '')}</textarea>
        <label class="mlab">${$t('tts.delivery')}</label><textarea data-k="delivery_style" rows="2" placeholder="${esc($t('tts.delivery.ph'))}">${esc(c.delivery_style || '')}</textarea></details>`
      : `<details open><summary class="empty">${$t('tts.vvSettings')}</summary><div class="form">
        <label>${$t('tts.speaker')}</label><select data-v="speaker"><option value="">${charSet(String(((e.ch.tts || {}).voicevox || {}).speaker ?? $t('tts.unset')))}</option>${spk.map(s => `<option value="${s.id}" ${String((c.voicevox || {}).speaker) === String(s.id) ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
        ${VV_KEYS.map(([k, nm, mn, mx, st]) => `<label>${nm}</label><input data-v="${k}" type="number" min="${mn}" max="${mx}" step="${st}" value="${(c.voicevox || {})[k] ?? ''}" placeholder="${((e.ch.tts || {}).voicevox || {})[k] ?? ''}">`).join('')}
        ${spk.length ? '' : `<label></label><span class="empty">${$t('tts.vvDown')}</span>`}
      </div></details>`}
      <div class="btns"><button id="ttsGen" class="primary">${$t((c.takes || []).length ? 'tts.regen' : 'tts.gen')}</button><span id="ttsMsg" class="tdim"></span></div>
      <h2>${$t('tts.takes')}</h2><div class="takes">${takes}</div>
      <h2>${$t('tts.sound')}</h2><div class="form">${timeFields(c, true)}${soundFields(c)}</div>`;
    bindHead(el, c); bindNums(el, c, ['start', 'dur', 'in', 'gain', 'fade_in', 'fade_out']); bindCurves(el, c);
    el.querySelector('[data-k="character"]').onchange = ev => change(() => { c.character = ev.target.value; });
    el.querySelector('[data-k="engine"]').onchange = ev => change(() => { c.engine = ev.target.value; });
    // 生成のあとの速さ（空＝キャラ設定の tts.tempo か 1。次に生成したテイクから効く。editor/ops.js の ttsTempo）
    el.querySelector('[data-k="tempo"]').onchange = ev => change(() => { const v = parseFloat(ev.target.value); if (ev.target.value === '' || !isFinite(v)) delete c.tempo; else c.tempo = Math.max(0.5, Math.min(2, v)); }, { keepForm: true });
    el.querySelector('[data-k="text"]').onchange = ev => change(() => { c.text = ev.target.value; }, { keepForm: true });
    const ds = el.querySelector('[data-k="delivery_style"]');
    if (ds) ds.onchange = ev => change(() => { const v = ev.target.value.trim(); if (v) c.delivery_style = v; else delete c.delivery_style; }, { keepForm: true });
    el.querySelector('[data-k="label"]').onchange = ev => change(() => { if (ev.target.value) c.label = ev.target.value; else delete c.label; }, { keepForm: true });
    el.querySelectorAll('[data-g]').forEach(inp => inp.onchange = () => change(() => { c.gemini = c.gemini || {}; if (inp.value === '') delete c.gemini[inp.dataset.g]; else c.gemini[inp.dataset.g] = inp.value; }, { keepForm: true }));
    el.querySelectorAll('[data-v]').forEach(inp => inp.onchange = () => change(() => {
      c.voicevox = c.voicevox || {}; const k = inp.dataset.v;
      if (inp.value === '') delete c.voicevox[k]; else c.voicevox[k] = k === 'speaker' ? +inp.value : parseFloat(inp.value);
    }, { keepForm: true }));
    el.querySelectorAll('.take').forEach(row => {
      const k = (c.takes || []).find(x => x.id === row.dataset.take);
      row.querySelector('input').onchange = () => change(() => { OPS.ttsSelectTake(c, k.id); });
      row.querySelector('.play').onclick = () => preview(rootUrl(k.src));
    });
    $('ttsGen').onclick = () => generate(c);
    if (B.cur === c.id) { $('ttsGen').disabled = true; $('ttsMsg').textContent = $t('tts.batchBusy'); }
  }
  const engineOf = c => OPS.ttsEngine(c, chars());
  // 1本生成して新しいテイクにする（選んでいるテイクもそれにする）。失敗は投げる。消されたクリップなら null
  // 頼みの中身（このシーンの演技 delivery_style は Gemini のスタイルのあとに「 / 」でつなぐ）とテイクの入れ方は editor/ops.js（API の tts と同じ）
  async function genOne(c) {
    const request = OPS.ttsRequest(c, chars());
    const r = await api('/api/tts', { method: 'POST', body: JSON.stringify({ clip: c.id, request, taken: (c.takes || []).map(k => k.id) }), headers: { 'Content-Type': 'application/json' } });
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || r.status);
    const f = findClip(c.id); if (!f) return null; const cc = f.clip;
    change(() => { OPS.ttsAddTake(cc, j, request, new Date().toISOString()); }, { keepForm: S.sel !== c.id });
    return j;
  }
  async function generate(c) {
    const engine = engineOf(c);
    const btn = $('ttsGen'), msg = $('ttsMsg'); btn.disabled = true; msg.textContent = $t(engine === 'gemini' ? 'tts.genGemini' : 'tts.genVv');
    try {
      const j = await genOne(c); if (!j) return;
      const ov = OPS.ttsOverlaps(S.tl).get(c.id), o = ov && findClip(ov);  // 声の長さで伸びて、同じトラックの次のセリフに重なった
      setStatus(o ? $LJ($L('tts.generated', { id: j.id, sec: (+j.dur).toFixed(2) }), $L('tts.overlapTail', { other: clipLabel(o.clip) })) : $L('tts.generated', { id: j.id, sec: (+j.dur).toFixed(2) }), o ? 'warn' : 'ok');
      preview(rootUrl(j.src));
    } catch (err) { if ($('ttsMsg')) $('ttsMsg').textContent = $t('tts.failShort', { err: err.message }); setStatus($L('tts.failed', { err: err.message }), 'bad'); }
    finally { if ($('ttsGen')) $('ttsGen').disabled = false; }
  }

  // ---- 字幕（ASS）：settings.subtitle.renderer = "ass" の作品（作者の紙芝居の作品で足した）。libass で焼く（pyengine/mittler/ass.py）。
  // 見た目は作品全体の settings.subtitle.ass（ASS の Style）＋ クリップの style（size・color・stroke・stroke_color・stroke_alpha・shadow・shadow_color・shadow_alpha・margin_v・align・valign）。
  const ASS_DEFAULT = { fontname: 'Noto Serif JP', fontsize: 56, primary: '&H00EAF3F5', outline_colour: '&H90302018', back_colour: '&HC0302018', outline: 2, shadow: 2,
    alignment: 2, margin_v: 65, fontsdir: 'assets/fonts' };
  const assMode = () => ((S.tl.settings || {}).subtitle || {}).renderer === 'ass';
  function assColour(h) {  // &HAABBGGRR → [[r, g, b], 濃さ 0〜1]
    const m = /^&H([0-9A-F]{2})?([0-9A-F]{2})([0-9A-F]{2})([0-9A-F]{2})$/i.exec(String(h || '').trim()); if (!m) return [[255, 255, 255], 1];
    const a = parseInt(m[1] || '00', 16); return [[parseInt(m[4], 16), parseInt(m[3], 16), parseInt(m[2], 16)], +(1 - a / 255).toFixed(3)];
  }
  function assBase() {  // 作品全体の見た目を、字幕の欄の形（Pillow の字幕と同じキー）にしたもの
    const b = Object.assign({}, ASS_DEFAULT, ((S.tl.settings || {}).subtitle || {}).ass || {});
    const [pc] = assColour(b.primary), [oc, oa] = assColour(b.outline_colour), [bc, ba] = assColour(b.back_colour), al = +b.alignment || 2;
    return { b, size: b.fontsize, color: pc, stroke: b.outline, stroke_color: oc, stroke_alpha: oa, shadow: b.shadow, shadow_color: bc, shadow_alpha: ba,
      margin_v: b.margin_v, align: ['left', 'center', 'right'][(al - 1) % 3], valign: al >= 7 ? 'top' : al >= 4 ? 'middle' : 'bottom' };
  }
  function inspectSubAss(c, f) {
    const el = $('sel'); el.className = ''; const base = assBase(), st = Object.assign({}, base, nonEmpty(c.style));
    const own = k => c.style && c.style[k] !== undefined;
    const lab = (k, n) => `<label${own(k) ? ' class="own"' : ''} title="${esc($t(own(k) ? 'sub.own' : 'sub.inherit'))}">${$t('sub.' + n)}${own(k) ? ' ●' : ''}</label>`;
    const T = k => $t('sub.' + k);
    el.innerHTML = head(c, f, $t('sub.titleAss')) + `
      <label class="mlab">${T('text')}</label><textarea data-k="text" rows="3">${esc(c.text || '')}</textarea>
      <div class="form">${timeFields(c, false)}</div>
      <div class="empty">${T('assNote')}</div>
      <h3>${T('look')} <span class="tdim">${T('lookNote')}</span></h3>
      <div class="form">
        ${lab('size', 'size')}<input data-s="size" type="number" step="1" min="8" value="${st.size}">
        ${lab('color', 'color')}<input data-s="color" type="color" value="${hex(st.color)}">
        ${lab('stroke', 'stroke')}<input data-s="stroke" type="number" step="0.5" min="0" value="${st.stroke}">
        ${lab('stroke_color', 'strokeColor')}<input data-s="stroke_color" type="color" value="${hex(st.stroke_color)}">
        ${lab('stroke_alpha', 'strokeAlpha')}<input data-s="stroke_alpha" type="number" step="0.05" min="0" max="1" value="${st.stroke_alpha}">
        ${lab('shadow', 'shadow')}<input data-s="shadow" type="number" step="0.5" min="0" value="${st.shadow}">
        ${lab('shadow_color', 'shadowColor')}<input data-s="shadow_color" type="color" value="${hex(st.shadow_color)}">
        ${lab('shadow_alpha', 'shadowAlpha')}<input data-s="shadow_alpha" type="number" step="0.05" min="0" max="1" value="${st.shadow_alpha}">
        ${lab('margin_v', 'marginV')}<input data-s="margin_v" type="number" step="1" min="0" value="${st.margin_v}">
        ${lab('align', 'halign')}<select data-s="align">${['left', 'center', 'right'].map(v => `<option value="${v}" ${v === st.align ? 'selected' : ''}>${T('a.' + v)}</option>`).join('')}</select>
        ${lab('valign', 'valign')}<select data-s="valign">${['bottom', 'middle', 'top'].map(v => `<option value="${v}" ${v === st.valign ? 'selected' : ''}>${T('a.' + v)}</option>`).join('')}</select>
      </div>
      <div class="btns"><button id="subAll">${T('resetToProject')}</button></div>
      <details><summary class="empty">${T('projectLook')}</summary><div class="form">
        <label>${T('fontname')}</label><input data-a="fontname" type="text" value="${esc(base.b.fontname)}" title="${esc($t('sub.fontname.tip', { dir: base.b.fontsdir }))}">
        <label>${T('size')}</label><input data-a="fontsize" type="number" step="1" min="8" value="${base.b.fontsize}">
        <label>${T('stroke')}</label><input data-a="outline" type="number" step="0.5" min="0" value="${base.b.outline}">
        <label>${T('shadow')}</label><input data-a="shadow" type="number" step="0.5" min="0" value="${base.b.shadow}">
        <label>${T('marginV')}</label><input data-a="margin_v" type="number" step="1" min="0" value="${base.b.margin_v}">
      </div><div class="empty">${esc($t('sub.fontsdir', { dir: base.b.fontsdir }))}</div></details>`;
    bindHead(el, c); bindNums(el, c, ['start', 'dur']);
    el.querySelector('[data-k="text"]').onchange = ev => change(() => { c.text = ev.target.value; }, { keepForm: true });
    el.querySelectorAll('[data-s]').forEach(inp => inp.onchange = () => change(() => {
      const k = inp.dataset.s; c.style = c.style || {};
      const v = inp.type === 'color' ? unhex(inp.value) : inp.type === 'number' ? (inp.value === '' ? null : parseFloat(inp.value)) : inp.value;
      if (v === null || JSON.stringify(v) === JSON.stringify(base[k])) delete c.style[k]; else c.style[k] = v;  // 作品の既定と同じなら持たない
      // 色と濃さは ASS では1つの値（&HAABBGGRR）なので、片方を変えたらもう片方も今の値で持つ（ass.py は無いほうを既定の色・濃さで埋めるため）
      for (const [x, y] of [['stroke_color', 'stroke_alpha'], ['shadow_color', 'shadow_alpha']]) {
        if (k !== x && k !== y) continue;
        const cx = c.style[x] !== undefined ? c.style[x] : base[x], cy = c.style[y] !== undefined ? c.style[y] : base[y];
        if (JSON.stringify(cx) === JSON.stringify(base[x]) && cy === base[y]) { delete c.style[x]; delete c.style[y]; } else { c.style[x] = cx; c.style[y] = cy; }
      }
      if (!Object.keys(c.style).length) delete c.style;
    }));
    el.querySelectorAll('[data-a]').forEach(inp => inp.onchange = () => change(() => {
      S.tl.settings = S.tl.settings || {}; const sub = S.tl.settings.subtitle = S.tl.settings.subtitle || {}; sub.ass = sub.ass || {};
      sub.ass[inp.dataset.a] = inp.type === 'number' ? parseFloat(inp.value) : inp.value;
    }, { keepForm: true }));
    $('subAll').onclick = () => change(() => { delete c.style; });
  }

  function inspectSub(c, f) {
    if (assMode()) return inspectSubAss(c, f);
    const el = $('sel'); el.className = ''; const st = Object.assign({}, SUB_DEFAULT, nonEmpty(S.tl.settings && S.tl.settings.subtitle), nonEmpty(c.style));
    const fonts = ((S.assets || {}).fonts || []).map(x => x.path);
    const T = k => $t('sub.' + k);
    el.innerHTML = head(c, f, T('title')) + `
      <label class="mlab">${T('text')}</label><textarea data-k="text" rows="3">${esc(c.text || '')}</textarea>
      <div class="form">${timeFields(c, false)}
        <label>${T('font')}</label><select data-s="font">${[...new Set([st.font, ...fonts])].map(p => `<option ${p === st.font ? 'selected' : ''}>${esc(p)}</option>`).join('')}</select>
        <label>${T('size')}</label><input data-s="size" type="number" step="1" value="${st.size}">
        <label>${T('color')}</label><input data-s="color" type="color" value="${hex(st.color)}">
        <label>${T('stroke')}</label><input data-s="stroke" type="number" step="1" min="0" value="${st.stroke}">
        <label>${T('strokeColor')}</label><input data-s="stroke_color" type="color" value="${hex(st.stroke_color)}">
        <label>${T('strokeAlpha')}</label><input data-s="stroke_alpha" type="number" step="0.05" min="0" max="1" value="${st.stroke_alpha}">
        <label>${T('align')}</label><select data-s="align">${['center', 'left', 'right'].map(a => `<option ${a === st.align ? 'selected' : ''}>${a}</option>`).join('')}</select>
        <label>x</label><input data-s="x" type="number" step="1" value="${st.x ?? ''}" placeholder="${esc(T('xPh'))}">
        <label>${T('y')}</label><input data-s="y" type="number" step="1" value="${st.y ?? ''}" placeholder="${esc($t('sub.yPh', { px: st.margin_v }))}">
      </div>
      <div class="btns"><button id="subPos">${T('resetPos')}</button><button id="subAll">${T('resetAll')}</button></div>`;
    bindHead(el, c); bindNums(el, c, ['start', 'dur']);
    el.querySelector('[data-k="text"]').onchange = ev => change(() => { c.text = ev.target.value; }, { keepForm: true });
    el.querySelectorAll('[data-s]').forEach(inp => inp.onchange = () => change(() => {
      c.style = c.style || {}; const k = inp.dataset.s;
      if (inp.type === 'color') c.style[k] = unhex(inp.value);
      else if (inp.type === 'number') { if (inp.value === '') delete c.style[k]; else c.style[k] = parseFloat(inp.value); }
      else c.style[k] = inp.value;
    }, { keepForm: true }));
    $('subPos').onclick = () => change(() => { if (c.style) { delete c.style.x; delete c.style.y; } });
    $('subAll').onclick = () => change(() => { delete c.style; });
  }

  function inspectAudio(c, f) {
    const el = $('sel'); el.className = '';
    el.innerHTML = head(c, f, $t(f.track.role === 'bgm' ? 'au.titleBgm' : 'au.title')) + `
      <div class="metaRow"><b>${$t('au.src')}</b>${esc(c.src || '')}</div>
      <div class="btns"><button id="auPlay">${$t('au.play')}</button></div>
      <div class="form">${timeFields(c, true)}${soundFields(c)}
        ${c.norm ? `<label>${$t('au.norm')}</label><span class="tdim">${$t('au.normV', { v: c.norm })}</span>` : ''}
        ${c.ramp ? `<label>${$t('au.ramp')}</label><span class="tdim">${c.ramp[0]} → ${c.ramp[1]} dB</span>` : ''}
      </div>`;
    bindHead(el, c); bindNums(el, c, ['start', 'dur', 'in', 'gain', 'fade_in', 'fade_out']); bindCurves(el, c);
    $('auPlay').onclick = () => preview(rootUrl(c.src), c.in || 0);
  }

  function inspectImage(c, f) {
    const el = $('sel'); el.className = '';
    el.innerHTML = head(c, f, $t('img.title')) + `<img class="ithumb" src="${rootUrl(c.src)}">
      <div class="metaRow"><b>${$t('au.src')}</b>${esc(c.src)}</div>
      <div class="form">${c.cut == null ? timeFields(c, false) : ''}
        <label>${$t('img.pop')}</label><input data-k="pop" type="checkbox" ${c.pop ? 'checked' : ''}></div>
      <label class="mlab">${$t('img.camera')}</label><textarea data-k="camera" rows="3">${esc(c.camera ? JSON.stringify(c.camera) : '')}</textarea>
      ${clipGradeHTML(c)}`;
    bindHead(el, c); bindNums(el, c, ['start', 'dur']); bindClipGrade(el, c);  // 🎨 クリップの色（editor.js）
    el.querySelector('[data-k="pop"]').onchange = ev => change(() => { if (ev.target.checked) c.pop = true; else delete c.pop; });
    el.querySelector('[data-k="camera"]').onchange = ev => {
      const v = ev.target.value.trim(); let cam = null;
      if (v) { try { cam = JSON.parse(v); } catch (e) { ev.target.classList.add('bad'); return; } }
      ev.target.classList.remove('bad'); change(() => { if (cam) c.camera = cam; else delete c.camera; }, { keepForm: true });
    };
  }

  // ---------- セリフをまとめて生成（時間の順に1本ずつ。もう一度押すと今の1本で止める） ----------
  //   pending：文が入っていて、テイクが1つもないもの
  //   all：文が入っているもの全部を作り直す（新しいテイクを足して選ぶ。前のテイクは残る）。押しまちがえないように、もう一度押して始める
  const B = { running: false, mode: null, stop: false, cur: null, done: 0, total: 0, fails: [], armed: 0 };
  const allLines = () => OPS.ttsLines(S.tl, 'all');
  const pendingLines = () => OPS.ttsLines(S.tl, 'pending');
  const linesOf = mode => mode === 'all' ? allLines() : pendingLines();
  const BTN_TIP = { pending: $L('batch.tip.pending'), subs: $L('batch.tip.subs'), all: $L('batch.tip.all') };
  // ---------- 💬 セリフから字幕を作る：タイムラインの表示（label）ではなく、しゃべる文（text）から。演技タグ <…> を外し、無音だけの行（……。）は作らない ----------
  // 時間はセリフのクリップと同じ。もう一度押すと、前に作った字幕（from_tts）の時間を合わせ直す（手で直した文はそのまま）。セリフを選んでいれば、選んだものだけ
  // 計算（演技タグを外す・無音だけの行は作らない・前に作った字幕の時間を合わせ直す）は editor/ops.js の subLines・subsFromLines（API の subs-from-lines と同じ）
  const subLines = () => OPS.subLines(S.tl, (typeof selIds === 'function' ? selIds() : []).map(findClip).filter(Boolean).map(f => f.clip));
  function subsFromLines() {
    const lines = subLines(); if (!lines.length) { setStatus($L('batch.noSubLines')); return; }
    let r = null;
    change(() => { r = OPS.subsFromLines(S.tl, lines, opsEnv()); });  // トラックの名前は、作るときの画面の言葉で
    const { made, upd, kept } = r;
    setStatus(kept ? $L('batch.subsDoneKept', { made, upd, kept }) : $L('batch.subsDone', { made, upd }));
  }
  function batchLabel(mode = 'pending') {
    if (mode === 'subs') return $t('batch.subs', { n: subLines().length });
    if (B.running && B.mode === mode) return $t('batch.stop', { done: B.done, total: B.total });
    const n = linesOf(mode).length;
    if (mode === 'all') return $t(B.armed > Date.now() ? 'batch.allArmed' : 'batch.all', { n });
    return $t('batch.pending', { n });
  }
  const batchOff = mode => mode === 'subs' ? !subLines().length : B.running ? B.mode !== mode : !linesOf(mode).length;
  const batchButtons = () => ['pending', 'all', 'subs'].map(m => `<button class="ttsAllBtn${m === 'pending' ? ' primary' : m === 'subs' ? ' subs' : ' regen'}${B.running && B.mode === m ? ' running' : ''}${m === 'all' && B.armed > Date.now() ? ' armed' : ''}"
    data-mode="${m}" title="${esc(BTN_TIP[m])}" ${batchOff(m) ? 'disabled' : ''}>${esc(batchLabel(m))}</button>`).join('');
  function batchRefresh() {
    document.querySelectorAll('.ttsAllBtn').forEach(b => { const m = b.dataset.mode; b.textContent = batchLabel(m); b.disabled = batchOff(m);
      b.classList.toggle('running', B.running && B.mode === m); b.classList.toggle('armed', m === 'all' && B.armed > Date.now()); });
    if (window.MITTLER_ASSETS) window.MITTLER_ASSETS.onEdit();
  }
  async function generateAll(mode = 'pending') {
    if (mode === 'subs') { subsFromLines(); return; }
    if (B.running) { if (B.mode === mode) { B.stop = true; setStatus($L('batch.stopping'), 'busy'); } return; }
    const list = linesOf(mode); if (!list.length) { setStatus($L(mode === 'all' ? 'batch.noLines' : 'batch.noPending')); return; }
    if (mode === 'all' && !(B.armed > Date.now())) {
      B.armed = Date.now() + 5000; batchRefresh(); setStatus($L('batch.armed', { n: list.length }), 'warn');
      setTimeout(() => { if (!B.running) batchRefresh(); }, 5100); return;
    }
    const word = $L(mode === 'all' ? 'batch.wordRegen' : 'batch.wordGen');
    Object.assign(B, { running: true, mode, stop: false, done: 0, total: list.length, fails: [], armed: 0 }); batchRefresh();
    let streak = 0, streakStop = false;
    for (const c0 of list) {
      if (B.stop) break;
      const f = findClip(c0.id); const c = f && f.clip;
      if (!c || !String(c.text || '').trim() || (mode === 'pending' && (c.takes || []).length)) { B.done++; continue; }  // 途中で消した・手で生成した・文を消した
      B.cur = c.id; setStatus($L('batch.progress', { word, i: B.done + 1, total: B.total, who: (charOf(c.character) || {}).name || c.character || '?', text: c.label || c.text })); batchRefresh();
      try { await genOne(c); streak = 0; }
      catch (err) { B.fails.push(`${c.label || c.text}${$t('sep.who')}${err.message}`); streak++; }
      B.done++; B.cur = null; batchRefresh();
      if (streak >= 3) { B.stop = true; streakStop = true; }
    }
    if (streakStop) B.fails.push($t('batch.streak'));
    const stopped = B.stop && B.done < B.total, ok = B.done - B.fails.length + (streakStop ? 1 : 0);
    B.running = false; B.mode = null; B.stop = false; B.cur = null; batchRefresh();
    setStatus($LJ($L('batch.done', { word, n: ok }), B.fails.length ? $L('batch.doneFails', { n: B.fails.length, first: B.fails[0].slice(0, 160) }) : '', stopped ? $L('batch.doneStopped') : ''), B.fails.length ? 'bad' : 'ok');
    if (S.sel) { const f = findClip(S.sel); if (f && f.clip.type === 'tts') window.MITTLER_INSPECT(f.clip, f); }
  }
  window.MITTLER_TTS_ALL = { run: generateAll, pending: pendingLines, all: allLines, label: batchLabel, buttons: batchButtons, refresh: batchRefresh, state: B };

  // ---------- トラック ----------
  window.MITTLER_INSPECT_TRACK = tr => {
    const el = $('sel'); el.className = '';
    const isTts = tr.kind === 'tts', isAu = tr.kind === 'audio';
    const T = (k, v) => $t('trk.' + k, v);
    el.innerHTML = `<div class="metaRow"><b>${$t('sel.track')}</b>${esc(KIND[tr.kind] || tr.kind)}</div>
      <div class="form"><label>${T('name')}</label><input data-t="name" type="text" value="${esc(tr.name || '')}">
        ${isTts ? `<label>${T('char')}</label><select data-t="character">${chars().map(ch => `<option value="${esc(ch.id)}" ${ch.id === tr.character ? 'selected' : ''}>${esc(ch.name)}</option>`).join('')}</select>` : ''}
        ${isAu ? `<label>${T('role')}</label><select data-t="role">${['sfx', 'bgm', 'reference'].map(v => `<option value="${v}" ${tr.role === v ? 'selected' : ''}>${T('role.' + v)}</option>`).join('')}</select>` : ''}
        ${(isTts || isAu) ? `<label>${T('mute')}</label><input data-t="muted" type="checkbox" ${tr.muted ? 'checked' : ''}>` : ''}
        ${(isTts || isAu) ? `<label>${T('gain')}</label><input data-t="gain" type="number" step="0.5" value="${tr.gain || 0}">` : ''}
      </div>
      ${isTts ? `<div class="btns ttsAllBtns">${batchButtons()}</div>` : ''}
      ${tr.kind === 'plan' && window.MITTLER_PLAN ? `<div class="btns"><button id="trAdoptAll" class="primary" title="${esc(T('adoptAll.tip'))}"
        ${MITTLER_PLAN.pendingAdopt(tr).length ? '' : 'disabled'}>${T('adoptAll', { n: MITTLER_PLAN.pendingAdopt(tr).length })}</button>
        <button id="trAdoptLatest" title="${esc(T('adoptLatest.tip'))}"
        ${MITTLER_PLAN.pendingAdopt(tr, true).length ? '' : 'disabled'}>${$t('ce.btn.latestN', { n: MITTLER_PLAN.pendingAdopt(tr, true).length })}</button></div>` : ''}
      <div class="btns">${(isTts || tr.kind === 'subtitle') ? `<button id="trAdd">${T('add')}</button>` : ''}
        <button id="trUp">${T('up')}</button><button id="trDown">${T('down')}</button>
        <button id="trDel" class="${delArmed(tr) ? 'armed' : ''}" title="${esc(T('del.tip'))}">${delLabel(tr)}</button></div>
      <div class="empty">${T('count', { n: (tr.clips || []).length })}</div>`;
    el.querySelectorAll('[data-t]').forEach(inp => inp.onchange = () => change(() => {
      const k = inp.dataset.t;
      if (inp.type === 'checkbox') { if (inp.checked) tr[k] = true; else delete tr[k]; }
      else if (inp.type === 'number') tr[k] = parseFloat(inp.value) || 0; else tr[k] = inp.value;
    }));
    if ($('trAdd')) $('trAdd').onclick = () => window.MITTLER_LANE_DBL(tr, snapFrame(S.t));
    if ($('trAdoptAll')) $('trAdoptAll').onclick = () => { window.MITTLER_PLAN.adoptAll(tr); window.MITTLER_INSPECT_TRACK(tr); };
    if ($('trAdoptLatest')) $('trAdoptLatest').onclick = () => { window.MITTLER_PLAN.adoptAll(tr, true); window.MITTLER_INSPECT_TRACK(tr); };
    el.querySelectorAll('.ttsAllBtn').forEach(b => { b.onclick = () => generateAll(b.dataset.mode); });
    $('trUp').onclick = () => change(() => { const i = S.tl.tracks.indexOf(tr); if (i > 0) { S.tl.tracks.splice(i, 1); S.tl.tracks.splice(i - 1, 0, tr); } });
    $('trDown').onclick = () => change(() => { const i = S.tl.tracks.indexOf(tr); if (i < S.tl.tracks.length - 1) { S.tl.tracks.splice(i, 1); S.tl.tracks.splice(i + 1, 0, tr); } });
    $('trDel').onclick = () => deleteTrack(tr);
    return true;
  };
  window.MITTLER_LANE_DBL = (tr, t) => {
    if (!tr) return;
    let c = null;
    if (tr.kind === 'tts') {
      const ch = charOf(tr.character) || chars()[0] || {};
      c = { id: uid('tts'), type: 'tts', start: t, dur: 2, character: ch.id || '', engine: (ch.tts || {}).default_engine || 'gemini', text: '',
        gemini: {}, voicevox: {}, takes: [], gain: 0, in: 0, fade_in: 0, fade_out: 0 };
    } else if (tr.kind === 'subtitle') c = { id: uid('sub'), type: 'subtitle', start: t, dur: 2, text: $t('sub.newText') };  // 新しい字幕の初めの文字（作品の中身。作るときの画面の言葉で）
    if (!c) return;
    change(() => { tr.clips.push(c); tr.clips.sort((a, b) => a.start - b.start); });
    select(c.id); if (S.pane !== 'sel') showPane('sel');
  };
  // トラックを足す：字幕はいちばん上、TTS は映像の下（TTS があればその下）、音はいちばん下（参考の音より上）
  // トラックを消す：クリップがあれば、押しまちがえないように 2 回押し（5 秒以内）。クリップごと消える（Ctrl+Z で戻る）
  const DEL = { id: null, until: 0 };
  const delArmed = tr => DEL.id === tr.id && DEL.until > Date.now();
  const delLabel = tr => { const n = (tr.clips || []).length; return $t(delArmed(tr) ? 'trk.delArmed' : n ? 'trk.delN' : 'trk.del', { n }); };
  function deleteTrack(tr) {
    const n = (tr.clips || []).length;
    if (n && !delArmed(tr)) {
      DEL.id = tr.id; DEL.until = Date.now() + 5000; window.MITTLER_INSPECT_TRACK(tr);
      setStatus($L('trk.delConfirm', { name: tr.name || tr.id, n }), 'warn');
      setTimeout(() => { if (S.selTrack === tr.id && !S.sel) window.MITTLER_INSPECT_TRACK(tr); }, 5100); return;
    }
    DEL.id = null; const ids = new Set((tr.clips || []).map(c => c.id));
    change(() => {
      const i = S.tl.tracks.indexOf(tr); if (i >= 0) S.tl.tracks.splice(i, 1);
      S.selTrack = null; if (ids.has(S.sel)) S.sel = null; if (S.multi) for (const id of ids) S.multi.delete(id);
    });
    setStatus($L(n ? 'trk.deletedN' : 'trk.deleted', { name: tr.name || tr.id, n }), 'ok');
  }
  window.MITTLER_DEL_TRACK = deleteTrack;
  function addTrack(kind, opts = {}) {
    const n = S.tl.tracks.filter(t => t.kind === kind).length + 1;
    // 名前（作品の中身）は、作るときの画面の言葉で（辞書の track.new.<種類>）
    const tr = Object.assign({ id: uid('t_' + kind), name: opts.name || $t('track.new.' + (kind === 'audio' ? (opts.role === 'bgm' ? 'bgm' : 'sfx') : kind)) + ' ' + n, kind, clips: [] }, opts.extra || {});
    if (kind === 'tts') tr.character = (chars()[0] || {}).id;
    const T = S.tl.tracks; let i;
    if (kind === 'subtitle') i = 0;
    else if (kind === 'plan') { const v = T.map(t => t.kind).lastIndexOf('video'); i = v >= 0 ? v + 1 : T.length; }  // 映像のすぐ下（奥）
    else if (kind === 'video') {  // いちばん上の映像トラックのさらに上（手前）。映像が無ければ動画化予定の上、それも無ければ音（セリフ・音）の上
      const v = T.findIndex(t => t.kind === 'video' || t.kind === 'media'), pl = T.findIndex(t => t.kind === 'plan'), au = T.findIndex(t => t.kind === 'tts' || t.kind === 'audio');
      i = v >= 0 ? v : pl >= 0 ? pl : au >= 0 ? au : T.length;
    }
    else if (kind === 'tts') { const last = T.map(t => t.kind).lastIndexOf('tts'); const v = T.map(t => t.kind).lastIndexOf('video'); i = (last >= 0 ? last : v) + 1; }
    else { const ref = T.findIndex(t => t.role === 'reference'); i = ref >= 0 ? ref : T.length; }
    change(() => T.splice(Math.max(0, i), 0, tr));
    S.selTrack = tr.id; showSel(); return tr;
  }
  window.MITTLER_ADD_TRACK = addTrack;
  function addTrackButtons() {
    const rh = document.querySelector('#heads .rulerHead'); if (!rh || rh.dataset.done) return; rh.dataset.done = '1';
    // ＋ とトラックの種類のアイコン（トラックの頭と同じ。editor.js の TRACK_ICON）。ツールチップは辞書の addtr.<種類>
    const paint = () => {
      rh.innerHTML = `<div class="addtr">${[['tts', 'speech'], ['subtitle', 'captions'], ['video', 'film'], ['sfx', 'volume-2'], ['bgm', 'music'], ['plan', 'clapperboard']]
        .map(([k, ic]) => `<button data-add="${k}" title="${esc($t('addtr.' + k))}" aria-label="${esc($t('addtr.' + k))}">＋${MITTLER_ICON(ic)}</button>`).join('')}</div>`;
    };
    paint(); MITTLER_I18N.onChange(paint);
    rh.addEventListener('click', e => {
      const b = e.target.closest('[data-add]'); if (!b || !S.tl) return; const k = b.dataset.add;
      if (k === 'sfx' || k === 'bgm') addTrack('audio', { role: k, extra: { role: k } }); else addTrack(k);
    });
  }

  // ---------- 再生中の音（Web Audio）：書き出し版の動画は消音にして、今のタイムラインの TTS・音を鳴らす ----------
  const AU = { ctx: null, bufs: new Map(), nodes: [], token: 0 };
  function audioClips() {
    const out = [];
    for (const tr of (S.tl && S.tl.tracks) || []) {
      if ((tr.kind !== 'tts' && tr.kind !== 'audio') || tr.muted || tr.hidden) continue;
      for (const c of tr.clips || []) {
        if (c.disabled) continue;
        const src = c.type === 'tts' ? (takeOf(c) || {}).src : c.src; if (!src) continue;
        out.push({ c, url: rootUrl(src), db: (c.gain || 0) + (c.norm || 0) + (tr.gain || 0) });
      }
    }
    return out;
  }
  function buf(url) {
    if (!AU.bufs.has(url)) AU.bufs.set(url, fetch(url).then(r => r.arrayBuffer()).then(b => ctx().decodeAudioData(b)).catch(() => null));
    return AU.bufs.get(url);
  }
  function ctx() { if (!AU.ctx) AU.ctx = new (window.AudioContext || window.webkitAudioContext)(); return AU.ctx; }
  window.MITTLER_AUDIO = {
    has: () => !!S.tl && audioClips().length > 0,
    preload: () => { for (const a of audioClips()) buf(a.url); },
    start(t0) {
      const ac = ctx(); ac.resume(); const tok = ++AU.token; const c0 = ac.currentTime;
      for (const a of audioClips()) {
        const c = a.c; if (c.start + c.dur <= t0) continue;
        buf(a.url).then(b => {
          if (!b || tok !== AU.token) return;
          const now = ac.currentTime, ph = t0 + (now - c0);  // 読み込みに時間がかかっても、今の位置に合わせて鳴らす
          if (c.start + c.dur <= ph) return;
          const off = Math.max(0, ph - c.start), when = now + Math.max(0, c.start - ph) + 0.02, left = c.dur - off;
          const s = ac.createBufferSource(); s.buffer = b; const g = ac.createGain(); s.connect(g).connect(ac.destination);
          const lin = db => Math.pow(10, db / 20);
          if (c.ramp) { const r0 = lin(c.ramp[0] + (c.norm || 0)), r1 = lin(c.ramp[1] + (c.norm || 0)), k = off / c.dur; g.gain.setValueAtTime(r0 + (r1 - r0) * k, when); g.gain.linearRampToValueAtTime(r1, when + left); }
          else {
            const base = lin(a.db), fi = c.fade_in || 0, fo = c.fade_out || 0;
            g.gain.setValueAtTime(fi > off ? base * off / fi : base, when);
            if (fi > off) g.gain.linearRampToValueAtTime(base, when + (fi - off));
            if (fo > 0 && left > 0) { const st = Math.max(when, when + left - fo); g.gain.setValueAtTime(base, st); g.gain.linearRampToValueAtTime(0, when + left); }
          }
          s.start(when, (c.in || 0) + off, Math.max(0.001, left)); AU.nodes.push(s);
        });
      }
    },
    stop() { AU.token++; for (const s of AU.nodes) try { s.stop(); } catch (e) { } AU.nodes = []; },
  };

  window.MITTLER_MEDIA_INIT = () => { addTrackButtons(); if (window.MITTLER_AUDIO.has()) window.MITTLER_AUDIO.preload(); };
})();
