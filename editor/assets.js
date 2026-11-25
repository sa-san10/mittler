// Mittler 編集画面：左のアセット窓（セリフ・動画・画像・音声・音楽・TTS 済み・エフェクト・キャラ）。editor.js・media.js のあとに読む。
// 一覧はサーバーの /api/assets（素材の根の assets/）。クリックで見る・聞く、「置く」で今の時刻にタイムラインへ。キャラは characters.json を直す。
// 画面の言葉は辞書の as.*（editor/i18n/*.json）。言葉を切り替えたら、タブと一覧を作り直す
'use strict';
(() => {
  const TABS = ['lines', 'videos', 'images', 'audio', 'bgm', 'voice', 'effects', 'chars'];  // 名前は辞書の as.tab.<タブ>
  let tab = (() => { try { return localStorage.getItem('cc.assetTab') || 'lines'; } catch (e) { return 'lines'; } })();
  let player = null;
  const fmtS = s => (s == null ? '' : $t('as.sec', { s: (+s).toFixed(1) }));
  const uid = p => p + '_' + Math.random().toString(36).slice(2, 8);
  async function load() {
    try { S.assets = await (await api('/api/assets', { cache: 'no-store' })).json(); } catch (e) { S.assets = {}; }
    S.fxLibLoaded = false;  // エフェクトのタブを開いたときに、部品の置き場の一覧を読み直す
    render();
  }
  // 部品の置き場（effects_lib/common）のエフェクトで、作品にまだ無いもの（描画サーバーが META を読む。/api/effects_lib）
  async function loadLib() {
    S.fxLibLoaded = true;
    try { const r = await api('/api/effects_lib', { cache: 'no-store' }); S.fxLib = r.ok ? await r.json() : {}; } catch (e) { S.fxLib = {}; }
    if (tab === 'effects') render();
  }
  function play(url, btn) {
    if (player) { player.pause(); if (player._btn) player._btn.innerHTML = MITTLER_ICON('play'); if (player._btn === btn) { player = null; return; } }
    player = new Audio(url); player._btn = btn; btn.innerHTML = MITTLER_ICON('square'); player.onended = () => { btn.innerHTML = MITTLER_ICON('play'); player = null; }; player.play().catch(() => { });
  }
  function trackFor(kind, role) {
    let tr = S.tl.tracks.find(t => t.kind === kind && (!role || t.role === role));
    if (!tr) tr = window.MITTLER_ADD_TRACK(kind, role ? { role, extra: { role } } : {});
    return tr;
  }
  function place(clip, tr) { change(() => { tr.clips.push(clip); tr.clips.sort((a, b) => a.start - b.start); }); select(clip.id); }

  function buildTabs() {
    $('assetTabs').innerHTML = TABS.map(k => `<button data-tab="${k}">${esc($t('as.tab.' + k))}</button>`).join('')
      + `<button data-tab="_reload" title="${esc($t('as.reload'))}">${MITTLER_ICON('refresh-cw')}</button><button data-tab="_close" class="aclose" title="${esc($t('as.close'))}">${MITTLER_ICON('chevrons-left')}</button>`;
    $('assetTabs').dataset.built = '1';
  }
  function render() {
    const body = $('assetBody'); if (!body || !S.tl) return;
    // タブのボタンは最初に1回だけ作る（作り直すと、入力欄から抜けた保存で描き直したときに、押している途中のボタンが消えてクリックが届かない）。言葉を切り替えたときは作り直す
    if (!$('assetTabs').dataset.built) buildTabs();
    $('assetTabs').querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
    const A = S.assets || {};
    const t = snapFrame(S.t);
    if (tab === 'lines') {
      const rows = S.tl.tracks.filter(tr => tr.kind === 'tts').flatMap(tr => tr.clips.map(c => ({ c, tr }))).sort((a, b) => a.c.start - b.c.start);
      const TA = window.MITTLER_TTS_ALL, cur = TA && TA.state.cur;
      body.innerHTML = (rows.length && TA ? `<div class="linesHead ttsAllBtns">${TA.buttons()}</div>` : '') + (rows.length ? rows.map(({ c }) => {
        const ch = charOf(c.character); const tk = (c.takes || []).find(k => k.id === c.activeTake);
        return `<div class="arow line${c.id === S.sel ? ' on' : ''}" data-clip="${esc(c.id)}"><span class="at">${fmt(c.start)}</span>
          <span class="who" ${ch && ch.color ? ` style="border-color:${esc(ch.color)}"` : ''}>${esc(ch ? ch.name : c.character || '?')}</span>
          <span class="txt">${esc(c.label || c.text || $t('as.emptyLine'))}</span><span class="st">${tk ? tk.id : c.id === cur ? $t('as.generating') : $t('as.notGenerated')}</span></div>`;
      }).join('') : `<div class="empty">${$t('as.noTts')}</div>`);
    } else if (tab === 'images') {
      body.innerHTML = '<div class="agrid">' + (A.images || []).map(it => `<div class="acell" data-path="${esc(it.path)}" title="${esc(it.path)}"><img loading="lazy" src="${rootUrl(it.path)}"><span>${esc(it.name)}</span></div>`).join('') + '</div>';
    } else if (tab === 'videos') {
      body.innerHTML = (A.videos || []).map(it => `<div class="arow" data-path="${esc(it.path)}" data-dur="${it.dur || 0}"><span class="txt">${esc(it.name)}</span><span class="st">${fmtS(it.dur)}</span></div>`).join('') || `<div class="empty">${$t('as.noVideos')}</div>`;
    } else if (tab === 'audio' || tab === 'bgm' || tab === 'voice') {
      const list = A[tab] || [];
      const used = new Map(); for (const tr of S.tl.tracks) for (const c of tr.clips || []) for (const k of c.takes || []) used.set(k.src, c);
      body.innerHTML = list.map(it => { const c = used.get(it.path); return `<div class="arow" data-path="${esc(it.path)}" data-dur="${it.dur || 0}"><button class="aplay">${MITTLER_ICON('play')}</button>
        <span class="txt" title="${esc(it.path)}">${esc(it.name)}${c ? `<br><small>${esc((charOf(c.character) || {}).name || '')}${esc($t('sep.who'))}${esc(c.label || c.text || '')}</small>` : ''}</span><span class="st">${fmtS(it.dur)}</span></div>`; }).join('')
        || `<div class="empty">${$t(tab === 'bgm' ? 'as.noBgm' : tab === 'voice' ? 'as.noVoice' : 'as.noAudio')}</div>`;
    } else if (tab === 'effects') {
      const names = Object.keys(S.fx || {}).sort();
      // 3D の印（GPU の 3D・Blender で描くエフェクト：META の gl3d・blender）
      const badge = m => m.gl3d || m.blender ? ` <span class="badge3d" title="${esc($t('as.badge3d.tip'))}">${esc($t('as.badge3d'))}</span>` : '';
      body.innerHTML = names.length ? names.map(n => { const m = (S.fx[n] || {}).meta || {}; return `<div class="arow fx" data-fx="${esc(n)}"><span class="txt"><b>${esc(fxLabel(m, n))}</b>${badge(m)} <small>${esc(n)}</small></span></div>`; }).join('')
        : `<div class="empty">${$t('as.waitFx')}</div>`;
      // 部品の置き場（effects_lib/library.json のフォルダ）にあって作品にまだ無いもの（3D のエフェクトなど）。「作品に入れる」で作品の effects/ に写す。
      // フォルダ（pack）ごとにまとめ、common のほかは見出し as.libPack.<pack>（偽マリアのエフェクト集など）を付ける。並びは描画サーバーが返した順
      const lib = Object.keys(S.fxLib || {});
      const row = n => { const m = (S.fxLib[n] || {}).meta || {};
        return `<div class="arow fxlib" data-fxlib="${esc(n)}"><span class="txt"><b>${esc(fxLabel(m, n))}</b>${badge(m)} <small>${esc(n)}</small></span></div>`; };
      const packs = [...new Set(lib.map(n => (S.fxLib[n] || {}).pack || 'common'))];
      if (lib.length) body.innerHTML += `<div class="libHead">${esc($t('as.libHead'))}</div>` + packs.map(p => {
        const ns = lib.filter(n => ((S.fxLib[n] || {}).pack || 'common') === p).sort();
        return (p === 'common' ? '' : `<div class="libPack">${esc($t('as.libPack.' + p))}</div>`) + ns.map(row).join('');
      }).join('');
      if (!S.fxLibLoaded) loadLib();
    } else if (tab === 'chars') {
      const cs = (S.chars || {}).characters || [];
      body.innerHTML = cs.map(c => `<div class="arow char" data-char="${esc(c.id)}">${c.image ? `<img class="cimg" src="${rootUrl(c.image)}">` : '<span class="cimg"></span>'}
        <span class="txt"><b class="cname"${c.color ? ` style="--cc:${esc(c.color)}"` : ''}>${esc(c.name)}</b><br><small>${esc(c.id)}${$t('sep.list')}${esc((c.tts || {}).default_engine || 'gemini')}</small></span></div>`).join('')
        + `<div class="btns"><button id="charAdd">${$t('as.charAdd')}</button><button id="charPreset">${$t('as.charPreset')}</button></div>`;
    }
    $('assetPreview').innerHTML = '';
  }

  // ---------- 選んだアセットの見る・置く ----------
  function showPreview(html) { $('assetPreview').innerHTML = html; }
  $('assetTabs').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.tab === '_reload') { load(); return; }
    if (b.dataset.tab === '_close') { setOpen(false); return; }
    tab = b.dataset.tab; try { localStorage.setItem('cc.assetTab', tab); } catch (err) { } render();
  });
  $('assetBody').addEventListener('click', e => {
    const t = snapFrame(S.t);
    const ab = e.target.closest('.ttsAllBtn'); if (ab) { window.MITTLER_TTS_ALL.run(ab.dataset.mode); return; }
    const ln = e.target.closest('.line'); if (ln) { const f = findClip(ln.dataset.clip); if (f) { seek(f.clip.start + 0.5 / fps()); select(f.clip.id); showPane('sel'); render(); } return; }
    const pb = e.target.closest('.aplay'); if (pb) { play(rootUrl(pb.closest('.arow').dataset.path), pb); return; }
    const cell = e.target.closest('.acell');
    if (cell) {
      const p = cell.dataset.path;
      const pl = window.MITTLER_PLAN && window.MITTLER_PLAN.selected();  // 動画化予定のクリップを選んでいたら、その開始・終了の絵にもできる
      showPreview(`<img src="${rootUrl(p)}"><div class="tdim">${esc(p)}</div><div class="btns"><button id="apImg">${$t('as.placeImg')}</button><button id="apSpr">${$t('as.placeSprite')}</button>
        ${pl ? `<button id="apPlanA">${$t('as.planStart')}</button><button id="apPlanB">${$t('as.planEnd')}</button>` : ''}</div>`);
      if (pl) { $('apPlanA').onclick = () => window.MITTLER_PLAN.setFrame(pl, 'start_frame', p); $('apPlanB').onclick = () => window.MITTLER_PLAN.setFrame(pl, 'end_frame', p); }
      $('apImg').onclick = () => place({ id: uid('img'), type: 'image', src: p, start: t, dur: 3, label: p.split('/').pop() }, trackFor('video'));
      $('apSpr').onclick = () => {
        let tr = S.tl.tracks.find(x => x.kind === 'effect' && (x.clips || []).some(c => c.effect === 'sprite'));
        if (!tr) { tr = { id: uid('t_sprite'), name: $t('track.sprite'), kind: 'effect', clips: [] }; change(() => S.tl.tracks.unshift(tr)); }  // トラックの名前は、作るときの画面の言葉で
        place({ id: uid('sprite'), type: 'effect', effect: 'sprite', start: t, dur: 2, label: p.split('/').pop(),
          params: { img: p, x: S.tl.width / 2, y: S.tl.height / 2, t0: t, t1: t + 2, anim: 'pop', scale: 1 } }, tr);
      };
      return;
    }
    const row = e.target.closest('.arow');
    if (row && row.dataset.path) {
      const p = row.dataset.path, d = +row.dataset.dur || 2;
      if (tab === 'videos') {
        showPreview(`<video src="${rootUrl(p)}" controls muted playsinline></video><div class="tdim">${esc(p)}${$t('sep.list')}${fmtS(d)}</div><div class="btns"><button id="apVid">${$t('as.placeVideo')}</button></div>`);
        $('apVid').onclick = () => { const c = { id: uid('vid'), type: 'video', src: [p], start: t, dur: +d.toFixed(3), in: 0, speed: 1, label: p.split('/').pop() };
          if (window.MITTLER_CUT) MITTLER_CUT.placeVideo(c, trackFor('video')); else place(c, trackFor('video')); };  // 音があれば、音も取り出してリンクして置く
      } else if (tab === 'audio' || tab === 'bgm') {
        const role = tab === 'bgm' ? 'bgm' : 'sfx';
        showPreview(`<div class="tdim">${esc(p)}${$t('sep.list')}${fmtS(d)}</div><div class="btns"><button id="apAu">${$t(role === 'bgm' ? 'as.placeBgm' : 'as.placeSfx')}</button></div>`);
        $('apAu').onclick = () => place({ id: uid(role), type: 'audio', src: p, start: t, dur: +d.toFixed(3), in: 0, gain: role === 'bgm' ? -6 : -12, fade_in: 0, fade_out: role === 'bgm' ? 1 : 0, label: p.split('/').pop() }, trackFor('audio', role));
      } else if (tab === 'voice') {
        const c = (S.tl.tracks.flatMap(x => x.clips || [])).find(c => (c.takes || []).some(k => k.src === p));
        if (c) { select(c.id); showPane('sel'); }
      }
      return;
    }
    const fx = e.target.closest('.fx');
    if (fx) {
      const n = fx.dataset.fx, info = S.fx[n] || {}, m = info.meta || {}, w = m.window || {};
      showPreview(`<div class="doc">${esc(fxDoc(info))}</div><div class="btns"><button id="apCode">${$t('sel.openCode')}</button>${w.per_cut || w.fixed ? '' : `<button id="apFx">${$t('as.placeFx')}</button>`}</div>`);
      $('apCode').onclick = () => openCode(n);
      if ($('apFx')) $('apFx').onclick = () => {
        const params = {}, dv = m.defaults || {};  // META の defaults（任意。3D のエフェクトなど）があれば、その値で置く
        for (const [k, sp] of Object.entries(m.params || {})) params[k] = k in dv ? JSON.parse(JSON.stringify(dv[k])) : sp.choices ? sp.choices[0] : sp.type === 'bool' ? false : sp.type === 'color' ? [255, 255, 255] : (sp.min != null ? sp.min : 1);
        const d = +m.dur > 0 ? +m.dur : 2;  // META の dur（任意）：置くときの長さ
        if (w.start) params[w.start] = t + (w.lead || 0); if (w.end) params[w.end] = t + d; if (w.dur) params[w.dur] = d;
        let tr = S.tl.tracks.find(x => x.kind === 'effect' && x.effect === n);
        if (!tr) { tr = { id: uid('t_' + n), name: fxLabel(m, n), kind: 'effect', effect: n, clips: [] }; change(() => S.tl.tracks.unshift(tr)); }
        place({ id: uid(n), type: 'effect', effect: n, start: t, dur: d, params }, tr);
      };
      return;
    }
    const fl = e.target.closest('.fxlib');
    if (fl) {  // 部品の置き場のエフェクト：説明と「作品に入れる」
      const n = fl.dataset.fxlib, info = (S.fxLib || {})[n] || {};
      showPreview(`<div class="doc">${esc(info.error || fxDoc(info))}</div><div class="btns"><button id="apLib" class="primary" title="${esc($t('as.libAdd.tip'))}">${$t('as.libAdd')}</button></div>`);
      $('apLib').onclick = async () => {
        let r; try { r = await (await api('/api/effects/add', { method: 'POST', body: JSON.stringify({ name: n }), headers: { 'Content-Type': 'application/json' } })).json(); } catch (err) { r = { ok: false, error: String(err) }; }
        if (!r.ok) { setStatus($L('as.libAddFailed', { err: r.error }), 'bad'); return; }
        setStatus($L('as.libAdded', { files: r.copied.join($t('sep.list')) }), 'ok');
        S.fxLibLoaded = false; delete (S.fxLib || {})[n];
        if (typeof loadEffects === 'function') await loadEffects();  // 作品のエフェクトの一覧を読み直す（入れたものが上の一覧に出る）
        render();
      };
      return;
    }
    const ch = e.target.closest('.char'); if (ch) { editChar(ch.dataset.char); return; }
    if (e.target.id === 'charPreset') { showCharPresets(); return; }
    if (e.target.id === 'charAdd') {
      const cs = S.chars.characters; const id = 'chara' + (cs.length + 1);
      cs.push({ id, name: $t('as.newChar'), image: '', profile: '', color: '#cccccc', tts: { default_engine: 'gemini', gemini: { model: 'gemini-3.8-flash-tts', voice: 'Kore', style: '' }, voicevox: { speaker: null, speedScale: 1, pitchScale: 0, intonationScale: 1, volumeScale: 1 } } });
      saveChars().then(() => { render(); editChar(id); });
    }
  });

  // ---------- キャラのプリセット（このリポジトリの隣の presets/characters。作品に写す）----------
  async function showCharPresets() {
    let d; try { d = await (await fetch('/api/presets/characters', { cache: 'no-store' })).json(); } catch (e) { d = { characters: [], error: String(e) }; }
    if (!d.characters.length) { showPreview(`<div class="empty">${esc(d.error || $t('as.noPresets'))}</div>`); return; }
    showPreview(`<div class="tdim">${esc($t('as.presetsHead', { dir: d.dir }))}</div><div class="pgrid">${d.characters.map(c => `
      <div class="pcell${c.in_project ? ' have' : ''}" data-preset="${esc(c.id)}" title="${esc(c.profile)}${c.notes.length ? '\n\n' + esc(c.notes.join('\n')) : ''}">
        ${c.thumb ? `<img loading="lazy" src="/api/presets/thumb?id=${encodeURIComponent(c.id)}">` : `<div class="pnoimg">${$t('as.noImage')}</div>`}<b class="cname"${c.color ? ` style="--cc:${esc(c.color)}"` : ''}>${esc(c.name)}</b>
        <span>${esc(c.id)}${c.voice ? '・' + MITTLER_ICON('mic') + esc(c.voice) : ''}${c.variants.length ? esc($t('as.variantsN', { n: c.variants.length })) : ''}${c.in_project ? esc($t('as.inProject')) : ''}</span></div>`).join('')}</div>`);
    $('assetPreview').querySelectorAll('.pcell').forEach(el => el.onclick = async () => {
      const id = el.dataset.preset, have = el.classList.contains('have');
      if (have && !confirm($t('as.presetOverwrite'))) return;
      const r = await (await api('/api/presets/characters/add', { method: 'POST', body: JSON.stringify({ id, overwrite: have }), headers: { 'Content-Type': 'application/json' } })).json();
      if (r.ok) setStatus($L('as.presetAdded', { name: r.name })); else setStatus($L('as.presetFailed', { err: r.error }));
      if (r.ok) { await loadChars(); load(); showCharPresets(); }
    });
  }

  // ---------- キャラ（characters.json）----------
  // 立ち絵の差分の1行（名前＋画像）
  function variantRow(k, p, imgs) {
    return `<div class="variant"><input class="vk" placeholder="smile" value="${esc(k)}"><select class="vp"><option value="">${$t('as.imageOpt')}</option>${imgs.map(x => `<option ${x === p ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></div>`;
  }
  async function saveChars() {
    const r = await api('/api/file?path=characters.json', { method: 'PUT', body: JSON.stringify(S.chars, null, 1) + '\n' });
    if (r.ok) setStatus($L('as.charSaved'), 'ok'); else setStatus($L('as.charSaveFailed'), 'bad'); buildTimeline();
  }
  async function editChar(id) {
    const c = ((S.chars || {}).characters || []).find(x => x.id === id); if (!c) return;
    c.tts = c.tts || {}; const g = c.tts.gemini = c.tts.gemini || {}; const v = c.tts.voicevox = c.tts.voicevox || {};
    let spk = []; try { const d = await (await fetch('/api/voicevox/speakers')).json(); spk = d.flatMap(s => s.styles.map(st => ({ id: st.id, name: $t('vv.speakerStyle', { name: s.name, style: st.name }) }))); } catch (e) { }
    const imgs = ((S.assets || {}).images || []).map(x => x.path);
    const T = (k, vv) => $t('as.c.' + k, vv);
    showPreview(`<div class="cform">
      ${c.image ? `<img class="cbig" src="${rootUrl(c.image)}">` : ''}
      <div class="form"><label>ID</label><span class="tdim">${esc(c.id)}</span>
        <label>${T('name')}</label><input data-c="name" value="${esc(c.name || '')}">
        <label>${T('color')}</label><input data-c="color" type="color" value="${esc(c.color || '#cccccc')}">
        <label>${T('image')}</label><select data-c="image"><option value="">${T('none')}</option>${imgs.map(p => `<option ${p === c.image ? 'selected' : ''}>${esc(p)}</option>`).join('')}</select>
        <label>${T('engine')}</label><select data-t="default_engine"><option value="gemini" ${c.tts.default_engine !== 'voicevox' ? 'selected' : ''}>Gemini TTS</option><option value="voicevox" ${c.tts.default_engine === 'voicevox' ? 'selected' : ''}>VOICEVOX</option></select>
        <label title="${esc($t('tts.tempo.tip'))}">${$t('tts.tempo')}</label><input data-tempo type="number" min="0.5" max="2" step="0.05" value="${c.tts.tempo ?? ''}" placeholder="1" title="${esc($t('tts.tempo.tip'))}">
      </div>
      <label class="mlab">${T('profile')}</label><textarea data-c="profile" rows="4">${esc(c.profile || '')}</textarea>
      <label class="mlab">${esc(T('look', { id: c.id }))}</label><textarea data-c="look" rows="3">${esc(c.look || '')}</textarea>
      <label class="mlab">${esc(T('variants', { id: c.id }))}</label>
      <div class="variants">${Object.entries(c.images || {}).filter(([k]) => k !== 'default').map(([k, p]) => variantRow(k, p, imgs)).join('')}</div>
      <div class="btns"><button id="charVarAdd">${T('variantAdd')}</button></div>
      <h2>Gemini TTS</h2><div class="form">
        <label>${$t('tts.model')}</label><input data-g="model" value="${esc(g.model || '')}" placeholder="gemini-3.8-flash-tts">
        <label>${$t('tts.voice')}</label><input data-g="voice" value="${esc(g.voice || '')}" placeholder="Kore">
      </div><label class="mlab">${T('style')}</label><textarea data-g="style" rows="3">${esc(g.style || '')}</textarea>
      <h2>VOICEVOX</h2><div class="form">
        <label>${$t('tts.speaker')}</label><select data-v="speaker"><option value="">${$t('tts.unset')}</option>${spk.map(s => `<option value="${s.id}" ${String(v.speaker) === String(s.id) ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
        ${[['speedScale', 'vv.speed'], ['pitchScale', 'vv.pitch'], ['intonationScale', 'vv.inton'], ['volumeScale', 'vv.volume']].map(([k, n]) => `<label>${$t(n)}</label><input data-v="${k}" type="number" step="0.01" value="${v[k] ?? ''}">`).join('')}
      </div>
      <div class="btns"><button id="charSave" class="primary">${$t('code.save')}</button></div></div>`);
    $('charVarAdd').onclick = () => $('assetPreview').querySelector('.variants').insertAdjacentHTML('beforeend', variantRow('', '', imgs));
    $('charSave').onclick = () => {
      const q = sel => [...$('assetPreview').querySelectorAll(sel)];
      for (const el of q('[data-c]')) c[el.dataset.c] = el.value;
      if (!c.look) delete c.look;
      const vars = {};  // 差分：名前と画像の両方があるものだけ
      for (const row of q('.variant')) { const k = row.querySelector('.vk').value.trim(), p = row.querySelector('.vp').value; if (k && p && k !== 'default') vars[k] = p; }
      if (Object.keys(vars).length) c.images = vars; else delete c.images;
      for (const el of q('[data-t]')) c.tts[el.dataset.t] = el.value;
      for (const el of q('[data-tempo]')) { const v = parseFloat(el.value); if (el.value === '' || !isFinite(v)) delete c.tts.tempo; else c.tts.tempo = Math.max(0.5, Math.min(2, v)); }  // 生成のあとの速さ
      for (const el of q('[data-g]')) { if (el.value) g[el.dataset.g] = el.value; else delete g[el.dataset.g]; }
      for (const el of q('[data-v]')) { if (el.value === '') v[el.dataset.v] = el.dataset.v === 'speaker' ? null : undefined; else v[el.dataset.v] = el.dataset.v === 'speaker' ? +el.value : parseFloat(el.value); }
      saveChars().then(render);
    };
  }

  // 開け閉め（open が null なら覚えている状態で）。閉じたぶんプレビューが広がる
  function setOpen(open) {
    if (open === null) { try { open = localStorage.getItem('cc.assetsOpen') !== '0'; } catch (e) { open = true; } }
    else { try { localStorage.setItem('cc.assetsOpen', open ? '1' : '0'); } catch (e) { } }
    $('assets').hidden = !open;
    $('assetToggle').hidden = false; $('assetToggle').classList.toggle('on', !!open);
    fitScreen();
  }
  $('assetToggle').addEventListener('click', () => setOpen($('assets').hidden));
  window.MITTLER_ASSETS = { load, render, setOpen, onEdit: () => { if (tab === 'lines') render(); } };
  const prevChange = window.MITTLER_ON_CHANGE;
  window.MITTLER_ON_CHANGE = kinds => { if (prevChange) prevChange(kinds); if (kinds.includes('asset') || kinds.includes('characters') || kinds.includes('timeline')) load(); };
  // 言葉を切り替えたら、タブと一覧を作り直す（開いていた見る・置くの欄は閉じる）
  MITTLER_I18N.onChange(() => { if ($('assetTabs').dataset.built) buildTabs(); render(); });
})();
