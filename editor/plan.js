// Mittler 編集画面：動画化予定（🎬 kind "plan"）のクリップ。media.js・assets.js のあとに読む。形は docs/タイムライン形式.md の plan、H3 との受け渡しは docs/H3受け渡し契約.md。
// クリップ：{type:'plan', start, dur, label,
//   start_frame:{src, prompt, takes:[{id, src, engine, sent, created}], activeTake}, end_frame:{同じ},
//   video:{prompt, engine:'h3-fl2va'|'h3-ref2va', takes:[{id, src, dur, engine, sent, created}], activeTake, adopted}}
// いまは第1段階：置く・開始と終了の絵を選ぶ・プロンプトを書く・仮のプレビュー（スタート→エンドの絵）。生成（絵・動画）は次の段階。
// プロンプトの参照は CSS の @import 風（案A）：@import char(kurochan) as クロ; / image("assets/…") / frame(clip, end) / style(名前) / audio(…)（動画だけ）
// 画面の言葉は辞書の pl.*
'use strict';
(() => {
  const uid = p => p + '_' + Math.random().toString(36).slice(2, 8);
  // 動画化のエンジンの選択肢（画面の名前は辞書の pl.engine.<id>）。エンジン → アダプタの対応表は tools/engines.json（ここの id がそこにあることは tools/smoke_same.py が確かめる）
  const ENGINES = [['h3-fl2va', 'pl.engine.fl2va'], ['h3-ref2va', 'pl.engine.ref2va']];
  // 絵のエンジン（'' は既定＝PC の設定 mittler.image.engine → tools/engines.json の既定）。OpenAI のモデルの候補（ほかの名前も書ける）（2026-11-15）
  const IMAGE_ENGINES = [['codex', 'pl.engine.codex'], ['openai', 'pl.engine.openai'], ['nanobanana', 'pl.engine.nanobanana']];
  // Nano Banana（Gemini）のモデルの候補（ほかの名前も書ける）と解像度。既定は Nano Banana Pro・2K（2026-11-19。tools/gemini_image_jobs.py）
  const GEMINI_MODELS = ['gemini-3-pro-image', 'gemini-nano-banana-2.1', 'gemini-3.1-flash-image', 'gemini-3.1-flash-lite-image', 'gemini-2.5-flash-image'];
  const GEMINI_SIZES = ['1K', '2K', '4K'];
  const OPENAI_MODELS = ['gpt-image-2.5-sunburst', 'gpt-image-2.5-flare', 'gpt-image-2', 'gpt-image-1.5', 'gpt-image-1-mini'];
  const OPENAI_QUALITIES = ['auto', 'low', 'medium', 'high', 'xhigh', 'max'];
  const blankFrame = () => ({ src: null, prompt: '', takes: [], activeTake: null });
  const newPlan = t => ({ id: uid('plan'), type: 'plan', start: t, dur: 5, label: '', start_frame: blankFrame(), end_frame: blankFrame(),
    video: { prompt: '', engine: 'h3-fl2va', takes: [], activeTake: null } });
  const images = () => (((S.assets || {}).images) || []).map(x => x.path);
  // 絵・動画の URL に S.assetVer（外でファイルが変わった回数）を付ける：同じ名前で上書きされても、ブラウザが覚えている古い絵を出さない
  const mediaUrl = p => rootUrl(p) + (S.assetVer ? '?v=' + S.assetVer : '');
  const KIND_ICON = { char: 'user', image: 'image', frame: 'film', style: 'palette', audio: 'volume-2' };  // Lucide のアイコン
  const charOpts = () => ((S.chars && S.chars.characters) || []).map(ch => `<option value="${esc(ch.id)}">${esc($t('vv.speakerStyle', { name: ch.name, style: ch.id }))}</option>`).join('');
  // 参照のチップ：サーバーで @import を読んでもらい（server/plan_refs.js）、サムネと番号（参照画像N）、だめなものは赤で
  async function refreshChips(sec, c, which, text) {
    const box = sec.querySelector('.chips'); if (!box) return;
    let r;
    try { r = await (await api('/api/plan/resolve', { method: 'POST', body: JSON.stringify({ clip: c, which, text }), headers: { 'Content-Type': 'application/json' } })).json(); }
    catch (e) { box.innerHTML = ''; return; }
    if (!r.imports) { box.innerHTML = ''; return; }
    box.innerHTML = r.imports.map(im => `<span class="chip${im.error ? ' bad' : im.warn ? ' warn' : ''}" title="${esc(im.error || im.warn || im.text || im.src)}">${im.image ? `<img src="${rootUrl(im.image)}">` : ''}${MITTLER_ICON(KIND_ICON[im.kind] || 'triangle-alert')} ${esc(im.alias || im.src)}${im.n ? `<b>${im.n}</b>` : ''}</span>`).join('')
      + (which !== 'video' && r.refs.length > (r.max_refs || 5) ? `<span class="chip bad" title="${esc($t('pl.tooMany.tip', { n: r.max_refs || 5 }))}">${$t('pl.tooMany', { n: r.max_refs || 5 })}</span>` : '');
    sec.dataset.prompt = r.prompt || '';
  }
  // キャラの参照を1行足す（宣言の行のあと、本文の前）
  function addCharLine(ta, id) {
    const ch = ((S.chars && S.chars.characters) || []).find(x => x.id === id); if (!ch) return;
    const line = `@import char(${ch.id}) as ${ch.name};`;
    const lines = ta.value ? ta.value.split('\n') : [];
    let i = 0; while (i < lines.length && /^\s*@import\b/i.test(lines[i])) i++;
    lines.splice(i, 0, line); ta.value = lines.join('\n'); ta.dispatchEvent(new Event('change')); ta.dispatchEvent(new Event('input'));
  }

  function setFrame(c, which, path) {
    change(() => { c[which] = Object.assign(blankFrame(), c[which] || {}); c[which].src = path || null; });
  }
  window.MITTLER_PLAN = {
    selected() { const f = S.sel && findClip(S.sel); return f && f.clip.type === 'plan' ? f.clip : null; },
    setFrame,
  };

  // トラックの空いたところをダブルクリック：新しい予定クリップ
  const prevDbl = window.MITTLER_LANE_DBL;
  window.MITTLER_LANE_DBL = (tr, t) => {
    if (!tr || tr.kind !== 'plan') return prevDbl && prevDbl(tr, t);
    const c = newPlan(t);
    change(() => { tr.clips.push(c); tr.clips.sort((a, b) => a.start - b.start); });
    select(c.id); if (S.pane !== 'sel') showPane('sel');
  };

  // 右の欄
  const prevInspect = window.MITTLER_INSPECT;
  window.MITTLER_INSPECT = (c, f) => {
    if (c.type !== 'plan') return prevInspect ? prevInspect(c, f) : false;
    inspect(c, f); return true;
  };
  function frameSec(c, which, title) {
    const fr = c[which] || blankFrame();
    // 作品の既定の絵のエンジン（settings.image_engine）。欄が空ならそれ。ほかのエンジンも選べる（生成と直しでエンジンを使い分ける）
    const projEng = IMAGE_ENGINES.some(([k]) => k === ((S.tl && S.tl.settings) || {}).image_engine) ? S.tl.settings.image_engine : '';
    const eng = IMAGE_ENGINES.some(([k]) => k === fr.engine) ? fr.engine : projEng;  // この絵で使うエンジン（モデル・品質の欄を決める）
    const opts = [`<option value="">${$t('pl.none')}</option>`].concat(images().map(p => `<option ${p === fr.src ? 'selected' : ''}>${esc(p)}</option>`));
    if (fr.src && !images().includes(fr.src)) opts.push(`<option selected>${esc(fr.src)}</option>`);
    return `<div class="planSec" data-which="${which}"><h3>${title}</h3>
      ${fr.src ? `<img class="pthumb" src="${mediaUrl(fr.src)}">` : `<div class="empty">${$t('pl.noImage')}</div>`}
      <div class="form"><label>${$t('pl.image')}</label><select data-f="src">${opts.join('')}</select>
        <label>${$t('pl.imgEngine')}</label><select data-fe="engine"><option value="">${esc(projEng ? $t('pl.imgEngine.project', { e: projEng }) : $t('pl.imgEngine.default'))}</option>${IMAGE_ENGINES.map(([k, n]) => `<option value="${k}" ${k === fr.engine ? 'selected' : ''}>${esc($t(n))}</option>`).join('')}</select>
        ${eng === 'openai' ? `<label>${$t('pl.imgModel')}</label><input data-fe="model" type="text" list="oaModels_${which}" value="${esc(fr.model || '')}" placeholder="${esc($t('pl.imgModel.ph'))}"><datalist id="oaModels_${which}">${OPENAI_MODELS.map(m => `<option value="${m}">`).join('')}</datalist>
        <label>${$t('pl.imgQuality')}</label><select data-fe="quality"><option value="">${esc($t('pl.imgQuality.default'))}</option>${OPENAI_QUALITIES.map(q => `<option ${q === fr.quality ? 'selected' : ''}>${q}</option>`).join('')}</select>` : ''}
        ${eng === 'nanobanana' ? `<label>${$t('pl.imgModel')}</label><input data-fe="model" type="text" list="nbModels_${which}" value="${esc(fr.model || '')}" placeholder="${esc($t('pl.nbModel.ph'))}"><datalist id="nbModels_${which}">${GEMINI_MODELS.map(m => `<option value="${m}">`).join('')}</datalist>
        <label>${$t('pl.imgSize')}</label><select data-fe="quality"><option value="">${esc($t('pl.nbSize.default'))}</option>${GEMINI_SIZES.map(q => `<option ${q === fr.quality ? 'selected' : ''}>${q}</option>`).join('')}</select>` : ''}</div>
      <label class="mlab">${$t('pl.imgPrompt')}</label>
      <textarea data-f="prompt" spellcheck="false">${esc(fr.prompt || '')}</textarea>
      <div class="chips"></div>
      <div class="form"><label>${$t('pl.addRef')}</label><select class="addChar"><option value="">${$t('pl.addChar')}</option>${charOpts()}</select></div>
      <div class="btns"><button class="gen primary">${$t('pl.gen')}</button><button class="genStop" hidden>${$t('pl.stop')}</button><span class="jobst"></span></div>
      ${takesHTML(fr)}</div>`;
  }
  // テイク（生成した絵）：サムネを押すと、その絵を使う。プロンプトが届いた割合・参照が届いたかを添える
  function takesHTML(fr) {
    const ts = fr.takes || []; if (!ts.length) return '';
    return `<div class="ptakes">${ts.map(k => `<div class="ptake${k.src === fr.src ? ' on' : ''}" data-take="${esc(k.id)}" title="${esc((k.warnings || []).join('\n') || k.id)}">
      <img src="${mediaUrl(k.src)}"><span>${esc(k.id)}${(k.warnings || []).length ? ' ' + MITTLER_ICON('triangle-alert') : ''}</span></div>`).join('')}</div>`;
  }
  // 動画のテイク：押して選ぶ（採用する前でも、タイムラインのこの場所に選んだテイクが映る）・サムネか ▶ で、生成した動画そのものを真ん中のプレビューで再生（音つき。
  // 止める・位置・閉じるはサムネの側）・「採用」で 🎞️ 映像トラックの同じ時間に映像クリップを置く（採用済みならその映像クリップを差しかえる）
  function videoTakesHTML(v) {
    const ts = v.takes || []; if (!ts.length) return '';
    const ad = v.adopted && findClip(v.adopted);
    return `<div class="vtakes">${ts.map(k => `<div class="vtake${k.id === v.activeTake ? ' on' : ''}" data-take="${esc(k.id)}" title="${esc($t('pl.vtake.tip'))}">
      <input type="radio" ${k.id === v.activeTake ? 'checked' : ''}><img class="vthumb" src="/api/takethumb?src=${encodeURIComponent(k.src)}&token=${TOKEN}" alt="" title="${esc($t('pl.vplay.tip'))}">
      <button class="vplay" title="${esc($t('pl.vplay.tip'))}">${MITTLER_ICON('play')}</button>
      <span>${esc(k.id)}${$t('sep.list')}${esc($t('as.sec', { s: (+k.dur || 0).toFixed(2) }))}${k.draft ? `${$t('sep.list')}<b class="draftTag">${esc($t('pl.draftTag', { n: k.steps || '' }))}</b>` : ''}${k.seed != null ? `${$t('sep.list')}${esc($t('pl.seedTag', { n: k.seed }))}` : ''}${(k.warnings || []).length ? ' ' + MITTLER_ICON('triangle-alert') : ''}</span>
      <button class="adopt">${$t(ad && ad.clip.src && ad.clip.src[0] === k.src ? 'pl.adopted' : 'pl.adopt')}</button>
      <span class="vctl" hidden><input type="range" min="0" max="1000" value="0" title="${esc($t('pl.vseek.tip'))}"><span class="vtime"></span>
        <button class="vclose" title="${esc($t('pl.vclose.tip'))}">${MITTLER_ICON('x')}</button></span></div>`).join('')}</div>
      <div class="tdim">${$t('pl.vtakesNote')}</div>`;
  }
  // テイクの動画を真ん中のプレビューで見る（#takeView。タイムラインの絵の上に重ねる）。操作はテイクの行（▶／一時停止・位置・閉じる）。
  // タイムラインを再生する・時刻を動かすと閉じる（editor.js の setPlaying・seek）
  // VS Code の中では H.264・AAC の MP4 を再生できないので、サーバーに WebM を作ってもらってから流す（/api/takeproxy。2 回目からは作ったものを使う）
  const TV = { src: null, take: null, req: 0 };
  const tvEl = () => $('takeView');
  async function tvOpen(k) {
    const v = tvEl(), id = ++TV.req;
    if (S.playing) setPlaying(false);
    TV.take = k.id;
    if (TV.loading && TV.src === k.src) return;  // WebM を作っている最中（もう一度押しても待つだけ）
    if (TV.src !== k.src) {
      v.pause(); TV.src = k.src; TV.loading = true; v.hidden = false; showSrc($L('src.takeLoading', { id: k.id })); tvSync();
      let j = {};
      try { j = await (await api('/api/takeproxy', { method: 'POST', body: JSON.stringify({ src: k.src }), headers: { 'Content-Type': 'application/json' } })).json(); } catch (e) { j = { ok: false, error: e.message }; }
      if (id !== TV.req || TV.src !== k.src) return;  // 待っているあいだに、ほかのテイクを押した・閉じた
      TV.loading = false;
      if (!j.ok) { setStatus($L('pl.vplayFail', { err: j.error || '' }), 'warn'); tvClose(); return; }
      v.src = projUrl(j.proxy) + '?v=' + Date.now();
    }
    v.hidden = false; v.muted = false;
    v.play().catch(err => { if (err.name !== 'AbortError') setStatus($L('pl.vplayFail', { err: err.name }), 'warn'); });
    showSrc($L('src.take', { id: k.id }));
    tvSync();
  }
  function tvClose() {
    const v = tvEl(); if (!TV.src) return;
    TV.req++; TV.loading = false; v.pause(); v.removeAttribute('src'); v.load(); v.hidden = true; TV.src = TV.take = null;
    tvSync(); S.exactT = null; draw();  // 今のタイムラインの絵に戻す
  }
  const fmtS = s => isFinite(s) ? s.toFixed(1) : '0.0';
  function tvSync() {  // テイクの行の ▶／一時停止・位置の表示を、プレビューの動画に合わせる
    const v = tvEl();
    document.querySelectorAll('.vtake').forEach(row => {
      const on = !!TV.take && row.dataset.take === TV.take && row.closest('.planSec');
      const b = row.querySelector('.vplay'); if (b) b.innerHTML = MITTLER_ICON(on && !v.paused ? 'pause' : 'play');
      const ctl = row.querySelector('.vctl'); if (!ctl) return;
      ctl.hidden = !on; if (!on) return;
      const d = v.duration || 0, r = ctl.querySelector('input');
      if (!r.matches(':active')) r.value = d ? String(Math.round(v.currentTime / d * 1000)) : '0';
      ctl.querySelector('.vtime').textContent = `${fmtS(v.currentTime)} / ${fmtS(d)}`;
    });
  }
  ['play', 'pause', 'timeupdate', 'ended', 'loadedmetadata'].forEach(ev => tvEl().addEventListener(ev, tvSync));
  tvEl().addEventListener('error', () => { if (TV.src) setStatus($L('pl.vplayFail', { err: (tvEl().error || {}).code || '' }), 'warn'); });
  window.MITTLER_TAKEVIEW = { open: tvOpen, close: tvClose, isOpen: () => !!TV.src };
  // 選んでいるテイクを全部採用（動画化予定のトラックの欄のボタン）：採用していないもの・採用中と違うテイクを選んでいるものを、1回の取り消しでまとめて
  // latest＝それぞれ いちばん新しく作ったテイク（作った時刻 created、無ければ並びの最後）を選んでから置く（道具のバーの「最新の動画を全部採用」）
  // 置く・差しかえる・カットも足す（作品の settings.cuts_on_adopt）・置く長さ（テイクが予定より 2 コマ未満だけ短いときは予定の長さいっぱい）の計算は
  // editor/ops.js の adopt・pendingAdopt（API の adopt・adopt-all と同じ。同じ1回の取り消し）
  function adoptAll(tr, latest) {
    if (!S.tl.tracks.some(t => t.kind === 'video')) { setStatus($L('pl.noVideoTrackAdd')); return 0; }
    const todo = pendingAdopt(tr, latest); if (!todo.length) { setStatus($L(latest ? 'pl.nothingLatest' : 'pl.nothing')); return 0; }
    let r = null;
    change(() => { r = OPS.adopt(S.tl, todo, opsEnv()); });
    setStatus($L(latest ? 'pl.adoptedAllLatest' : 'pl.adoptedAll', { n: todo.length, cuts: cutNote(r.cuts) })); return todo.length;
  }
  const pendingAdopt = (tr, latest) => OPS.pendingAdopt(S.tl, tr, latest);
  Object.assign(window.MITTLER_PLAN, { adoptAll, pendingAdopt });
  function adopt(c, k) {
    if (!S.tl.tracks.some(t => t.kind === 'video')) { setStatus($L('pl.noVideoTrack')); return; }
    let r = null;
    change(() => { r = OPS.adopt(S.tl, [[c, k]], opsEnv()); });
    setStatus($L('pl.adoptedOne', { id: k.id, cuts: cutNote(r.cuts) }));
  }
  // あとで訳す（$L と同じく、言葉を切り替えたら訳し直す）
  function cutNote(rs) {
    const ok = rs.filter(r => r && r.label), ng = rs.filter(r => r && r.err);
    return { toString: () => (ok.length ? $t('pl.cutNote', { list: ok.map(r => r.label + (r.kind === 'exist' ? $t('pl.existing') : '')).join($t('sep.list')) }) : '')
      + (ng.length ? $t('pl.cutNoteFail', { n: ng.length, err: ng[0].err }) : '') };
  }
  // ---- ジョブ（生成）：サーバーに頼んで（/api/jobs）、できたら編集画面がテイクに入れる（タイムラインを書くのは編集画面だけ）----
  let jobs = [], pollTm = null;
  const reqErr = {};  // 頼めなかった理由（クリップ｜欄 → {msg, at}）。描き直してもジョブの状態より新しければ出す
  const JOB_ST = k => $t('pl.job.' + k);  // queued・running・waiting・done・failed・cancelled
  async function pollJobs() {
    clearTimeout(pollTm); pollTm = null;
    try { jobs = (await (await fetch('/api/jobs', { cache: 'no-store' })).json()).jobs || []; } catch (e) { }
    for (const j of jobs) if (j.state === 'done' && !j.applied) applyJob(j);
    showJobStates();
    if (jobs.some(j => ['queued', 'running', 'waiting'].includes(j.state))) pollTm = setTimeout(pollJobs, 2000);
  }
  function applyJob(j) {
    const f = findClip(j.clip); if (!f) return;
    const c = f.clip;
    if (j.kind === 'video') {
      if (!j.result) return;
      c.video = c.video || { prompt: '', engine: 'h3-fl2va', takes: [], activeTake: null };
      if (!(c.video.takes || []).some(k => k.src === j.result.src)) {
        const n = (c.video.takes || []).length + 1;
        change(() => {
          const sn = j.sent || {};
          const k = { id: 't' + n, src: j.result.src, dur: j.result.dur, engine: (j.video || {}).engine || 'h3-fl2va', created: j.finished || new Date().toISOString(),
            job: j.id, warnings: j.warnings || [], sent: j.sent };
          if (sn.draft) { k.draft = true; k.steps = sn.steps; } if (sn.seed != null) k.seed = sn.seed;
          c.video.takes = (c.video.takes || []).concat([k]); c.video.activeTake = k.id;
        });
        setStatus($L('pl.videoDone', { name: c.label || c.id }), 'ok');
      }
      afterSaved(() => api(`/api/jobs/${j.id}/applied`, { method: 'POST' })); j.applied = true; return;  // 印はタイムラインの保存のあと（editor.js の afterSaved）
    }
    const fr = c[j.which]; if (!fr || !j.result) return;
    if (!(fr.takes || []).some(k => k.src === j.result.src)) {
      const n = (fr.takes || []).length + 1;
      change(() => {
        c[j.which] = Object.assign(blankFrame(), c[j.which]);
        const k = { id: 't' + n, src: j.result.src, engine: (j.image || {}).engine || 'codex', created: j.finished || new Date().toISOString(), job: j.id,
          refs_ok: j.result.refs_ok, spec_coverage: j.result.spec_coverage, warnings: j.result.warnings || [], sent: j.sent };
        if (j.result.model) k.model = j.result.model;
        c[j.which].takes = (c[j.which].takes || []).concat([k]); c[j.which].src = k.src; c[j.which].activeTake = k.id;
      });
      setStatus($L(j.which === 'start_frame' ? 'pl.startDone' : 'pl.endDone', { name: c.label || c.id }), 'ok');
    }
    afterSaved(() => api(`/api/jobs/${j.id}/applied`, { method: 'POST' })); j.applied = true;
  }
  function showJobStates() {
    document.querySelectorAll('#sel .planSec').forEach(sec => {
      const c = window.MITTLER_PLAN.selected(); if (!c) return;
      const mine = jobs.filter(j => j.clip === c.id && j.which === sec.dataset.which).sort((a, b) => (a.created < b.created ? 1 : -1));
      const j = mine[0], st = sec.querySelector('.jobst'), stop = sec.querySelector('.genStop'), gens = [...sec.querySelectorAll('.gen')], gen = { set disabled(v) { gens.forEach(g => { g.disabled = v; }); } };
      const er = reqErr[c.id + '|' + sec.dataset.which];
      if (er && (!j || er.at > Date.parse(j.created))) { st.textContent = String(er.msg); st.className = 'jobst bad'; stop.hidden = true; gen.disabled = false; return; }
      const active = j && ['queued', 'running', 'waiting'].includes(j.state);
      st.textContent = j ? `${JOB_ST(j.state)}${j.state === 'failed' ? $t('sep.who') + String(j.error || '').slice(-200) : ''}${(j.warnings || []).length && j.state !== 'failed' ? $t('cm.paren', { x: j.warnings.join($t('sep.list')) }) : ''}` : '';
      st.className = 'jobst' + (j && j.state === 'failed' ? ' bad' : '');
      stop.hidden = !active; stop.dataset.job = active ? j.id : ''; gen.disabled = !!active;
    });
  }
  window.MITTLER_PLAN_JOBS = { poll: pollJobs, get jobs() { return jobs; } };
  setTimeout(pollJobs, 1500);  // 開いたとき：終わっていてまだ入れていないものを入れる
  // ジョブのファイルが変わった（Claude が mittler_api.py で頼んだものも）→ 見に行って、できたものをテイクに入れる。
  // 絵・動画のファイルが変わった（同じ名前の上書きも）→ 予定のクリップを選んでいれば、欄を描き直して新しい絵を出す（2026-10-31）
  const prevChange = window.MITTLER_ON_CHANGE;
  window.MITTLER_ON_CHANGE = kinds => {
    if (prevChange) prevChange(kinds);
    if (kinds.includes('jobs')) pollJobs();
    if (kinds.includes('media') && window.MITTLER_PLAN.selected()) showSelSafe();
  };
  function inspect(c, f) {
    const el = $('sel'); el.className = '';
    const v = c.video || {};
    el.innerHTML = `<div class="metaRow"><b>${$t('pl.title')}</b>${esc(f.track.name || f.track.id)}</div>
      <div class="btns"><button data-act="off">${$t(c.disabled ? 'sel.enable' : 'sel.disable')}</button><button data-act="del">${$t('sel.delete')}</button></div>
      <div class="form"><label>${$t('trk.name')}</label><input data-k="label" type="text" value="${esc(c.label || '')}" placeholder="${esc($t('pl.label.ph'))}">
        <label>${$t('f.start')}</label><input data-k="start" type="number" step="${1 / fps()}" value="${+c.start.toFixed(3)}">
        <label>${$t('f.dur')}</label><input data-k="dur" type="number" step="${1 / fps()}" min="${1 / fps()}" value="${+c.dur.toFixed(3)}"></div>
      ${frameSec(c, 'start_frame', $t('pl.startFrame'))}
      ${frameSec(c, 'end_frame', $t('pl.endFrame'))}
      <div class="planSec" data-which="video"><h3>${$t('pl.video')}</h3>
        <div class="form"><label>${$t('tts.engine')}</label><select data-v="engine">${ENGINES.map(([k, n]) => `<option value="${k}" ${k === (v.engine || 'h3-fl2va') ? 'selected' : ''}>${esc($t(n))}</option>`).join('')}</select></div>
        <label class="mlab">${esc($t('pl.videoPrompt'))}</label>
        <textarea data-v="prompt" spellcheck="false">${esc(v.prompt || '')}</textarea>
        <div class="chips"></div>
        <div class="form"><label>${$t('pl.addRef')}</label><select class="addChar"><option value="">${$t('pl.addChar')}</option>${charOpts()}</select></div>
        <div class="btns"><button class="gen primary">${$t('pl.genVideo')}</button><button class="gen draft" title="${esc($t('pl.draft.tip'))}">${$t('pl.draft')}</button><button class="genStop" hidden>${$t('pl.stop')}</button><span class="jobst"></span></div>
        <div class="form"><label>${$t('pl.seed')}</label><span class="seedRow"><span class="seedv">${v.seed != null ? esc(v.seed) : $t('pl.seedAuto')}</span><button class="reseed" title="${esc($t('pl.reseed.tip'))}">${$t('pl.reseed')}</button></span>
          <label>${$t('pl.draftSteps')}</label><input class="dsteps" type="number" min="4" max="40" step="1" value="${esc(v.draft_steps || 10)}"></div>
        <div class="tdim">${$t('pl.h3Note')}</div>
        ${videoTakesHTML(v)}</div>
      ${clipGradeHTML(c)}
      ${window.MITTLER_CUTMETA ? MITTLER_CUTMETA.clipHTML(c) : ''}
      <div class="tdim">${$t('pl.previewNote')}</div>`;
    bindClipGrade(el, c);  // 🎨 クリップの色（editor.js）
    if (window.MITTLER_CUTMETA) MITTLER_CUTMETA.bindClip(el, c);  // ✂ この範囲をカットにする・採用するときカットも（cutmeta.js）
    el.querySelector('[data-act="off"]').onclick = () => change(() => { if (c.disabled) delete c.disabled; else c.disabled = true; });
    el.querySelector('[data-act="del"]').onclick = () => deleteClip(c.id);
    el.querySelector('[data-k="label"]').onchange = ev => change(() => { c.label = ev.target.value; }, { keepForm: true });
    for (const k of ['start', 'dur']) {
      el.querySelector(`[data-k="${k}"]`).onchange = ev => { const x = parseFloat(ev.target.value); if (isFinite(x) && (k === 'start' ? x >= 0 : x > 0)) change(() => { if (k === 'start') setClipStart(c, x); else setClipDur(c, x); }, { keepForm: true }); };  // コマにそろえる（editor.js）
    }
    el.querySelectorAll('.planSec[data-which$="_frame"]').forEach(sec => {
      const which = sec.dataset.which;
      sec.querySelector('[data-f="src"]').onchange = ev => setFrame(c, which, ev.target.value);
      sec.querySelector('[data-f="prompt"]').onchange = ev => change(() => { c[which] = Object.assign(blankFrame(), c[which] || {}); c[which].prompt = ev.target.value; }, { keepForm: true });
      // 絵のエンジン・OpenAI のモデル・品質（空＝既定なので欄を消す）。エンジンを変えたらモデルの欄を出し入れするので描き直す
      sec.querySelectorAll('[data-fe]').forEach(inp => inp.onchange = () => change(() => {
        c[which] = Object.assign(blankFrame(), c[which] || {});
        const v = inp.value.trim(); if (v) c[which][inp.dataset.fe] = v; else delete c[which][inp.dataset.fe];
      }, inp.dataset.fe === 'engine' ? {} : { keepForm: true }));
    });
    // 参照のチップ：開いたとき・打っているあいだ（少し待って）に読み直す。「＋キャラ」で宣言の行を足す
    el.querySelectorAll('.planSec').forEach(sec => {
      const which = sec.dataset.which, ta = sec.querySelector('textarea'); let tm = null;
      refreshChips(sec, c, which, ta.value);
      ta.addEventListener('input', () => { clearTimeout(tm); tm = setTimeout(() => refreshChips(sec, c, which, ta.value), 400); });
      const sel = sec.querySelector('.addChar'); if (sel) sel.onchange = () => { addCharLine(ta, sel.value); sel.value = ''; };
    });
    el.querySelectorAll('.planSec[data-which$="_frame"]').forEach(sec => {
      const which = sec.dataset.which;
      sec.querySelector('.gen').onclick = async () => {
        const ta = sec.querySelector('textarea');
        if (ta.value !== ((c[which] || {}).prompt || '')) change(() => { c[which] = Object.assign(blankFrame(), c[which] || {}); c[which].prompt = ta.value; }, { keepForm: true });
        const r = await api('/api/jobs', { method: 'POST', body: JSON.stringify({ kind: 'image', clip: c, which }), headers: { 'Content-Type': 'application/json' } });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) { reqErr[c.id + '|' + which] = { msg: j.error || $L('pl.reqFail'), at: Date.now() }; showJobStates(); return; }
        delete reqErr[c.id + '|' + which];
        setStatus($L('pl.reqSent')); pollJobs();
      };
      sec.querySelector('.genStop').onclick = ev => { const id = ev.target.dataset.job; if (id) api(`/api/jobs/${id}/cancel`, { method: 'POST' }).then(pollJobs); };
      sec.querySelectorAll('.ptake').forEach(t => t.onclick = () => {
        if (!((c[which] || {}).takes || []).some(x => x.id === t.dataset.take)) return;
        change(() => { OPS.planFrameTake(c, which, t.dataset.take); });  // editor/ops.js（API の frame-take と同じ）
      });
    });
    const vsec = el.querySelector('.planSec[data-which="video"]');
    const vdef = () => { c.video = Object.assign({ prompt: '', engine: 'h3-fl2va', takes: [], activeTake: null }, c.video || {}); };
    const newSeed = () => 1 + Math.floor(Math.random() * 2147483646);
    vsec.querySelector('.reseed').onclick = () => { change(() => { vdef(); c.video.seed = newSeed(); }, { keepForm: true }); vsec.querySelector('.seedv').textContent = c.video.seed; setStatus($L('pl.seedSet', { n: c.video.seed })); };
    vsec.querySelector('.dsteps').onchange = ev => { const n = Math.round(+ev.target.value); if (n >= 4 && n <= 40) change(() => { vdef(); c.video.draft_steps = n; }, { keepForm: true }); };
    const genVideo = async draft => {
      const ta = vsec.querySelector('textarea');
      if (ta.value !== ((c.video || {}).prompt || '')) change(() => { vdef(); c.video.prompt = ta.value; }, { keepForm: true });
      const steps = Math.round(+vsec.querySelector('.dsteps').value) || (c.video || {}).draft_steps || 10;
      const r = await api('/api/jobs', { method: 'POST', body: JSON.stringify({ kind: 'video', clip: c, which: 'video', dry: !!window.MITTLER_PLAN_DRY, draft: !!draft, steps }), headers: { 'Content-Type': 'application/json' } });
      const j = await r.json().catch(() => ({}));
      const st = vsec.querySelector('.jobst');
      if (!r.ok || j.ok === false) { reqErr[c.id + '|video'] = { msg: j.error || $L('pl.reqVideoFail'), at: Date.now() }; showJobStates(); return; }
      delete reqErr[c.id + '|video'];
      setStatus($L('pl.queued', { w: (j.warnings || []).join($t('sep.list')) })); pollJobs();
    };
    vsec.querySelector('.gen.primary').onclick = () => genVideo(false);
    vsec.querySelector('.gen.draft').onclick = () => genVideo(true);
    vsec.querySelector('.genStop').onclick = ev => { const id = ev.target.dataset.job; if (id) api(`/api/jobs/${id}/cancel`, { method: 'POST' }).then(pollJobs); };
    const takeOf = row => ((c.video || {}).takes || []).find(x => x.id === row.dataset.take);
    vsec.querySelectorAll('.vtake').forEach(row => row.onclick = e => {
      const k = takeOf(row); if (!k) return;
      if (e.target.closest('.adopt')) { adopt(c, k); return; }
      if (e.target.closest('.vctl')) {  // 位置・閉じる（行を選んだことにはしない）
        if (e.target.closest('.vclose')) tvClose();
        return;
      }
      if (e.target.closest('.vplay') || e.target.closest('.vthumb')) {  // 真ん中のプレビューで再生（音つき）。再生中にもう一度押すと一時停止
        const v = tvEl();
        if (TV.take === k.id && TV.src === k.src && !v.paused) v.pause();
        else { if (TV.take === k.id && v.ended) v.currentTime = 0; tvOpen(k); }
        return;
      }
      if ((c.video || {}).activeTake === k.id) return;
      change(() => { OPS.planVideoTake(c, k.id); });  // 選ぶ：タイムラインのこの場所に映る（採用はまだ）。editor/ops.js（API の video-take と同じ）
      seek(snapFrame(Math.min(c.start + c.dur - 1 / fps(), Math.max(c.start, S.t))));
      setStatus($L('pl.takeSelected', { id: k.id }));
    });
    vsec.querySelectorAll('.vctl input[type=range]').forEach(r => r.oninput = () => { const v = tvEl(); if (v.duration) v.currentTime = (+r.value / 1000) * v.duration; tvSync(); });
    tvSync();
    showJobStates();
    const vs = el.querySelector('.planSec[data-which="video"]');
    vs.querySelectorAll('[data-v]').forEach(inp => inp.onchange = () => change(() => { c.video = Object.assign({ prompt: '', engine: 'h3-fl2va', takes: [], activeTake: null }, c.video || {}); c.video[inp.dataset.v] = inp.value; }, { keepForm: true }));
  }
})();
