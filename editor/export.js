// Mittler 書き出し（Python エンジンだけ）。上の「書き出し」→ 品質・範囲・ファイル名を決めて始める。
// サーバー（/api/export）がこのPC（サーバーが動いている PC）で描いて <プロジェクト>/output/<名前>.mp4 に書く。進み具合は1秒ごとに聞く。
// 「完了後、この動画をプレビュー再生に使う」なら再生用の MP4 も作り、できたら preview.proxy をそれにする（タイムラインを書くのは編集画面だけ）。
// 🏆 マスター書き出し（機能追加案03 v2）：同じ枠で /api/export に {master: true}。設定・道具・キャッシュは /api/master、キャッシュの削除は /api/master/cache/clear。
// 画質（作品の settings.master.upscale。2026-10-31）：標準（none：高画質化なし・作品の大きさのまま 60fps）／高画質（アニメ）（anime）／高画質（実写）（real）。
//   選ぶとタイムラインに書く（作品ごと）。クリップごとの上書きは映像クリップの欄（warp.js の「マスター画質」）。
// 窓の作り（設定の項目と実装の説明を分ける。基本の操作には必要最小限の情報だけを出し、
//   内部の技術用語・開発者向けの説明は、詳細設定かツールチップに置く）：
//   基本＝品質（画質）・範囲・ファイル名・出力の要約1行・注意の短い1行。詳細設定（たたむ）＝同時処理数・キャッシュ・4K 未対応でも書き出す・保存先を開く。
//   長い説明・内部の言葉（キャンバス・scale・Real-ESRGAN・RIFE・補間・work/master など）はツールチップ（title）にだけ置く。ふつうの書き出しも同じ部品で同じ作り。
// 送る中身（POST /api/export の master・upscale・from・to・jobs・force・fresh・name、ふつうの step・scale・proxy）は前と同じ。
// 画面の言葉は辞書の ex.*（editor/i18n/*.json）。言葉を切り替えたら、開いている窓を入力を残したまま作り直す。
'use strict';
(function () {
  const X = (k, v) => $t('ex.' + k, v);
  const STATES = ['preparing', 'rendering', 'muxing', 'proxy', 'cancelling', 'cancelled', 'done', 'error'];
  const stateText = s => STATES.includes(s) ? X('st.' + s) : s;
  const BUSY = ['preparing', 'rendering', 'muxing', 'proxy', 'cancelling'];
  let job = { state: 'idle' }, timer = null, applied = '', advOpen = false;  // advOpen：詳細設定を開いているか（窓を開き直しても覚えておく）
  let where = '', defaultJobs = 16;  // 描くPC（サーバーが返す。いつもサーバーが動いている PC＝'このPC'）
  const whereText = w => (!w || w === 'このPC') ? X('thisPC') : w;  // サーバーの WHERE（'このPC'）は画面では今の言葉で
  const W_ = () => whereText(where);
  const LS = () => $t('sep.list');  // 「・」

  const btn = document.createElement('button');
  btn.id = 'exportBtn'; btn.hidden = true;
  $('status').before(btn);
  // 🏆 マスター書き出し：60fps・高画質の最終版（同じ書き出しの枠＝/api/export の {master: true} で動く）
  const mbtn = document.createElement('button');
  const MASTER_LABEL = () => MITTLER_ICO('trophy', X('master'));  // アイコン＋名前（名前は幅が狭いとたたむ。ui.js）
  mbtn.id = 'masterBtn'; mbtn.className = 'ib'; mbtn.hidden = true;
  $('status').before(mbtn);
  function btnTitles() { btn.title = where ? X('btnTipWhere', { where: W_() }) : X('btnTip'); mbtn.title = X('masterTip'); }
  // マスターの段階（サーバーの phase）→ 画面の言葉。STEPS は進み具合の画面の段の並び
  const STEPS = ['check', 'upscale', 'interp', 'render', 'encode'];
  const BAR = ['check', 'upscale', 'interp', 'encode'];
  // 画質（作品の settings.master.upscale の値 → 名前・ひとこと）。値の名前（none は /api/master の noUpscale）は変えない
  const QUAL = ['none', 'anime', 'real'];
  const qname = k => QUAL.includes(k) ? X('q.' + k) : (k || '');
  const qsub = k => X('q.' + k + '.sub');
  const panel = document.createElement('div');
  panel.id = 'exportPanel'; panel.hidden = true;
  document.body.appendChild(panel);

  const pad = n => String(n).padStart(2, '0');
  // 名前の初め・マスターの画質の初め・再生用の動画の入れ方は editor/ops.js（API の export・master と同じ）
  const defaultName = master => OPS.exportName(S.file, new Date(), master);
  const secs = s => s >= 60 ? X('secsM', { m: Math.floor(s / 60), s: pad(Math.round(s % 60)) }) : X('secs', { s: Math.round(s) });
  const about = s => s >= 90 ? X('left', { n: Math.round(s / 60) }) : s >= 50 ? X('left1') : X('soon');  // 残り時間はおおまかに
  const tshort = t => fmt(t).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');  // 0:10.000 → 0:10
  const tip = s => s ? ` title="${esc(s)}"` : '';
  const fpsTxt = f => String(+(+f).toFixed(2));

  // 窓の部品（ふつうの書き出しとマスターで同じ）
  const head = (title, note) => `<div class="xhead"><b>${title}</b><span class="sp"></span><button class="xx" data-x="close" title="${esc(note || X('close'))}">${MITTLER_ICON('x')}</button></div>`;
  const line = (k, v, o = {}) => `<div class="xline"${o.id ? ` id="${o.id}"` : ''}${o.hidden ? ' hidden' : ''}><span class="xk"${tip(o.tip)}>${k}</span><div class="xv">${v}</div></div>`;
  const card = (name, value, on, title, sub, o = {}) => `<label${tip(o.tip)}><input type="radio" name="${name}" value="${esc(value)}"${on ? ' checked' : ''}><b>${title}</b><small${o.warn ? ' class="warn"' : ''}>${sub}</small></label>`;
  const rangeLines = () => line(X('range'), `<div class="xseg"><label><input type="radio" name="xr" value="all" checked>${X('rangeAll')}<span class="xmut">${tshort(0)}${$t('sep.range')}${tshort(dur())}</span></label>`
      + `<label><input type="radio" name="xr" value="part">${X('rangePart')}</label></div>`)
    + line(X('from'), `<span class="xrow"><input type="text" inputmode="decimal" id="xFrom" value="${fmt(0)}" disabled title="${esc(X('timeIn.tip'))}"><span class="xmut">${X('timeIn')}</span><button data-x="now0" disabled title="${esc(X('now0.tip'))}">${X('now')}</button></span>`, { id: 'xPart0', hidden: true })
    + line(X('to'), `<span class="xrow"><input type="text" inputmode="decimal" id="xTo" value="${fmt(dur())}" disabled title="${esc(X('timeIn.tip'))}"><span class="xmut">${X('timeIn')}</span><button data-x="now1" disabled title="${esc(X('now1.tip'))}">${X('now')}</button></span>`, { id: 'xPart1', hidden: true });
  // 開始・終了の欄：画面の時刻と同じ 分:秒（1:28.213）で出す。
  // 前は秒だけ（88.213）だったので、1 分をこえると再生位置の表示（1:28.213）と違う数字に見えた。打つときは 分:秒 でも 秒だけ でもよい
  const parseT = s => {
    const v = String(s || '').trim().replace(/[：]/g, ':').replace(/[．。]/g, '.'); if (!v) return NaN;
    const parts = v.split(':'); if (parts.length > 3 || parts.some(p => !/^\d*\.?\d*$/.test(p) || p === '' || p === '.')) return NaN;
    return parts.reduce((a, p) => a * 60 + parseFloat(p), 0);
  };
  const rangeOf = () => {  // 一部のときの開始・終了（秒）。読めなければ知らせて null
    const from = parseT($('xFrom').value), to = parseT($('xTo').value);
    if (!isFinite(from) || !isFinite(to)) { setStatus($L('ex.stBadTime')); return null; }
    if (!(to > from)) { setStatus($L('ex.stToAfter')); return null; }
    return { from: snapFrame(Math.max(0, from)), to: snapFrame(Math.min(dur(), to)) };
  };
  const nameLine = v => line(X('name'), `<span class="xrow"><input type="text" id="xName" value="${esc(v)}"><span class="xmut">.mp4</span></span>`);
  const adv = body => `<details class="xadv"${advOpen ? ' open' : ''}><summary>${X('adv')}</summary><div class="xadvbody">${body}</div></details>`;
  const foot = (start, label) => `<div class="xfoot"><button data-x="close">${X('cancel')}</button><button class="primary" data-x="${start}">${label}</button></div>`;
  const revealLine = () => line(X('saveTo'), `<button data-x="reveal" data-path="output" title="${esc(X('revealOut.tip'))}">${X('revealOut')}</button><span class="xmut">output</span>`);
  function wireCommon() {  // 範囲（一部のときだけ開始・終了を出す）・詳細設定の開け閉めを覚える
    panel.querySelectorAll('input[name=xr]').forEach(r => r.onchange = () => {
      const part = panel.querySelector('input[name=xr]:checked').value === 'part';
      ['xFrom', 'xTo'].forEach(id => $(id).disabled = !part); panel.querySelectorAll('[data-x^=now]').forEach(b => b.disabled = !part);
      $('xPart0').hidden = $('xPart1').hidden = !part;
    });
    const d = panel.querySelector('details.xadv'); if (d) d.ontoggle = () => { advOpen = d.open; };
  }

  // ふつうの書き出し
  let lastView = '';  // 進み具合の窓に最後に描いた HTML（progressView）
  function form() {
    lastView = '';  // 設定の窓を出したら、次の進み具合は必ず描き直す（progressView は中身が同じなら描き直さない）
    const W = S.tl.width || 1920, H = S.tl.height || 1080, f = fps();
    const sz = s => s === 1 ? `${W}×${H}` : `${Math.trunc(W * s / 2) * 2}×${Math.trunc(H * s / 2) * 2}`;
    const drafttip = X('draft.tip');
    const sum = (st, s) => X('sum', { size: sz(s), fps: fpsTxt(f / st) }) + (st > 1 ? `<span class="xmut">${X('sumTook', { st })}</span>` : '');
    panel.innerHTML = head(X('title')) + `<div class="xbody">
        ${line(X('quality'), `<div class="xchoice">${card('xq', 1, true, X('final'), X('final.sub', { fps: fpsTxt(f) }), { tip: X('final.tip') })}
          ${card('xq', 2, false, X('draft'), X('draft.sub', { fps: fpsTxt(f / 2) }), { tip: drafttip })}
          ${card('xq', 4, false, X('draftFast'), X('draftFast.sub', { fps: fpsTxt(f / 4) }), { tip: drafttip })}</div>`)}
        ${line(X('size'), `<select id="xScale" disabled title="${esc(X('size.tip'))}">
            <option value="1">${X('size.orig', { sz: sz(1) })}</option><option value="0.5">${X('size.half', { sz: sz(0.5) })}</option><option value="0.25">${X('size.quarter', { sz: sz(0.25) })}</option></select>`, { id: 'xScaleRow', hidden: true })}
        ${rangeLines()}
        ${nameLine(defaultName())}
        ${line('', `<label class="xcheck" title="${esc(X('proxy.tip'))}"><input type="checkbox" id="xProxy" checked>${X('proxy')}</label>`)}
        <div class="xsum" id="xSum" title="${esc(X('sumWhere', { where: W_() }))}">${line(X('out'), `<span id="xOut">${sum(1, 1)}</span>`)}</div>
        ${adv(line(X('jobs'), `<input type="number" id="xJobs" min="1" max="32" value="${defaultJobs}">`, { tip: X('jobs.tip', { where: W_() }) }) +
          line('', `<label class="xcheck" title="${esc(X('nocache.tip'))}"><input type="checkbox" id="xNoCache">${X('nocache')}</label>`) + revealLine())}
      </div>${foot('start', X('start'))}`;
    const upd = () => { const st = +panel.querySelector('input[name=xq]:checked').value; $('xOut').innerHTML = sum(st, st > 1 ? +$('xScale').value : 1); };
    panel.querySelectorAll('input[name=xq]').forEach(r => r.onchange = () => {  // 下書きなら名前に _draft、プレビュー用の動画は作らない
      const st = +panel.querySelector('input[name=xq]:checked').value, nm = $('xName');
      nm.value = nm.value.replace(/_draft(_\d+)?$/, '') + (st > 1 ? '_draft' : '');
      $('xProxy').checked = st === 1; $('xScale').disabled = st === 1; if (st === 1) $('xScale').value = '1';
      $('xScaleRow').hidden = st === 1; upd();
    });
    $('xScale').onchange = upd;
    wireCommon();
  }

  // 🏆 マスター書き出しの設定（設定・道具・キャッシュはサーバーの /api/master から）
  async function masterForm() {
    lastView = '';  // 設定の窓を出したら、次の進み具合は必ず描き直す（progressView は中身が同じなら描き直さない）
    let mi = null; try { mi = await (await fetch('/api/master', { cache: 'no-store' })).json(); } catch (e) { }
    if (panel.dataset.form !== 'master') return;  // 待つあいだに閉じた・切り替えた
    const M = (mi && mi.settings) || { scale: 2, fps: 60, outHeight: 1080, cacheGb: 50, jobs: 0 }, tools = (mi && mi.tools) || {}, cache = (mi && mi.cache) || { gb: 0, files: 0 };
    const W = S.tl.width || 1920, H = S.tl.height || 1080;
    // 画質（作品ごと：タイムラインの settings.master.upscale。書いてなければ PC の設定のモデル＝ふつうはアニメ）
    const KIND = (mi && mi.upscale) || { anime: 'realesr-animevideov3', real: 'realesrgan-x4plus' }, hasM = tools.models || {};
    const NONE = (mi && mi.noUpscale) || 'none';
    const wup = ((S.tl.settings || {}).master || {}).upscale || '', cur = OPS.masterUpscale(S.tl, M, KIND);
    const cw = Math.round(W * M.scale), ch = Math.round(H * M.scale), is4K = Math.max(cw, ch) >= 3800;
    const HI = is4K ? '4K' : X('hiRes'), HIs = is4K ? X('hi4Ks') : HI;  // HIs：助詞の前（「4K に」。英語は空きなし）
    const outHi = M.outHeight > 0 ? (W < H ? `${M.outHeight}×${2 * Math.round(H * M.outHeight / W / 2)}` : `${2 * Math.round(W * M.outHeight / H / 2)}×${M.outHeight}`) : `${cw}×${ch}`;  // outHeight は短い辺（縦長の作品は幅）
    const size = k => k === NONE ? `${W}×${H}` : outHi;
    const ratio = +(M.fps / fps()).toFixed(1);
    // 画質のカード（使えないもの＝道具・モデルが無いは、ひとことを注意の色に。止まるのは書き出しの始め）
    const lackUp = k => tools.esrgan === false ? X('lackEsrgan') : hasM[k] === false ? X('lackModel', { model: KIND[k] }) : '';
    const hiTip = k => X('hiTip', { hi: HI, cw, ch, out: outHi }) + X(k === 'anime' ? 'hiTip.anime' : 'hiTip.real')
      + '\n\n' + X('hiTip.int', { model: KIND[k], fps: M.fps, scale: M.scale });
    const noneTip = X('noneTip', { w: W, h: H, fps: M.fps, his: HIs }) + '\n\n' + X('noneTip.int', { fps: M.fps });
    const qcard = k => {
      const lack = k === NONE ? '' : lackUp(k), q = k === NONE ? 'none' : k;
      return card('xUp', k, cur === k, qname(q), lack ? X('unavailable') : qsub(q), { warn: !!lack, tip: (k === NONE ? noneTip : hiTip(k)) + (lack ? '\n\n' + lack : '') });
    };
    // クリップごとの画質の指定（映像クリップの欄の「マスター画質」）：基本の画面は短い注意だけ、中身はツールチップ
    const overNote = k => {
      const over = { anime: 0, real: 0 };
      for (const tr of S.tl.tracks || []) if (!tr.hidden && ['video', 'plan'].includes(tr.kind)) for (const c of tr.clips || []) if (!c.disabled && over[c.upscale] !== undefined && c.upscale !== k) over[c.upscale]++;
      if (!over.anime && !over.real) return '';
      const list = [over.anime ? X('clipsN', { name: qname('anime'), n: over.anime }) : '', over.real ? X('clipsN', { name: qname('real'), n: over.real }) : ''].filter(Boolean).join(LS());
      return k === NONE
        ? `<span title="${esc(X('over.none.tip', { list }))}">${X('over.none')}</span>`
        : `<span title="${esc(X('over.tip', { list }))}">${X('over')}</span>`;
    };
    const toolNote = tools.rife === false ? `<span title="${esc(X('noRife.tip', { path: M.rife || '' }))}">${X('noRife')}</span>` : '';
    const notes = k => [overNote(k), toolNote].filter(Boolean).join('');
    const took = k => k === NONE ? X('took.none', { r: ratio }) : X(k === 'real' ? 'took.real' : 'took.hi');
    const sumTip = k => (k === NONE ? X('sumTip.none', { fps: M.fps }) : X('sumTip.hi', { hi: HI, cw, ch, out: outHi }))
      + X('sumTip.where', { where: W_() });
    const name = defaultName(true);
    const workTip = w => w ? X('workTip.set', { q: qname(w === NONE ? 'none' : w) }) : X('workTip.unset', { model: M.esrganModel || KIND.anime });
    panel.innerHTML = head(X('masterTitle')) + `<div class="xbody">
        ${line(X('mquality'), `<div class="xchoice">${[NONE, 'anime', 'real'].map(qcard).join('')}</div><div class="xnote" id="xUpOver">${notes(cur)}</div>`, { id: 'xUpLine', tip: workTip(wup) })}
        ${rangeLines()}
        ${nameLine(name)}
        <div class="xsum" id="xSum" title="${esc(sumTip(cur))}">${line(X('out'), `<span id="xOut">${X('sum', { size: size(cur), fps: M.fps })}</span><span class="xmut" id="xTook">${took(cur)}</span>`)}</div>
        ${adv(line(X('jobs'), `<input type="number" id="xJobs" min="0" max="32" value="${M.jobs || ''}" placeholder="${esc(X('auto'))}">`,
          { tip: X('mjobs.tip', { where: W_() }) })
        + line('', `<label class="xcheck" title="${esc(X('force.tip', { his: HIs }))}"><input type="checkbox" id="xForce">${X('force', { his: HIs })}</label>`, { id: 'xForceRow', hidden: cur === NONE })
        + line(X('cache'), `<span class="xrow"><span id="xCache">${X('cacheSize', { gb: cache.gb, files: cache.files })}</span><button data-x="mclear" title="${esc(X('cacheClear.tip'))}">${X('cacheClear')}</button></span>`,
          { tip: X('cache.tip', { gb: M.cacheGb }) })
        + line('', `<label class="xcheck" title="${esc(X('fresh.tip'))}"><input type="checkbox" id="xFresh">${X('fresh')}</label>`)
        + revealLine())}
      </div>${foot('mstart', X('start'))}`;
    wireCommon();
    // 画質：選んだらすぐタイムラインの settings.master.upscale に書く（作品ごとに覚える。取り消しもできる）
    panel.querySelectorAll('input[name=xUp]').forEach(r => r.onchange = () => {
      const v = r.value;
      change(() => { S.tl.settings = S.tl.settings || {}; S.tl.settings.master = Object.assign({}, S.tl.settings.master || {}, { upscale: v }); }, { keepForm: true });
      setStatus($L('ex.stQual', { q: { toString: () => qname(v === NONE ? 'none' : v) } }), 'ok');
      $('xOut').textContent = X('sum', { size: size(v), fps: M.fps }); $('xTook').textContent = took(v); $('xSum').title = sumTip(v);
      $('xUpOver').innerHTML = notes(v); $('xForceRow').hidden = v === NONE; panel.querySelector('#xUpLine .xk').title = workTip(v);
      if (v === NONE) $('xForce').checked = false;  // 標準では使わない（隠したまま送らない）
    });
  }

  // 書き出しはできたときの注意（MASTER_WARN の ' / ' 区切り。master.py の check_only の文。これはエンジンとの決まりなので日本語のまま）を、画面の言葉に。知らない文はそのまま
  const WARN = [['scale 未対応のまま描く（位置・大きさがずれることがある）：', 'warn.scale'],
    ['コマ番号で絵が変わるエフェクト（60fps で進みが変わる）：', 'warn.frame'],
    ['アップスケールなしなので、クリップのアップスケールは使わない：', 'warn.noUp']];
  const warnHTML = (w, master) => master ? `<ul class="xlist">${String(w).split(' / ').map(s => `<li>${esc(WARN.reduce((t, [a, b]) => t.replace(a, X(b)), s))}</li>`).join('')}</ul>` : `<pre class="xerr">${esc(w)}</pre>`;
  // マスターの画質の値（サーバーの cfg.kind。古いサーバーなら表示の文から）
  const jobKind = j => (j.cfg && j.cfg.kind != null ? j.cfg.kind : j.kind) || (j.cfg && j.cfg.upscale ? (/^なし/.test(j.cfg.upscale) ? 'none' : /^実写/.test(j.cfg.upscale) ? 'real' : 'anime') : '');
  // 止まった理由（MASTER_STOP の kind）→ 見出し・どうすればよいか。名指しの一覧と元の文は「詳細」を開くと見える
  function stopHTML(j) {
    const s = j.stop || {}, list = [];
    const hiRes = j.cfg && j.cfg.scale > 1 && Math.max((S.tl.width || 1920) * j.cfg.scale, (S.tl.height || 1080) * j.cfg.scale) < 3800;
    const HI = hiRes ? X('hiRes') : X('hi4Ks');  // 「4K に」（助詞の前に空き）
    let headTxt = X('failed'), hint = '', what = '';
    if (s.kind === 'effects') {
      headTxt = X('stop.effects', { his: HI });
      hint = X('stop.effects.hint', { his: HI });
      what = X('stop.effects.what', { n: (s.effects || []).length });
      for (const m of s.effects || []) list.push(`<li><b>${esc(m.name)}</b><span class="xmut">${X('clipN', { n: m.clips })}${m.why ? LS() + esc(m.why) : ''}</span></li>`);
    } else if (s.kind === 'tools') {
      headTxt = X('stop.tools');
      hint = X('stop.tools.hint');
      what = X('stop.tools.what', { n: (s.tools || []).length });
      const TN = { esrgan: X('tn.esrgan'), esrgan_model: X('tn.esrgan_model'), rife: X('tn.rife') };
      for (const t of s.tools || []) list.push(`<li><b>${esc(TN[t.tool] || t.tool)}</b><span class="xmut">${esc(t.path || '')}</span></li>`);
    } else if (s.kind === 'upscale') {
      headTxt = X('stop.upscale');
      hint = X('stop.upscale.hint');
      what = X('stop.upscale.what', { n: (s.items || []).length });
      for (const t of s.items || []) list.push(`<li>${esc(t)}</li>`);
    } else if (s.kind === 'tool_failed') headTxt = X('stop.toolFailed');
    let h = `<div class="xmsg bad"><b>${headTxt}</b>${hint ? `<div>${hint}</div>` : ''}</div>`;
    if (list.length) h += `<details class="xdet"><summary>${what}</summary><ul class="xlist">${list.join('')}</ul></details>`;
    return h + `<details class="xdet"><summary>${X('errDetail')}</summary><pre class="xerr">${esc(j.error || '')}</pre></details>`;
  }
  function progressView() {
    const j = job, busy = BUSY.includes(j.state), pct = j.total ? Math.min(100, 100 * j.done / j.total) : 0;
    const kind = j.master ? jobKind(j) : '', mf = (j.cfg && j.cfg.fps) || 60;
    let h = head(j.master ? X('masterTitle') : X('title'), busy ? X('closeBusy') : X('close')) + '<div class="xbody">';
    h += `<div class="xfile" title="${esc(j.name || '')}">${esc(j.name || '')}</div>`;
    // 何を・どこを（技術的なこと＝キャンバスの倍率・同時処理数・アップスケールの記録はツールチップに）
    let info = '', itip = '';
    if (j.master) {
      info = [fmt(j.from || 0) + $t('sep.range') + fmt(j.to || 0), j.cfg ? X('resSize', { size: j.cfg.size, fps: mf }) : '', qname(kind), j.fresh ? X('info.fresh') : ''].filter(Boolean).join(LS());
      itip = j.cfg ? X('info.mtip', { scale: j.cfg.scale, fps: j.cfg.fps, size: j.cfg.size, up: j.cfg.upscale || '', jobs: j.jobs || X('auto'), where: whereText(j.where || where) }) : '';
    } else if (j.state !== 'idle') {
      info = [fmt(j.from || 0) + $t('sep.range') + fmt(j.to || 0), j.step > 1 || (j.scale && j.scale < 1) ? X('info.draft', { fps: fpsTxt(fps() / (j.step || 1)) }) + (j.scale < 1 ? X('info.scale', { n: Math.round(1 / j.scale) }) : '') : ''].filter(Boolean).join(LS());
      itip = X('info.tip', { jobs: j.jobs || '', where: whereText(j.where || where) });
    }
    if (busy) {
      // マスターの段階：準備 → 高画質化 → 60fps 化 → 書き出し → 仕上げ（標準は高画質化なし）
      const ph = j.state === 'muxing' ? 'encode' : j.master ? (j.phase || 'check') : '';
      const pre = j.master && ['check', 'upscale', 'interp'].includes(ph);
      let title = stateText(j.state), sub = '', p = null;
      if (j.state === 'cancelling') p = null;  // 中止の途中：見出しだけ
      else if (j.phase === 'blender' && j.state === 'rendering') {  // Blender の 3D：区間に分ける前にまとめて描く段（PHASE blender）
        title = X('ph.blender'); sub = X('ph.blender.sub', { d: j.phaseDone || 0, t: j.phaseTotal || 0 });
        p = j.phaseTotal ? Math.min(100, 100 * j.phaseDone / j.phaseTotal) : null;
      } else if (pre) {
        title = ph === 'check' ? X('ph.check') : ph === 'upscale' ? X('ph.upscale') : X('ph.interp', { fps: mf });
        sub = ph === 'check' ? X('ph.check.sub') : j.phaseTotal ? X('ph.items', { d: j.phaseDone, t: j.phaseTotal }) : '';
        p = j.phaseTotal ? Math.min(100, 100 * j.phaseDone / j.phaseTotal) : null;
      } else if (j.state === 'rendering') {
        p = pct;
        const eta = j.done > 0 && j.sec > 0 ? LS() + about(j.sec * (j.total - j.done) / j.done) : '';
        sub = X('frames', { d: j.done || 0, t: j.total || 0 }) + (j.sec ? X('elapsed', { t: secs(j.sec) }) : '') + eta;
      } else if (j.state === 'muxing') sub = X('ph.mux.sub');
      h += `<div class="xstate"><span>${esc(title)}</span>${p != null && !pre ? `<span class="xpct">${p.toFixed(0)}%</span>` : ''}</div>`;
      h += `<div class="xprog${p == null ? ' ind' : ''}"><i style="width:${(p || 0).toFixed(1)}%"></i></div>`;
      if (sub) h += `<div class="xmut">${esc(sub)}</div>`;
      if (j.master) {
        const steps = STEPS.filter(k => !(k === 'upscale' && kind === 'none')), at = steps.findIndex(k => k === ph);
        h += `<ol class="xsteps">${steps.map((k, i) => `<li class="${i < at ? 'done' : i === at ? 'on' : ''}">${k === 'interp' ? X('step.interpN', { fps: mf }) : X('step.' + k)}</li>`).join('')}</ol>`;
      }
      if (info) h += `<div class="xmut xinfo"${tip(itip)}>${esc(info)}</div>`;
    } else if (j.state === 'done' && j.result) {
      const r = j.result, took = j.finished && j.started ? secs((j.finished - j.started) / 1000) : '';
      h += `<div class="xmsg ok"><b>${MITTLER_ICON('circle-check')} ${stateText('done')}</b></div>`;
      h += `<div class="xres" title="${esc(X('shaTip', { sha: r.sha256, where: whereText(r.where || where) }))}"><div class="xpath">${esc(r.path)}</div>
        <div class="xmut">${[r.size ? X('resSize', { size: r.size, fps: r.fps || '' }) + (r.draft ? X('draftMark') : '') : '', `${(r.bytes / 1e6).toFixed(1)} MB`, r.dur ? X('durSec', { s: r.dur.toFixed(2) }) : '', took ? X('tookTime', { t: took }) : ''].filter(Boolean).join(LS())}</div></div>`;
      if (j.cached) h += `<div class="xmut">${X('cachedUsed', { n: j.cached, total: j.total || '' })}</div>`;  // 差分書き出し：ためた絵を使ったコマ（fcache）
      if (r.proxy) h += `<div class="xmut">${X('proxyFile', { p: esc(r.proxy) })}${S.tl.preview && S.tl.preview.proxy === r.proxy ? X('proxyInUse') : ''}</div>`;
      if (j.proxyError) h += `<details class="xdet"><summary class="warn">${X('proxyErr')}</summary><pre class="xerr">${esc(j.proxyError)}</pre></details>`;
      if (j.warning) h += `<details class="xdet"><summary class="warn">${X('doneWarn')}</summary>${warnHTML(j.warningKey ? $t(j.warningKey) : j.warning, j.master)}</details>`;
      if (info) h += `<div class="xmut xinfo"${tip(itip)}>${esc(info)}</div>`;
    } else if (j.state === 'error') {
      h += j.master ? stopHTML(j) : `<div class="xmsg bad"><b>${X('failed')}</b></div><details class="xdet"><summary>${X('errDetail')}</summary><pre class="xerr">${esc(j.error || '')}</pre></details>`;
    } else if (j.state === 'cancelled') h += `<div class="xmsg"><b>${stateText('cancelled')}</b></div>`;
    h += '</div>';
    if (busy) { if (['preparing', 'rendering', 'muxing'].includes(j.state)) h += `<div class="xfoot"><button data-x="cancel" title="${esc(X('cancelJob.tip'))}">${X('cancelJob')}</button></div>`; }
    else h += `<div class="xfoot">${j.state === 'done' && j.result ? `<button data-x="reveal" data-path="${esc(j.result.path)}" title="${esc(X('revealFile.tip'))}">${X('revealFile')}</button>` : `<button data-x="reveal" data-path="output" title="${esc(X('revealOut2.tip'))}">${X('revealOut2')}</button>`}<span class="sp"></span>
      <button data-x="again">${j.state === 'done' ? X('again') : X('back')}</button>${j.state === 'done' ? `<button class="primary" data-x="close">${X('close')}</button>` : ''}</div>`;
    // エラーの全文（pre.xerr）には「コピー」のボタン（選んでコピーしにくい・選んでも次の更新で消えるため。2026-11-22）
    h = h.replace(/<pre class="xerr">/g, `<button type="button" class="xcopy" data-x="copyerr">${X('copyErr')}</button><pre class="xerr">`);
    // 中身が変わらないときは描き直さない（描き直すと、選んでいる文字と開いた「詳細」が消える）。変わったときも、開いていた「詳細」は開いたままにする
    if (h === lastView) return;
    const open = [...panel.querySelectorAll('details.xdet')].map(d => d.open);
    lastView = h; panel.innerHTML = h;
    panel.querySelectorAll('details.xdet').forEach((d, i) => { if (open[i]) d.open = true; });
  }
  function copyErr(btn) {
    const pre = btn.nextElementSibling; if (!pre) return;
    const done = () => { btn.textContent = X('copied'); setTimeout(() => { btn.textContent = X('copyErr'); }, 1500); };
    const fallback = () => { const sel = getSelection(), rg = document.createRange(); rg.selectNodeContents(pre); sel.removeAllRanges(); sel.addRange(rg); try { if (document.execCommand('copy')) done(); } catch (e) { } };
    try { navigator.clipboard.writeText(pre.textContent).then(done, fallback); } catch (e) { fallback(); }
  }
  function render() { if (panel.dataset.form === 'master') return masterForm(); else if (panel.dataset.form) form(); else progressView(); }
  function barText() {
    if (BUSY.includes(job.state)) {
      const pct = job.total ? Math.round(100 * job.done / job.total) : 0;
      const b = job.master ? mbtn : btn, label = job.master ? '{icon:trophy}' : X('btn'), ph = job.state === 'muxing' ? 'encode' : job.phase;  // {icon:…} は ui.js がアイコンに
      b.textContent = job.phase === 'blender' && job.state === 'rendering' ? `${label} {icon:box} ${job.phaseTotal ? Math.round(100 * job.phaseDone / job.phaseTotal) : 0}%`  // Blender の 3D をまとめて描いている
        : job.state === 'rendering' && (!job.master || ph === 'render') ? `${label} ${pct}%` : job.master && BAR.includes(ph) ? `${label} ${X('bar.' + ph)}…` : `${label}…`;
      b.classList.add('busy');
    } else { btn.textContent = X('btn'); btn.classList.remove('busy'); mbtn.innerHTML = MASTER_LABEL(); mbtn.classList.remove('busy'); }
  }
  btnTitles(); barText();
  // できたら：再生用の動画を preview.proxy に入れる（1回だけ。取り消しもできる）
  function applyProxy() {
    const r = job.result; if (job.state !== 'done' || !r || !r.proxy || !job.wantProxy) return;  // wantProxy はサーバーが覚えている
    const key = `${job.started}|${r.proxy}`; if (applied === key) return; applied = key;
    // API（tools/mittler_api.py の export）で始めた書き出しは、サーバーがタイムラインに入れた（job.proxyApplied）：読み込み直すだけ
    if (job.proxyApplied || (S.tl.preview && S.tl.preview.proxy === r.proxy)) {  // 同じ名前の再生用の動画を作り直した：読み込み直す
      const v = $('proxy'); v.removeAttribute('src'); v.setAttribute('src', projUrl(r.proxy) + '?v=' + job.finished); return;
    }
    change(() => { OPS.applyProxy(S.tl, r.proxy, X('proxyNote', { name: base(r.path) })); });
    const v = $('proxy'); v.setAttribute('src', projUrl(r.proxy));
  }
  async function poll() {
    clearTimeout(timer); timer = null;
    try {
      const r = await fetch('/api/export', { cache: 'no-store' }); if (!r.ok) return;
      const prev = job.state; job = await r.json();
      if (job.where) { where = job.where; defaultJobs = job.defaultJobs || 16; btnTitles(); }
      barText();
      if (!panel.hidden && !panel.dataset.form) render();
      if (BUSY.includes(prev) && ['done', 'error', 'cancelled'].includes(job.state)) {  // この画面で見ていた書き出しが終わった
        const what = $L(job.master ? 'ex.whatMaster' : 'ex.whatExport');
        if (job.state === 'done') setStatus($L('ex.stDone', { what, path: job.result.path }), 'ok');
        else if (job.state === 'error') setStatus($L('ex.stError', { what }));
        else setStatus($L('ex.stCancelled', { what }), 'ok');
        applyProxy();
        if (panel.hidden) { panel.hidden = false; delete panel.dataset.form; render(); }
      }
    } catch (e) { }
    if (BUSY.includes(job.state)) timer = setTimeout(poll, 1000);
  }
  async function reveal(rel) {  // 📂 フォルダを開く（サーバーがエクスプローラーで開く）
    try {
      const r = await (await api('/api/reveal', { method: 'POST', body: JSON.stringify({ path: rel }), headers: { 'Content-Type': 'application/json' } })).json();
      setStatus(r.ok ? $L('ex.stRevealed', { path: r.path }) : $L('ex.stRevealFail', { err: r.error || '' }));
    } catch (e) { setStatus($L('ex.stRevealFail', { err: String(e) })); }
  }
  async function startExport() {
    const part = panel.querySelector('input[name=xr]:checked').value === 'part';
    const body = { name: $('xName').value.trim() || defaultName(), jobs: +$('xJobs').value || 16, proxy: $('xProxy').checked,
      step: +panel.querySelector('input[name=xq]:checked').value, scale: +$('xScale').value, nocache: $('xNoCache').checked };
    if (part) { const r = rangeOf(); if (!r) return; body.from = r.from; body.to = r.to; }
    const prev = job;
    job = { state: 'preparing', name: body.name + '.mp4', from: body.from || 0, to: body.to || dur(), jobs: body.jobs, scale: body.scale, step: body.step, done: 0 };  // 押したらすぐ「準備しています」（前の結果を出さない）
    delete panel.dataset.form; render(); barText();
    if (S.saveTimer || S.saving) { setStatus($L('ex.stWaitSave'), 'busy'); while (S.saveTimer || S.saving) await new Promise(r => setTimeout(r, 200)); }
    const r = await api('/api/export', { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } });
    if (!r.ok) { job = prev; barText(); panel.dataset.form = '1'; form(); setStatus($L('ex.stStartFail', { err: (await r.json().catch(() => ({}))).error || r.status })); return; }
    clog(`書き出し開始 ${JSON.stringify(body)}`);
    poll();
  }
  async function startMaster() {
    const part = panel.querySelector('input[name=xr]:checked').value === 'part';
    const body = { master: true, name: $('xName').value.trim() || defaultName() + '_master', jobs: +$('xJobs').value || 0, force: $('xForce').checked, fresh: $('xFresh').checked };
    // 画質：窓で選んでいるものをそのまま渡す（タイムラインへの保存が間に合わない・届かないときも、見えているとおりに書き出す。2026-10-31）
    const up = panel.querySelector('input[name=xUp]:checked'); if (up) body.upscale = up.value;
    if (part) { const r = rangeOf(); if (!r) return; body.from = r.from; body.to = r.to; }
    const prev = job;
    job = { state: 'preparing', master: true, fresh: body.fresh, phase: 'check', kind: body.upscale || '', name: body.name + '.mp4', from: body.from || 0, to: body.to || dur(), jobs: body.jobs, done: 0 };
    delete panel.dataset.form; render(); barText();
    if (S.saveTimer || S.saving) { setStatus($L('ex.stWaitSave'), 'busy'); while (S.saveTimer || S.saving) await new Promise(r => setTimeout(r, 200)); }
    const r = await api('/api/export', { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } });
    if (!r.ok) { job = prev; barText(); panel.dataset.form = 'master'; masterForm(); setStatus($L('ex.stMStartFail', { err: (await r.json().catch(() => ({}))).error || r.status })); return; }
    clog(`マスター書き出し開始 ${JSON.stringify(body)}`);
    poll();
  }
  async function clearCache() {  // キャッシュの削除：窓は作り直さず、大きさの表示だけ直す（選んでいる範囲・名前はそのまま）
    try {
      const r = await (await api('/api/master/cache/clear', { method: 'POST' })).json();
      if (r.ok) setStatus($L('ex.stCacheCleared', { files: r.files, gb: r.gb }), 'ok'); else setStatus($L('ex.stCacheFail', { err: r.error || '' }));
    } catch (e) { setStatus($L('ex.stCacheFail', { err: String(e) })); }
    try { const c = (await (await fetch('/api/master', { cache: 'no-store' })).json()).cache; if ($('xCache') && c) $('xCache').textContent = X('cacheSize', { gb: c.gb, files: c.files }); } catch (e) { }
  }
  panel.addEventListener('click', e => {
    const x = e.target.closest('[data-x]') && e.target.closest('[data-x]').dataset.x; if (!x) return;
    const el = e.target.closest('[data-x]');
    if (x === 'close') panel.hidden = true;
    else if (x === 'start') startExport();
    else if (x === 'mstart') startMaster();
    else if (x === 'mclear') clearCache();
    else if (x === 'cancel') { api('/api/export/cancel', { method: 'POST' }); job.state = 'cancelling'; render(); }
    else if (x === 'again') { panel.dataset.form = job.master ? 'master' : '1'; render(); }
    else if (x === 'reveal') reveal(el.dataset.path || 'output');
    else if (x === 'copyerr') copyErr(el);
    else if (x === 'now0') $('xFrom').value = fmt(S.t);  // 再生位置の表示（下の時刻）とまったく同じ 分:秒。コマには書き出すときにそろえる（rangeOf）
    else if (x === 'now1') $('xTo').value = fmt(S.t);
  });
  panel.addEventListener('keydown', e => {  // 入力中の Space・Delete で再生やクリップ削除が動かないように。Esc で閉じる
    e.stopPropagation();
    if (e.key === 'Escape') panel.hidden = true;
  });
  btn.onclick = () => {
    if (!panel.hidden) { panel.hidden = true; return; }
    panel.hidden = false;
    if (BUSY.includes(job.state)) { delete panel.dataset.form; progressView(); } else { panel.dataset.form = '1'; form(); }
  };
  mbtn.onclick = () => {  // 🏆：マスター書き出しの設定（書き出しの途中ならその進み具合）
    if (!panel.hidden && (panel.dataset.form === 'master' || (!panel.dataset.form && job.master))) { panel.hidden = true; return; }
    panel.hidden = false;
    if (BUSY.includes(job.state)) { delete panel.dataset.form; progressView(); } else { panel.dataset.form = 'master'; masterForm(); }
  };
  // 言葉を切り替えたら：ボタンと、開いている窓を作り直す（入力した値・選んだものは残す）
  async function relang() {
    btnTitles(); barText();
    if (panel.hidden) return;
    const keep = [];
    for (const el of panel.querySelectorAll('input, select')) {
      if (el.type === 'radio') { if (el.checked && ['xq', 'xr'].includes(el.name)) keep.push(['radio', el.name, el.value]); }
      else if (el.id) keep.push([el.type === 'checkbox' ? 'check' : 'value', el.id, el.type === 'checkbox' ? el.checked : el.value]);
    }
    await render();
    for (const [how, a, v] of keep.filter(k => k[0] === 'radio')) {
      const r = panel.querySelector(`input[name=${a}][value="${v}"]`); if (r && !r.checked) { r.checked = true; r.dispatchEvent(new Event('change')); }
    }
    for (const [how, id, v] of keep.filter(k => k[0] !== 'radio')) {
      const el = document.getElementById(id); if (!el || !panel.contains(el)) continue;
      if (how === 'check') el.checked = v; else el.value = v;
    }
  }
  if (window.MITTLER_I18N) MITTLER_I18N.onChange(relang);
  // 読み込まれたらボタンを出し、途中の書き出しがあれば続きを見る
  const wait = setInterval(() => {
    if (!S.tl) return; clearInterval(wait);
    btn.hidden = false; mbtn.hidden = false; poll();
  }, 200);
  // 外（tools/mittler_api.py の export・master）で書き出しを始めた：サーバーの知らせ 'export' で見に行く（進み具合が上のバーに出る。終わったら結果の窓）
  const prevChange = window.MITTLER_ON_CHANGE;
  window.MITTLER_ON_CHANGE = kinds => { if (prevChange) prevChange(kinds); if (kinds.includes('export')) poll(); };
  // 窓を開く・閉じる（API の見える操作 ui open-export・open-master・close-export。editor/remote.js）。書き出しの途中ならその進み具合
  function open(master) {
    panel.hidden = false;
    if (BUSY.includes(job.state)) { delete panel.dataset.form; progressView(); }
    else if (master) { panel.dataset.form = 'master'; masterForm(); } else { panel.dataset.form = '1'; form(); }
  }
  window.MITTLER_EXPORT = { get job() { return job; }, poll, open, close: () => { panel.hidden = true; }, get isOpen() { return !panel.hidden; } };
})();
