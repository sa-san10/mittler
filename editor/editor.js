// Mittler 編集画面。正本は *.cut.json（とプロジェクトの effects/*.py）。ファイルが変わったら読み直す。
// Python エンジン（format "mittler/py…"。前の名前の "claude-cut/py…" も同じ形）：再生は書き出し済みの動画（preview.proxy）、止めると今のタイムラインの1コマを描画サーバーから（/api/frame）。
// エフェクトのクリップ：選んでパラメータを直す・ドラッグで動かす・端で長さを変える・Delete で消す・Ctrl+Z で戻す・コードを開く。色の卓（カットごと）。
'use strict';
const $ = id => document.getElementById(id);
const TOKEN = new URLSearchParams(location.search).get('token') || '';
const S = {
  tl: null, file: '', t: 0, playing: false, pps: 40, sel: null, fx: {}, reqId: 0, undo: [],
  drag: null, saveTimer: null, saving: null, lastSaved: '', exactUrl: '', exactT: null, gradeCut: null, dragging: false,
  ver: 0, shownVer: -1, metaTab: null, metaNow: -2, metaItems: [], metaGen: 0, pane: 'sel', edits: 0,  // ver＝保存（と外での直し）の回数、shownVer＝出ている1コマを頼んだときの ver（同じなら最新）
  assetVer: 0,  // 絵・動画のファイルが外で変わった回数（サムネ・テイクの絵の URL に付けて、同じ名前の上書きでも読み直す）
};

const fps = () => S.tl.fps || 30;
const dur = () => S.tl.duration || 10;
// タイムラインの右の余白（動画の外）：ここにクリップを置く・動かすと動画が伸びる（change の autoExtend）
const padSec = () => Math.max(5, dur() * 0.15);
const snapFrame = t => Math.round(t * fps()) / fps();
// ---- コマに乗っている時刻は、コマの時刻そのもの（n / fps の小数）で書く（2026-11-12）----
// 前は、動かす・伸び縮み・分けるたびに時刻を小数 6 桁に丸めて書いていた。コマの時刻の 3 つに 1 つ（0.6666666… → 0.666667）は丸めると大きくなり、
// エンジンは start <= t で比べるので、タイムラインで合わせたコマより 1 コマ遅れて切り替わっていた。
// 決まり：コマの時刻から 1e-6 秒より近い値は n / fps にする。コマに乗っていない値（拍に吸いつけた・素材の長さなど）は今までどおり 6 桁。
// 書きかえるのは、その操作で変わった値だけ（change の normalizeTimes）。開いただけ・触っていないクリップの値は変えない。
const T_EPS = 1e-6;
const onFrame = x => { const f = snapFrame(x); return Math.abs(f - x) < T_EPS ? f : null; };  // コマの時刻（乗っていなければ null）
const snapT = x => { const f = onFrame(x); return f == null ? x : f; };                      // コマに乗っていればその時刻、いなければそのまま
const rT = x => { const f = onFrame(x); return f == null ? +(+x).toFixed(6) : f; };          // コマに乗っていればその時刻、いなければ 6 桁
const _f64 = new Float64Array(1), _u64 = new BigUint64Array(_f64.buffer);
const prevDouble = v => { _f64[0] = v; _u64[0] -= 1n; return _f64[0]; };                      // v（正の数）のすぐ下の小数
// 頭 s のクリップの終わりをコマの時刻 f にする長さ。エンジンは s + 長さ を計算して t < s + 長さ で比べるので、その足し算が f をこえないようにする
// （こえると、終わりのコマでもまだかかっていることになり、1 コマ長くなる）
function durTo(s, f) { let v = f - s; while (v > 0 && s + v > f) v = prevDouble(v); return v; }
// change の中の直し fn のあとの決まり（この操作で変わった時刻をそろえる・動画の外に置いたら長さを伸ばす）は editor/ops.js の finish（API の直しも同じもの。2026-11-15）
const OPS = window.MITTLER_OPS;
const fmt = OPS.fmt;
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
const base = p => String(p || '').split('/').pop();
// 作品のフォルダからのパス（preview.proxy など）を URL に。名前に # % ? があっても読めるように、/ で区切った 1 つずつをエンコードする
// （前はそのままつないでいて、書き出しの名前に # などがあると再生用の動画が読めなかった）
const projUrl = p => '/project/' + String(p).split('/').map(encodeURIComponent).join('/');
function api(path, opts = {}) {
  opts.headers = Object.assign({ 'X-Mittler-Token': TOKEN }, opts.headers || {});
  return fetch(path, opts);
}
// 上のバーの 1 行の知らせ。msg は文字列か、あとで訳す文（$L。言葉を切り替えたら訳し直す）。
// level（種類。色は editor.css の .status[data-level]）：'ok' できた・'busy' 待っている・'warn' 注意・'bad' 失敗・'act' 押せる（「ここを押すと…」）・''（ふつう）。
// 種類は呼ぶ側が決める（前は文の言葉から決めていた。言葉を切り替えられるようにしたので、2026-11-12 にやめた）。
// 失敗は、次の知らせですぐ上書きされても分かるように、右下の知らせ（閉じるまで残る）にも出す（opts.toast が false なら出さない：
// 描画サーバーの知らせ（2 秒ごと・コマごとに同じ文が来る）と、保存の失敗（scheduleSave が自分で出して、通ったら消す））。同じ鍵の失敗は 1 つにまとめる
S.status = { msg: '', level: '' };
function setStatus(msg, level, opts) {
  msg = msg == null ? '' : msg; level = level || '';
  S.status = { msg, level }; S.statusKey = (msg && msg.k) || '';
  paintStatus();
  if (level === 'bad' && window.MITTLER_NOTIFY && !(opts && opts.toast === false)) MITTLER_NOTIFY(msg, 'bad', { key: 'st:' + (S.statusKey || String(msg).slice(0, 12)) });
}
function paintStatus() {
  const el = $('status'), s = String(S.status.msg); el.textContent = s; el.title = s; el.dataset.level = S.status.level;
  if (S.status.level === 'act') { el.tabIndex = 0; el.setAttribute('role', 'button'); } else { el.removeAttribute('tabindex'); el.setAttribute('role', 'status'); }
}
// 今の知らせが、この鍵（$L の鍵。前の頭の一致）か
const statusIs = (...keys) => keys.some(k => S.statusKey === k || S.statusKey.startsWith(k + '.'));
// 今の直しをすぐ保存する（Ctrl+S。保存は自動なので、待っている保存を前倒しするだけ）
function saveNow() {
  if (S.saveTimer) { scheduleSave(0); setStatus($L('st.saving'), 'busy'); return; }
  if (S.saving) { setStatus($L('st.saving'), 'busy'); return; }
  if (S.lastSaved === JSON.stringify(S.tl)) setStatus($L('st.alreadySaved'), 'ok'); else setStatus($L('st.saving'), 'busy');
  if (S.lastSaved !== JSON.stringify(S.tl)) scheduleSave(0);
}

// ---------- 読み込み ----------
async function loadTimeline() {
  const r = await fetch('/api/timeline', { cache: 'no-store' }); const j = await r.json();
  S.tl = j.timeline; S.file = j.file; $('file').textContent = S.tl.name || j.file; $('file').title = $t('file.title', { name: S.tl.name || '', file: j.file });
  $('proxy').hidden = false;
  const src = S.tl.preview && S.tl.preview.proxy ? projUrl(S.tl.preview.proxy) : '';
  if ($('proxy').getAttribute('src') !== src) { if (src) $('proxy').setAttribute('src', src); else $('proxy').removeAttribute('src'); }
  if (S.sel && !findClip(S.sel)) S.sel = null;
  S.lastSaved = JSON.stringify(S.tl);
  try { S.hideShy = !!localStorage.getItem('cc.hideShy:' + S.file); } catch (e) { }
  await loadChars();
  if (S.pps < fitPps()) S.pps = fitPps();  // 短い作品：開いたときから全体を幅いっぱいに（前は 40px/秒のままで左に寄っていた。窓の大きさを変えたときの決まりと同じ）
  buildTimeline(); fitScreen(); showSel(); zoomRange(); buildMetaPanel();
}
async function loadChars() {
  if (!S.tl || !S.tl.characters) { S.chars = { characters: [] }; return; }
  try { const r = await fetch('/api/file?path=characters.json', { cache: 'no-store' }); S.chars = r.ok ? JSON.parse(await r.text() || '{}') : { characters: [] }; }
  catch (e) { S.chars = { characters: [] }; }
  if (!S.chars.characters) S.chars.characters = [];
}
async function loadEffects() {
  try {
    const r = await api('/api/effects', { cache: 'no-store' }); if (!r.ok) throw new Error(await r.text());
    S.fx = await r.json(); S.fxReady = true; buildTimeline(); showSel();  // fxReady：カットの段の道具（cutmeta.js）が「カットごとのエフェクト」を見分けられる
  } catch (e) { setStatus($L('st.waitEffects'), 'busy'); setTimeout(loadEffects, 3000); }
}
// ---------- 時刻・描画 ----------
function cutAt(t) {
  const m = (S.tl.meta || []).find(x => x.kind === 'cuts'); if (!m) return null;
  let c = m.items[0]; for (const x of m.items) if (t >= x.start) c = x; return c;
}
function draw() {
  $('time').textContent = fmt(S.t); $('frame').textContent = 'f' + Math.round(S.t * fps());
  $('playhead').style.left = (S.t * S.pps) + 'px';
  const c = cutAt(S.t); $('cutNow').textContent = c ? $t('cut.label', { label: c.label }) : '';
  if (!S.playing && !(window.MITTLER_TAKEVIEW && MITTLER_TAKEVIEW.isOpen())) requestExact();  // テイクの動画を見ているあいだは描かない（plan.js）
  showMetaNow();
  if (c && c.label !== S.gradeCut) buildGradePanel();
}
function seek(t) {
  if (window.MITTLER_TAKEVIEW && MITTLER_TAKEVIEW.isOpen()) MITTLER_TAKEVIEW.close();  // テイクの動画を見ていたら閉じて、タイムラインの絵に戻す
  S.t = Math.max(0, Math.min(dur(), t)); if (!S.dragging) followPlayhead();
  const v = $('proxy'); if (v.src && Math.abs(v.currentTime - S.t) > 0.5 / fps()) v.currentTime = S.t;
  if (S.playing && window.MITTLER_AUDIO && window.MITTLER_AUDIO.has()) { window.MITTLER_AUDIO.stop(); window.MITTLER_AUDIO.start(S.t); }
  if (S.playing && S.noProxy) S.clock = { t0: S.t, at: performance.now() };
  draw();
}
let exactTimer = null;
// プレビューの縮小（下の「プレビュー」の切り替え。1＝等倍・0.5・0.25。既定 0.5）。描画サーバーは等倍で描いてから縮める（書き出しのドラフトと同じ）ので、
// 描く時間はほぼ同じで、送る JPEG が小さくなる。📷 PNG と書き出しはいつも等倍
S.pvScale = (() => { try { const v = +localStorage.getItem('cc.pvScale'); return [1, 0.5, 0.25].includes(v) ? v : 0.5; } catch (e) { return 0.5; } })();
function setPvScale(v) {
  S.pvScale = [1, 0.5, 0.25].includes(+v) ? +v : 0.5; try { localStorage.setItem('cc.pvScale', String(S.pvScale)); } catch (e) { }
  $('pvScale').value = String(S.pvScale); invalidateExact();
}
function requestExact() {
  const t = snapFrame(S.t);
  if (S.exactT === t && !$('frameImg').hidden) return;
  // 描き終わるまで前の絵を出したままにする（隠すと、その間は再生用の動画か黒が見えてチカチカして、目に悪い）
  $('gradeCv').hidden = true;
  // Blender の 3D のクリップがかかっている時刻は、ためた絵が無いと下描きに数秒かかるので、それと分かる札に
  const bl = (S.tl.tracks || []).some(tr => !tr.hidden && (tr.clips || []).some(c => c.type === 'effect' && !c.disabled && fxMeta(c).blender && c.start <= t && t < c.start + c.dur));
  showSrc($('frameImg').hidden ? $L('src.proxyRendering', { name: proxyName() }) : $L(bl ? 'src.blRendering' : 'src.prevRendering'));
  clearTimeout(exactTimer);
  const id = ++S.reqId, ver = S.ver;  // 先に番号を振る（前の時刻の返事が遅れて届いても出さない）
  exactTimer = setTimeout(async () => {
    // 前に頼んだ絵がまだなら取り消す（描くのが重い作品で頼みが積もり、ブラウザの同時接続（1つのサーバーに6本）が埋まって
    // 再生用の動画が読めなくなった。2026-10-24 muse-cut）。live=1：サーバーも、描いている1枚と待っている最新の1枚だけにする
    abortExact(); const ctl = S.exactCtl = new AbortController();
    try {
      const r = await api(`/api/frame?t=${t}&live=1&scale=${S.pvScale}`, { cache: 'no-store', signal: ctl.signal });
      if (r.status === 409) return;  // もっと新しい頼みに置きかわった
      if (!r.ok) { const txt = await r.text(); showRenderErr(t, txt); setStatus($L('st.renderError', { err: txt.slice(-300) }), 'bad', { toast: false }); return; }
      const ms = r.headers.get('x-mittler-ms'); const blob = await r.blob();
      if (id !== S.reqId || S.playing || snapFrame(S.t) !== t) return;
      if (S.exactUrl) URL.revokeObjectURL(S.exactUrl);
      S.exactUrl = URL.createObjectURL(blob); S.exactT = t; S.shownVer = ver;
      const img = $('frameImg'); img.src = S.exactUrl; img.hidden = false;
      showSrc(r.headers.get('x-mittler-cache') === 'disk' ? $L('src.cached', { sec: (ms / 1000).toFixed(1) })  // ディスクにためた絵（書き出し・前に描いたコマ。fcache）
        : S.pvScale < 1 ? $L('src.currentScaled', { sec: (ms / 1000).toFixed(1), k: Math.round(1 / S.pvScale) }) : $L('src.current', { sec: (ms / 1000).toFixed(1) }));
      showRenderErr(null);
      if (statusIs('st.renderError', 'st.renderNoConn', 'st.renderer')) setStatus('');  // 消すのは描画のエラーだけ（生成・保存などの知らせは残す）
    } catch (e) { if (e.name !== 'AbortError') setStatus($L('st.renderNoConn', { err: e.message }), 'bad', { toast: false }); }
    finally { if (S.exactCtl === ctl) S.exactCtl = null; }
  }, 80);
}
// 描画のエラーを画面の上の箱に出す（文は選んでコピーできる。次にその時刻が描けたら消える）。t が null なら消す。
// 上のバーの 1 行の知らせは短く切れ、ツールチップは画面を撮ろうとすると消えて、全文を写せなかったため（2026-11-22）。
// 素材が無いとき（FileNotFoundError）は、どのファイルかを見出しに出す。全文は state.json の render_error にも書く（フックが AI に伝える）
S.renderErr = null; S.renderErrClosed = '';
function showRenderErr(t, text) {
  const box = $('renderErr'); if (!box) return;
  if (t == null) { S.renderErr = null; box.hidden = true; $('screen').classList.remove('hasErr'); return; }
  text = String(text || '').trim();
  S.renderErr = { t, text };
  if (S.renderErrClosed === text) return;  // 閉じた同じエラーは、もう出さない（違うエラーなら出す）
  const m = text.match(/FileNotFoundError:.*?['"]([^'"]+)['"]\s*$/m) || text.match(/No such file or directory:\s*['"]([^'"]+)['"]/);
  $('reTitle').textContent = m ? $t('re.missing', { path: m[1].replace(/\\\\/g, '\\') }) : $t('re.title', { t: (+t).toFixed(3) });
  $('reText').textContent = text; $('reText').scrollTop = 1e9;  // 大事なのは最後の行（エラーの種類と理由）なので、いちばん下を見せる
  box.hidden = false; $('screen').classList.add('hasErr');
}
function copyRenderErr() {
  const e = S.renderErr; if (!e) return;
  const txt = $('reTitle').textContent + '\n' + e.text;
  const done = () => { const b = $('reCopy'); b.textContent = $t('re.copied'); setTimeout(() => { b.textContent = $t('re.copy'); }, 1500); };
  const fallback = () => { const sel = getSelection(), rg = document.createRange(); rg.selectNodeContents($('reText')); sel.removeAllRanges(); sel.addRange(rg); try { if (document.execCommand('copy')) done(); } catch (err) { } };
  try { navigator.clipboard.writeText(txt).then(done, fallback); } catch (err) { fallback(); }
}
(() => {  // index.html は、このスクリプトより前に箱を置いている
  const c = $('reCopy'), x = $('reClose');
  if (c) c.onclick = copyRenderErr;
  if (x) x.onclick = () => { if (S.renderErr) S.renderErrClosed = S.renderErr.text; $('renderErr').hidden = true; $('screen').classList.remove('hasErr'); };
})();
function abortExact() { if (S.exactCtl) { try { S.exactCtl.abort(); } catch (e) { } S.exactCtl = null; } }
async function fetchFrame(t) {
  try {
    const r = await api(`/api/frame?t=${t}&q=70&live=1&scale=${S.pvScale}`, { cache: 'no-store' }); if (!r.ok) return;
    const blob = await r.blob(); if (!S.playing) return;
    if (S.exactUrl) URL.revokeObjectURL(S.exactUrl);
    S.exactUrl = URL.createObjectURL(blob); const img = $('frameImg'); img.src = S.exactUrl; img.hidden = false;
  } catch (e) { }
}
// 画面で起きたことを VS Code の記録（サーバーの標準エラー）に残す
function clog(msg) { try { api('/api/log', { method: 'POST', body: String(msg).slice(0, 2000) }); } catch (e) { } }
window.addEventListener('error', e => clog('error: ' + e.message + ' @' + (e.filename || '').split('/').pop() + ':' + e.lineno));
window.addEventListener('unhandledrejection', e => clog('rejection: ' + (e.reason && (e.reason.stack || e.reason.message) || e.reason)));
['error', 'stalled', 'abort'].forEach(ev => $('proxy').addEventListener(ev, () => { const v = $('proxy'); clog(`動画 ${ev}: error=${v.error && v.error.code} ${v.error && v.error.message} rs=${v.readyState} ns=${v.networkState} src=${decodeURIComponent(v.currentSrc).slice(-40)}`); }));
$('proxy').addEventListener('loadedmetadata', () => { const v = $('proxy'); clog(`動画を読めた: ${v.videoWidth}x${v.videoHeight} ${v.duration.toFixed(1)}秒 ${decodeURIComponent(v.currentSrc).slice(-30)}`); });
function invalidateExact() { S.exactT = null; if (!S.playing) requestExact(); }
function proxyName() { return base(S.tl.preview && S.tl.preview.proxy).replace(/\.mp4$/, '') || $t('src.noVideo'); }
// プレビューの左上の札（今の絵がどこから来たか）。s は文字列か $L（言葉を切り替えたら訳し直す）
function showSrc(s) { S.srcMsg = s; $('srcTag').textContent = String(s); }
function setPlaying(on) {
  S.playing = on; $('play').innerHTML = MITTLER_ICON(on ? 'pause' : 'play');
  const v = $('proxy');
  const ownAudio = window.MITTLER_AUDIO && window.MITTLER_AUDIO.has();  // 音のトラックがあれば、書き出し版の音は消して、トラックの音を鳴らす
  v.muted = !!ownAudio;
  if (on) {
    if (window.MITTLER_TAKEVIEW && MITTLER_TAKEVIEW.isOpen()) MITTLER_TAKEVIEW.close();  // テイクの動画を見ていたら閉じる（plan.js）
    clearTimeout(exactTimer); abortExact();  // 止めていたときの絵の頼みは取り消す（再生用の動画に接続を空ける）
    if (S.t >= dur()) S.t = 0;
    // 再生用の動画が使えない（読めない・再生を断られた・止まったまま）ときは、動画なしで時計で進める（絵は描画サーバーの描画を追いかける）
    S.clock = { t0: S.t, at: performance.now() }; S.noProxy = !v.src || !!v.error; S.clockMode = false;
    // ためた絵で流す（editor/cacheplay.js）：再生位置から先がだいたいためてあり、音のトラックがあるとき。書き出し版の動画（直す前の絵かもしれない）より今のタイムライン
    S.cachePlay = !!(ownAudio && window.MITTLER_CACHE && MITTLER_CACHE.canPlay(S.t));
    if (S.cachePlay) {
      S.noProxy = true; S.clockMode = true; v.pause(); $('gradeCv').hidden = true; showSrc($L('src.cachePlay'));
    } else if (!S.noProxy) {
      $('frameImg').hidden = true; $('gradeCv').hidden = true; showSrc(ownAudio ? $L('src.proxyAudio', { name: proxyName() }) : $L('src.proxy', { name: proxyName() }));
      v.currentTime = S.t;
      v.play().catch(err => { clog('動画の再生を断られた: ' + err.name + ' ' + err.message); proxyFail($L('pf.refused', { err: err.name })); });
      // まだ読み込み中（readyState が 2 未満）なら、最大 8 秒待つ（すぐリアルタイム描画に落とさない）
      const waitMs = v.readyState < 2 ? 8000 : 2500, t0 = performance.now();
      if (v.readyState < 2) setStatus($L('st.proxyLoading'), 'busy');
      const watch = () => {
        if (!S.playing || S.noProxy) return;
        if (v.readyState >= 2 && !v.paused) { if (statusIs('st.proxyLoading')) setStatus(''); return; }
        if (performance.now() - t0 > waitMs) { proxyFail($L('pf.stuck', { rs: v.readyState, ns: v.networkState, paused: v.paused })); return; }
        S.proxyWatch = setTimeout(watch, 250);
      };
      S.proxyWatch = setTimeout(watch, 250);
    } else proxyFail(v.error ? $L('pf.unreadable', { code: v.error.code }) : $L('pf.none'));
    if (ownAudio) window.MITTLER_AUDIO.start(S.t);
    requestAnimationFrame(tick);
  }
  else { S.cachePlay = false; if (window.MITTLER_CACHE) MITTLER_CACHE.stopPlay(); clearTimeout(S.proxyWatch); v.pause(); if (window.MITTLER_AUDIO) window.MITTLER_AUDIO.stop(); if (statusIs('st.proxyFail', 'st.proxyLoading')) setStatus(''); S.t = snapFrame(S.noProxy ? S.t : (v.currentTime || S.t)); S.noProxy = false; S.exactT = null; draw(); pumpThumbsUi(); }
}
// 再生用の動画をあきらめて、時計で進める（音はトラックから。絵は1枚ずつ追いかける）
function proxyFail(why) {
  if (!S.playing || S.clockMode) return;
  const v = $('proxy'); S.clock = { t0: S.noProxy ? S.t : (v.currentTime || S.t), at: performance.now() }; S.noProxy = true; S.clockMode = true; v.pause();
  // 再生はできている（描いたコマをその場で出す）ので、失敗の色（赤）・右下の残る知らせにはしない。再生用の動画が無いだけならふつうの知らせ、
  // あるのに読めないときは注意の色。止めたら消す（2026-11-14 使ってみた知らせ：再生のたびに赤い知らせが出て、上のバーに赤いまま残った）
  clog('再生用の動画を使わずに再生: ' + why); setStatus($L('st.proxyFail', { why }), S.tl.preview && S.tl.preview.proxy ? 'warn' : '', { toast: false });
  showSrc($L('src.noProxy'));
}
function tick() {
  if (!S.playing) return;
  const v = $('proxy');
  if (S.noProxy) {  // 時計で進めて、描けたコマを出す（同時に頼むのは1枚だけ）
    S.t = Math.min(dur(), S.clock.t0 + (performance.now() - S.clock.at) / 1000);
    const cached = S.cachePlay && MITTLER_CACHE.show(snapFrame(S.t));  // ためた絵（無いコマは下で描画サーバーに頼む）
    if (!cached && !S.fetching) { S.fetching = true; fetchFrame(snapFrame(S.t)).finally(() => { S.fetching = false; }); }
  } else S.t = v.currentTime;
  if ((!S.noProxy && v.ended) || S.t >= dur()) { setPlaying(false); return; }
  draw(); followPlayhead(); requestAnimationFrame(tick);
}
function followPlayhead() { const wr = $('lanesWrap'), x = S.t * S.pps; if (x < wr.scrollLeft || x > wr.scrollLeft + wr.clientWidth - 40) wr.scrollLeft = Math.max(0, x - 80); }

// ---------- プレビューの大きさ ----------
function fitScreen() {
  if (!S.tl) return; const st = $('stage'), sc = $('screen'); const W = S.tl.width || 1920, H = S.tl.height || 1080;
  const cs = getComputedStyle(st), px = k => parseFloat(cs[k]) || 0;  // 余白（書き込み中は下に道具の帯のぶん空ける。annotate.js）
  const tp = $('transport'), below = tp ? tp.offsetHeight + 6 : 0;  // 下の再生の操作のぶん
  const k = Math.min((st.clientWidth - px('paddingLeft') - px('paddingRight')) / W, (st.clientHeight - px('paddingTop') - px('paddingBottom') - below) / H); sc.style.width = Math.floor(W * k) + 'px'; sc.style.height = Math.floor(H * k) + 'px';
}

// ---------- タイムライン ----------
function findClip(id) { for (const tr of S.tl.tracks || []) for (const c of tr.clips || []) if (c.id === id) return { clip: c, track: tr }; return null; }
const fxMeta = c => (S.fx[c.effect] || {}).meta || {};
// エフェクトの名前・説明の、今の言葉のもの（エフェクトの META：'label'・'label_en'、または 'label': {'ja': …, 'en': …}。
// 英語が無いもの（作品専用のエフェクト・今ある作品の effects/）は、ある言葉（日本語）で出す。docs/エフェクトの書き方.md）
function pickLang(v, en) {
  if (v && typeof v === 'object' && !Array.isArray(v)) return v[MITTLER_I18N.lang] || v.en || v.ja || '';
  return MITTLER_I18N.lang === 'en' && en ? en : v;
}
const fxLabel = (meta, fallback) => pickLang(meta && meta.label, meta && meta.label_en) || fallback || '';
const fxDoc = fx => pickLang(fx && fx.doc, fx && fx.doc_en) || '';
// クリップの窓（どこをつかめるか）・動かす・伸び縮みの計算は editor/ops.js（API の split・ripple・gaps・stretch と同じ）
const win = c => OPS.clipWin(c, fxMeta);
const CE = () => OPS.clipEdit(S.tl, opsEnv());
// 素材の根（タイムラインの root）からのパスを URL に
const rootUrl = p => '/project/' + (S.tl.root && S.tl.root !== '.' ? S.tl.root.replace(/\/$/, '') + '/' : '') + String(p).split('/').map(encodeURIComponent).join('/');
const charOf = id => ((S.chars || {}).characters || []).find(c => c.id === id);
function clipLabel(c) {
  if (c.type === 'effect') { const l = c.label || fxLabel(fxMeta(c), c.effect); return (c.cut != null ? c.cut + $t('sep.bar') : '') + l; }
  if (c.type === 'script') { const p = c.params || {}; return p.text ? $t('clip.scriptText', { name: c.script, text: p.text }) : c.script; }
  if (c.type === 'keyframes') { const tk = c.activeTake && (c.takes || []).find(k => k.id === c.activeTake); return (c.label || $t('clip.keyframes')) + (tk ? ' ・' + tk.id : ''); }
  if (c.type === 'tts') { const ch = charOf(c.character), who = ch ? ch.name : c.character || '?', txt = c.label || c.text || ''; return c.takes && c.takes.length ? who + $t('sep.who') + txt : $t('clip.ttsPending', { who, text: txt }); }
  if (c.type === 'subtitle') return c.text || $t('clip.subtitle');
  if (c.type === 'plan') return c.label || $t('clip.plan');
  return c.label || base(c.src);
}
// editor/ops.js（ボタンと API で同じ書きかえ）に渡すもの：新しい id・作品の中身に書く名前（今の画面の言葉）・知らせの文（$L）・クリップの名前・
// per_cut のエフェクトか（エフェクトの META）・素材の長さ（アセットの一覧・波形から）・エフェクトの META が届いたか
function opsEnv() {
  return { uid: p => p + '_' + Math.random().toString(36).slice(2, 8), t: $t, L: $L, label: c => clipLabel(c), name: c => $L('cm.q', { x: clipLabel(c) }),
    isPerCut: c => !!(fxMeta(c).window || {}).per_cut, fxMeta, srcDur: c => (window.MITTLER_CUT && MITTLER_CUT.srcDur) ? MITTLER_CUT.srcDur(c) : null, fxReady: !!S.fxReady };
}
// 映像クリップのスタートフレーム（小さな絵）：URL にクリップの中身の印を付けて、ブラウザに覚えてもらう。読み込むのは同時に2つまで、再生中は読まない
// （いっぺんに頼むと、ブラウザの同時接続（6本）が埋まって再生用の動画が読めなくなり、リアルタイム描画に落ちていた。2026-10-21）
const THUMB_OK = new Set(); const thumbQ = []; let thumbBusy = 0;
function thumbUrl(c) {
  const sig = JSON.stringify([c.src, c.in || 0, c.speed || 1, c.warp || null, c.land || 0, c.land ? c.dur : 0]);
  let h = 0; for (let i = 0; i < sig.length; i++) h = (h * 31 + sig.charCodeAt(i)) | 0;
  return `/api/thumb?clip=${encodeURIComponent(c.id)}&v=${(h >>> 0).toString(36)}${S.assetVer ? '&a=' + S.assetVer : ''}&token=${TOKEN}`;  // ffmpeg を動かす GET なのでトークン（img はヘッダーを付けられない）
}
function loadThumbs() {
  for (const el of document.querySelectorAll('#laneList .clip.thumb[data-thumb]')) {
    const u = el.dataset.thumb;
    if (THUMB_OK.has(u)) { el.style.backgroundImage = `url('${u}')`; continue; }
    if (!thumbQ.includes(u)) thumbQ.push(u);
  }
  pumpThumbsUi();
}
function pumpThumbsUi() {
  while (thumbBusy < 2 && thumbQ.length && !S.playing) {
    const u = thumbQ.shift(); if (THUMB_OK.has(u)) continue; thumbBusy++;
    const im = new Image();
    im.onload = () => { THUMB_OK.add(u); thumbBusy--; document.querySelectorAll(`#laneList .clip.thumb[data-thumb="${CSS.escape(u)}"]`).forEach(el => { el.style.backgroundImage = `url('${u}')`; }); pumpThumbsUi(); };
    im.onerror = () => { thumbBusy--; pumpThumbsUi(); };
    im.src = u;
  }
}
function clipHTML(c) {
  const l = c.start * S.pps, w = Math.max(3, c.dur * S.pps); let inner = '', cls = 'clip ' + c.type, bg = '', extra = '';
  if (c.type === 'effect') cls += ' fx-' + c.effect;
  if (c.type === 'image') bg = `background-image:url('${rootUrl(c.src)}')`;
  if (c.type === 'tts') {
    const ch = charOf(c.character); if (ch && ch.color) bg = `border-left:4px solid ${ch.color}`; if (!(c.takes || []).length) cls += ' pending';
    const ov = S.ttsOverlap && S.ttsOverlap.get(c.id), o = ov && findClip(ov);  // 同じトラックのセリフと重なっている（editor/ops.js の ttsOverlaps）
    if (o) { cls += ' overlap'; inner += `<span class="ovl" title="${esc($t('tts.overlap', { other: clipLabel(o.clip) }))}">${MITTLER_ICON('triangle-alert')}</span>`; }
  }
  if ((c.type === 'audio' || c.type === 'tts') && window.MITTLER_CUT) inner += MITTLER_CUT.audioLane(c);  // 波形・フェードのつまみ（cutedit.js）
  if (c.type === 'audio' && c.music && window.MITTLER_MUSIC) inner += MITTLER_MUSIC.badge(c);  // 🎵 Suno の曲：未生成・テイク n・採用待ち・採用したテイク（music.js）
  if (c.link) { cls += ' linked'; inner += `<span class="lnk" title="${esc($t('clip.linkTip'))}">${MITTLER_ICON('link')}</span>`; }
  if (c.grade) inner += `<span class="cgb${c.link ? ' l2' : ''}" title="${esc($t('clip.gradeTip', { list: GK.filter(([k]) => c.grade[k] != null).map(([k, n]) => n + ' ' + c.grade[k]).join($t('sep.list')) }))}">${MITTLER_ICON('palette')}</span>`;
  if (c.type === 'video') { const u = thumbUrl(c); bg = THUMB_OK.has(u) ? `background-image:url('${u}')` : ''; cls += ' thumb'; extra = ` data-thumb="${esc(u)}"`; if (window.MITTLER_WARP) inner += MITTLER_WARP.lane(c); }  // スタートフレーム（loadThumbs）・速さの線（warp.js）
  if (c.type === 'keyframes') {
    const done = !!c.activeTake; if (done) cls += ' done';
    if (c.startFrame) inner += `<div class="kf a" style="background-image:url('/project/${encodeURI(c.startFrame)}')"></div>`;
    if (c.endFrame) inner += `<div class="kf b" style="background-image:url('/project/${encodeURI(c.endFrame)}')"></div>`;
    inner += `<span class="badge">${done ? $t('clip.takesN', { n: (c.takes || []).length }) : $t('clip.notGenerated')}</span>`;
  }
  if (c.type === 'plan') {  // 動画化予定：左にスタート・右にエンドの絵、状態のしるし
    const a = (c.start_frame || {}).src, b = (c.end_frame || {}).src, v = c.video || {};
    if (a) inner += `<div class="kf a" style="background-image:url('${rootUrl(a)}')"></div>`;
    if (b) inner += `<div class="kf b" style="background-image:url('${rootUrl(b)}')"></div>`;
    const st = $t(v.adopted ? 'plan.badge.adopted' : (v.takes || []).length ? 'plan.badge.videos' : a && b ? 'plan.badge.both' : a ? 'plan.badge.start' : b ? 'plan.badge.end' : 'plan.badge.none', { n: (v.takes || []).length });
    inner += `<span class="badge">${st}</span>`; if (v.adopted) cls += ' done';
  }
  const wn = win(c); if (wn.start || wn.end || wn.clip) inner += '<i class="grip l"></i><i class="grip r"></i>';
  if (c.disabled) cls += ' off'; if (c.id === S.sel) cls += ' sel'; else if (S.multi && S.multi.has(c.id)) cls += ' msel';
  return `<div class="${cls}" data-id="${esc(c.id)}"${extra} style="left:${l}px;width:${w}px;${bg}" title="${esc(clipLabel(c))}"><span class="lb">${esc(clipLabel(c))}</span>${inner}</div>`;
}
function metaHTML(m) {
  if (m.kind === 'beats') {
    if (Array.isArray(m.items)) return m.items.map(b => `<div class="beat${b[1] ? ' down' : ''}" style="left:${b[0] * S.pps}px"></div>`).join('');
    const times = m.times || []; const per = 60 / (S.tl.bpm || 120), db = S.tl.downbeat || 0;
    return times.map(t => `<div class="beat${Math.abs(((t - db) / per) % 4) < .05 || Math.abs(((t - db) / per) % 4 - 4) < .05 ? ' down' : ''}" style="left:${t * S.pps}px"></div>`).join('');
  }
  const isCut = m.kind === 'cuts', CM = window.MITTLER_CUTMETA;
  const txt = it => isCut ? $t('cut.label', { label: it.label }) + (it.togaki ? '　' + it.togaki : it.lyric ? '　' + it.lyric : '') : m.kind === 'sections' ? $t('meta.strength', { v: it.value }) : (it.who ? it.who + $t('sep.who') : '') + (it.text || '');
  const ed = !META_FIXED.has(m.kind), ms = S.metaSel && S.metaSel.m === m.id ? S.metaSel.it : null;
  const tip = $t(isCut ? 'meta.cutItemTip' : 'meta.itemTip');
  const items = m.items || [];
  if (!items.length && (isCut || m.kind === 'notes')) return `<div class="mhint">${$t(isCut ? 'meta.emptyCuts' : 'meta.emptyNotes')}</div>`;
  return items.map((it, i) => {
    const w = isCut && CM ? CM.mismatch(it) : null;
    return `<div class="item ${esc(m.kind)}${ed ? ' ed' : ''}${it === ms ? ' sel' : ''}${w ? ' warn' : ''}" data-meta="${esc(m.id)}" data-i="${i}" style="left:${it.start * S.pps}px;width:${Math.max(3, (it.end - it.start) * S.pps)}px" title="${esc(txt(it))}${w ? '\n' + esc(CM.warnText(it, w)) : ''}${ed ? tip : ''}">${ed ? '<i class="grip l"></i><i class="grip r"></i>' : ''}${w ? MITTLER_ICON('triangle-alert') + ' ' : ''}${esc(txt(it))}</div>`;
  }).join('');
}
// トラック・メタデータの種類の名前（$L：使うときに今の言葉の文になる。KIND[x] || x の形はそのまま使える）
const KIND = Object.fromEntries(['plan', 'media', 'video', 'script', 'effect', 'tts', 'subtitle', 'audio', 'beats', 'lyrics', 'dialogue', 'notes', 'detect', 'cuts', 'sections', 'song_sections'].map(k => [k, $L('kind.' + k)]));
// レイヤーの種類の印（トラック名の前に付ける。種類の名前はマウスを乗せると出る）
// トラックの頭の印（Lucide のアイコン。色はトラックの種類の色 --c-*：editor.css の .head .tk）
const TRACK_ICON = { plan: 'clapperboard', effect: 'sparkles', video: 'film', media: 'film', script: 'scroll-text', tts: 'speech', subtitle: 'captions', audio: 'volume-2' };
const trackIcon = (kind, tr) => `<span class="tk k-${esc(kind || '')}">${MITTLER_ICON((kind === 'audio' && tr && tr.role === 'bgm') ? 'music' : (kind === 'audio' && tr && tr.role === 'reference') ? 'cassette-tape' : TRACK_ICON[kind] || 'square')}</span>`;
function buildTimeline() {
  if (S.multi) for (const id of [...S.multi]) if (!findClip(id)) S.multi.delete(id);
  if (S.metaSel && !(S.tl.meta || []).some(m => m.id === S.metaSel.m && (m.items || []).includes(S.metaSel.it))) S.metaSel = null;
  const tl = S.tl, totalW = (dur() + padSec()) * S.pps + 24; let heads = '', lanes = '';  // 右の余白は全体表示（fitPps）と同じ 24px＋動画の外
  S.ttsOverlap = OPS.ttsOverlaps(tl);
  // シャイ（After Effects の shy）：🫣 の印（tr.shy / m.shy、タイムラインに保存）を付けたトラックを、上の 🫣 で表示から隠す（表示だけ。描画・書き出しは変わらない）
  const shyBtn = b => `<button class="shy${b.on ? ' on' : ''}" ${b.attr} title="${esc($t(b.on ? 'tr.shyOn' : 'tr.shyOff'))}">${b.on ? MITTLER_ICON('ghost') : '·'}</button>`;
  let nShy = 0;
  for (const tr of tl.tracks || []) {
    if (tr.shy) nShy++;
    if (tr.shy && S.hideShy) continue;
    // トラックを残したまま有効・無効：音（tts・audio）はミュート（muted）、絵（映像・エフェクト・字幕…）は非表示（hidden＝描かない・書き出さない）
    const isAu = tr.kind === 'tts' || tr.kind === 'audio', off = isAu ? !!(tr.muted || tr.hidden) : !!tr.hidden;
    const tog = isAu
      ? `<button class="mute${off ? ' on' : ''}" data-track="${esc(tr.id)}" title="${esc($t(off ? 'tr.muted' : 'tr.mute'))}">${MITTLER_ICON(off ? 'volume-x' : 'volume-1')}</button>`
      : `<button class="vis${off ? ' on' : ''}" data-track="${esc(tr.id)}" title="${esc($t(off ? 'tr.hidden' : 'tr.visible'))}">${MITTLER_ICON(off ? 'eye-off' : 'eye')}</button>`;
    heads += `<div class="head${S.selTrack === tr.id ? ' selt' : ''}${off ? ' off' : ''}" data-track="${esc(tr.id)}" title="${esc(KIND[tr.kind] || tr.kind || '')}${off ? esc($t(isAu ? 'tr.mutedTag' : 'tr.hiddenTag')) : ''}"><span class="nm">${trackIcon(tr.kind, tr)} ${esc(tr.name || tr.id)}</span><span class="hb">${shyBtn({ on: tr.shy, attr: `data-track="${esc(tr.id)}"` })}${tog}</span></div>`;
    lanes += `<div class="lane${off ? ' off' : ''}" data-track="${esc(tr.id)}" style="width:${totalW}px">${(tr.clips || []).map(clipHTML).join('')}</div>`;
  }
  for (const m of tl.meta || []) {
    if (m.kind === 'pulse_grid') continue;
    if (m.shy) nShy++;
    if (m.shy && S.hideShy) continue;
    // ＋：再生位置に足す（カットの段は再生位置で分ける。無ければ最初のカット）。拍は文字ではないので無し
    const add = !META_SKIP.has(m.kind) && Array.isArray(m.items) ? `<button class="madd" data-meta="${esc(m.id)}" title="${esc(m.kind === 'cuts' ? $t(m.items.length ? 'meta.addCutSplit' : 'meta.addCutFirst') : $t('meta.addItem', { name: m.name || KIND[m.kind] || m.kind }))}">＋</button>` : '';
    heads += `<div class="head meta" data-meta="${esc(m.id)}" title="${esc($t('meta.headTip', { kind: KIND[m.kind] || m.kind }))}"><span class="nm"><span class="tk">${MITTLER_ICON('tags')}</span> ${esc(m.name || KIND[m.kind] || m.kind)}</span><span class="hb">${add}${shyBtn({ on: m.shy, attr: `data-meta="${esc(m.id)}"` })}</span></div>`;
    lanes += `<div class="lane meta" data-meta="${esc(m.id)}" style="width:${totalW}px">${metaHTML(m)}</div>`;
  }
  // カット・ト書きの段が無い作品：段を作るボタン（2026-10-31。ひな形 templates/project と同じ m_cuts・m_notes）
  const noCuts = !(tl.meta || []).some(m => m.kind === 'cuts'), noNotes = !(tl.meta || []).some(m => m.kind === 'notes');
  if (noCuts || noNotes) {
    heads += `<div class="head meta addmeta">${noCuts ? `<button data-addmeta="cuts" title="${esc($t('meta.addCutsLane.tip'))}">${esc($t('meta.addCutsLane'))}</button>` : ''}${noNotes ? `<button data-addmeta="notes" title="${esc($t('meta.addNotesLane.tip'))}">${esc($t('meta.addNotesLane'))}</button>` : ''}</div>`;
    lanes += `<div class="lane meta addmeta" style="width:${totalW}px"></div>`;
  }
  $('headList').innerHTML = heads; $('laneList').innerHTML = lanes; $('lanes').style.width = totalW + 'px'; loadThumbs();
  if (window.MITTLER_FOLLOW) MITTLER_FOLLOW.paint();  // AI を追う：光らせている印を、作り直したタイムラインにも
  const sb = $('shyBtn'); sb.classList.toggle('on', !!S.hideShy); sb.innerHTML = MITTLER_ICO('ghost', $t('bar.shy'), true, nShy ? String(nShy) : '');
  sb.title = $t(S.hideShy ? 'bar.shy.hiding' : 'bar.shy.hide', { n: nShy });
  buildRuler(totalW); $('playhead').style.left = (S.t * S.pps) + 'px';
  const ez = $('endZone'); if (ez) { ez.hidden = false; ez.style.left = (dur() * S.pps) + 'px'; ez.style.width = (padSec() * S.pps + 24) + 'px'; }
  if (window.refreshDurBtn) refreshDurBtn();
  const wh = `${tl.width || 1920}x${tl.height || 1080}`; if (S.lastWH !== wh) { S.lastWH = wh; fitScreen(); if (window.refreshSizeBtn) refreshSizeBtn(); }
  if (window.MITTLER_CUT && MITTLER_CUT.refresh) MITTLER_CUT.refresh();  // 道具のバーの数（最新の動画を全部採用 など）
}
function buildRuler(totalW) {
  const steps = [.1, .25, .5, 1, 2, 5, 10, 15, 30, 60]; const major = steps.find(s => s * S.pps >= 70) || 60; const minor = major / (major >= 1 && major % 5 === 0 ? 5 : 2);
  let h = ''; for (let t = 0; t <= dur() + padSec() + 1e-9; t += minor) {
    const isMaj = Math.abs(t / major - Math.round(t / major)) < 1e-6;
    h += isMaj ? `<div class="tick" style="left:${t * S.pps}px">${fmt(t).replace(/\.?0+$/, '').replace(/:(\d)$/, ':0$1')}</div>` : `<div class="tick minor" style="left:${t * S.pps}px"></div>`;
  }
  $('ruler').innerHTML = h; $('ruler').style.width = totalW + 'px';
  if (window.MITTLER_CACHE) MITTLER_CACHE.drawBar();  // ためた絵の印（editor/cacheplay.js）
}
// リンク（c.link が同じクリップ。動画とその音など）：🔗 連動がオンなら一緒に選ぶ・動かす・切る・消す
S.linkOn = (() => { try { return localStorage.getItem('cc.linkOn') !== '0'; } catch (e) { return true; } })();
const linkGroup = id => CE().linkGroup(id, S.linkOn);  // editor/ops.js（API の --no-link でなければ連動オン）
const selIds = () => [...new Set([...(S.multi || []), ...(S.sel ? [S.sel] : [])])].filter(id => findClip(id));
function markSel() {
  document.querySelectorAll('#laneList .clip').forEach(el => { const id = el.dataset.id; el.classList.toggle('sel', id === S.sel); el.classList.toggle('msel', id !== S.sel && !!(S.multi && S.multi.has(id))); });
  if (window.MITTLER_CUT) MITTLER_CUT.refresh();
}
function select(id, add) {
  if (add && id) {
    S.multi = S.multi || new Set(); const g = linkGroup(id);
    if (S.multi.has(id)) { g.forEach(x => S.multi.delete(x)); if (S.sel && !S.multi.has(S.sel)) S.sel = [...S.multi][0] || null; }
    else { g.forEach(x => S.multi.add(x)); S.sel = id; }
  } else { S.sel = id; S.multi = new Set(id ? linkGroup(id) : []); }
  if (S.sel) S.selTrack = null;
  if (S.metaSel) { S.metaSel = null; document.querySelectorAll('#laneList .item.sel').forEach(el => el.classList.remove('sel')); }
  markSel(); showSel();
}

// ---------- 編集（取り消し・保存） ----------
// クリップの終わりのいちばん後ろ（音のクリップ＝音楽・効果音は入れない：BGM は動画より長いことが多いので）
const contentEnd = withAudio => OPS.contentEnd(S.tl, withAudio);
function change(fn, opts = {}) {
  const before = JSON.stringify(S.tl);
  fn();
  // コマに乗っている時刻は n / fps で書く（この操作で変わった値だけ）。動画の外（最後より後ろ）にクリップを置いた・動かした・伸ばした：動画の長さをそこまで伸ばす（同じ1回の取り消しで戻る）
  const extended = OPS.finish(S.tl, before, opts);
  if (JSON.stringify(S.tl) === before) return;  // 何も変わらない（同じ値の入れ直しなど）：取り消しの記録も保存もしない
  S.edits++;
  S.undo.push(before); if (S.undo.length > 200) S.undo.shift(); S.redo = [];
  buildTimeline(); if (!opts.keepForm) showSel(); scheduleSave();
  if (window.MITTLER_ASSETS && window.MITTLER_ASSETS.onEdit) window.MITTLER_ASSETS.onEdit();
  if (extended) setStatus($L('st.durExtended', { d: fmt(dur()) }), 'ok');
}
// ⏱ 動画の長さ：秒数で決める・足す・最後のクリップに合わせる（縮めると、外にはみ出たクリップは書き出しに入らない）
function refreshDurBtn() {
  const b = $('durBtn'); if (!b || !S.tl) return; b.hidden = false;
  b.innerHTML = `${MITTLER_ICON('timer')} ${esc(fmt(dur()).replace(/\.?0+$/, ''))}`;
  if (!$('durMenu').hidden && document.activeElement && document.activeElement.id === 'durIn') return;  // 数字を打っているあいだは作り直さない（打った数字が消えないように）
  const ce = contentEnd(false), ca = contentEnd(true);
  $('durMenu').innerHTML = `<div class="dm"><label>${$t('dur.label')}</label><input id="durIn" type="number" step="${1 / fps()}" min="${1 / fps()}" value="${+dur().toFixed(3)}"><button data-d="set">${$t('dur.set')}</button></div>
    <div class="dm"><button data-d="+5">${$t('dur.plus', { n: 5 })}</button><button data-d="+10">${$t('dur.plus', { n: 10 })}</button><button data-d="+30">${$t('dur.plus', { n: 30 })}</button></div>
    <div class="dm"><button data-d="fit" ${ce > 0 ? '' : 'disabled'}>${$t('dur.fit', { t: fmt(ce) })}</button></div>
    ${ca > ce + 1e-6 ? `<div class="dm"><button data-d="fitAll">${$t('dur.fitAll', { t: fmt(ca) })}</button></div>` : ''}
    <div class="tdim">${$t('dur.note')}</div>`;
}
function setDuration(sec) {
  const v = +(Math.round(Math.max(1 / fps(), sec) * fps()) / fps()).toFixed(6); if (Math.abs(v - dur()) < 1e-9) return;
  change(() => { S.tl.duration = v; }, { noExtend: true });
  if (S.t > dur()) seek(dur());
  setStatus($L('st.durSet', { d: fmt(dur()) }), 'ok');
}
$('durBtn').addEventListener('click', e => { e.stopPropagation(); refreshDurBtn(); $('durMenu').hidden = !$('durMenu').hidden; });
$('durMenu').addEventListener('click', e => {
  const b = e.target.closest('[data-d]'); if (!b) return; const k = b.dataset.d;
  if (k === 'set') { const v = parseFloat($('durIn').value); if (isFinite(v) && v > 0) setDuration(v); }
  else if (k === 'fit') setDuration(contentEnd(false));
  else if (k === 'fitAll') setDuration(contentEnd(true));
  else setDuration(dur() + parseFloat(k));
  refreshDurBtn();
});
$('durMenu').addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'durIn') { const v = parseFloat(e.target.value); if (isFinite(v) && v > 0) setDuration(v); refreshDurBtn(); } });
document.addEventListener('mousedown', e => { if (!e.target.closest('.durWrap')) $('durMenu').hidden = true; });
// 取り消しの記録の1つ：ふつうは直す前のタイムライン（JSON の文字列）。外（Claude Code など）の直しを読み直したときは {tl: 読み直す前, ext: true}（listen）。
// 外の直しも取り消しの 1 回の単位にする：前は記録に入れていなかったので、外の直しのあとの Ctrl+Z が「自分の最後の直しの前」まで戻り、
// 外の直しも一緒に黙って消して保存していた（2026-11-12）。今は 1 回目の Ctrl+Z が外の直しだけを戻し（知らせる）、2 回目が自分の直しを戻す
function undo() {
  const prev = S.undo.pop(); if (!prev) return;
  const ext = typeof prev !== 'string', cur = JSON.stringify(S.tl);
  (S.redo = S.redo || []).push(ext ? { tl: cur, ext: true } : cur);
  S.edits++; S.tl = JSON.parse(ext ? prev.tl : prev); if (S.sel && !findClip(S.sel)) S.sel = null; buildTimeline(); showSel(); buildGradePanel(); buildMetaPanel(); scheduleSave();
  if (ext) {
    setStatus($L('st.extUndo'), 'ok');
    // 右下にも出す（自分の直しではなく、外の直しが戻ったことを見落とさないように。上の 1 行は次の知らせで消える）
    if (window.MITTLER_NOTIFY) MITTLER_NOTIFY($L('toast.extUndo'), 'info', { key: 'extundo', ms: 10000 });
  }
}
function redo() {
  const next = (S.redo || []).pop(); if (!next) return;
  const ext = typeof next !== 'string', cur = JSON.stringify(S.tl);
  S.undo.push(ext ? { tl: cur, ext: true } : cur);
  S.edits++; S.tl = JSON.parse(ext ? next.tl : next); if (S.sel && !findClip(S.sel)) S.sel = null; buildTimeline(); showSel(); buildGradePanel(); buildMetaPanel(); scheduleSave();
  if (ext) setStatus($L('st.extRedo'), 'ok');
}
// 保存に失敗したとき（サーバーが 500 を返した・通信が切れた）：「保存しました」と出さない・保存できたことにしない（S.lastSaved を入れない）・
// S.saving を必ず外す（外れないと、そのあと外で直されたタイムラインを読み直さなくなる）・少し待ってやり直す（2026-11-12）。
// 保存できるまでは「保存していない直しがある」の扱い（S.saveTimer が立っている）なので、外の直しは読み直さない。やり直しが通れば、画面の中身がファイルになる
function scheduleSave(delay = 350) {
  clearTimeout(S.saveTimer);
  S.saveTimer = setTimeout(async () => {
    S.saveTimer = null; const body = JSON.stringify(S.tl);
    let why = '';
    S.saving = api('/api/timeline', { method: 'PUT', body, headers: { 'Content-Type': 'application/json' } })
      .then(async r => { if (!r.ok) why = `HTTP ${r.status} ${(await r.text().catch(() => '')).slice(0, 200)}`; }, e => { why = $L('save.noConn', { err: e.message || e }); });
    await S.saving; S.saving = null;
    if (why) {
      S.saveFails = (S.saveFails || 0) + 1;
      const wait = Math.min(15, 2 * S.saveFails);
      setStatus($L('st.saveFailed', { why, wait, n: S.saveFails }), 'bad', { toast: false }); clog('保存できなかった: ' + why);
      // 右下にも出す（上の 1 行は、次の知らせですぐ上書きされて埋もれる）。保存が通るまで消えない・同じ知らせを置きかえる
      if (window.MITTLER_NOTIFY) MITTLER_NOTIFY($L('toast.saveFailed', { why, wait, n: S.saveFails }), 'bad', { key: 'save', action: { label: $L('toast.retryNow'), run: () => scheduleSave(0) } });
      if (!S.saveTimer) scheduleSave(wait * 1000);  // 待っているあいだにまた直されていれば、その保存がやり直しになる
      return;
    }
    if (S.saveFails && window.MITTLER_NOTIFY) { MITTLER_NOTIFY.close('save'); MITTLER_NOTIFY($L('toast.saveRecovered'), 'ok', { key: 'save-ok', ms: 6000 }); }
    S.lastSaved = body; S.saveFails = 0;
    if (S.saveTimer) return;  // 待っているあいだにまた直された：次の保存のあとで描く
    S.ver++; if (S.status.level !== 'act' && !statusIs('st.extUndo', 'st.extRedo')) setStatus($L('st.saved'), 'ok'); invalidateExact();  // 押せる知らせ（▶ ここを押すと…。cutmeta.js）と、外の直しを取り消した知らせは消さない  // 保存が終わってから描き直す（描画サーバーは中身が変わったタイムラインを読み直す）
  }, delay);
}
// 今の直しがタイムラインのファイルに保存されてから fn を呼ぶ（届いたもの（🎬 のテイク・🔬 の解析・🎵 の曲）に「取り込んだ」の印を付けるのは保存のあと。
// 保存の前（約 0.35 秒）に画面を閉じると、取り込みは消えるのに印だけ付いて、二度と取り込まれなかった。2026-10-30）。60 秒たっても保存されなければ印を付けない（次に開いたとき取り込み直す）
function afterSaved(fn, tries = 0) {
  if (S.saveTimer || S.saving || S.lastSaved !== JSON.stringify(S.tl)) { if (tries < 600) setTimeout(() => afterSaved(fn, tries + 1), 100); return; }
  fn();
}
// 動かす（エフェクトの時刻のパラメータ time_params も同じだけ・コマに乗っていればコマの時刻そのものに・カットに付いていればそのときのカットのラベルに）・
// 伸び縮み（音・動画は頭を切ると素材の何秒目からもずれる・音ハメの点も）：editor/ops.js の clipEdit（API と同じ）
const moveClip = (c, dt) => CE().moveClip(c, dt);
const trimClip = (c, side, dt) => CE().trimClip(c, side, dt);
// 数の欄から：開始（0 より前にしない・コマにそろえる）と長さ（1 コマより短くしない・コマにそろえる）。欄には 3 桁で出ているので、打った数をそのまま書くと
// コマに乗らない値になる（0.067 など）。0・負の数の長さのクリップも作れてしまっていた（つかめない。音は書き出しで落ちる）
function setClipStart(c, v) { if (isFinite(v)) moveClip(c, Math.max(0, snapFrame(v)) - c.start); }
function setClipDur(c, v) { if (isFinite(v)) trimClip(c, 'r', Math.max(1 / fps(), snapFrame(v)) - c.dur); }

// ---------- 右の欄：選んだクリップ ----------
function isColor(key, v, spec) {
  return Array.isArray(v) && v.length === 3 && v.every(x => Number.isInteger(x) && x >= 0 && x <= 255) && (spec.type === 'color' || /^c\d?$|color|fill|line|shadow|band|inner|tint/.test(key));
}
const hex = v => '#' + v.map(x => x.toString(16).padStart(2, '0')).join('');
const unhex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
// 行の並び（["…", "…"]。フキダシの縦書きの列など）：1行に1つのテキストで直す
const isLines = (v, spec) => spec.type === 'lines' || (spec.type !== 'json' && Array.isArray(v) && v.length > 0 && v.every(x => typeof x === 'string'));
// 書体（root からの相対の .ttf／.otf）：アセットの書体から選ぶ
const isFont = (key, v, spec) => spec.type === 'font' || (typeof v === 'string' && /(^|_)font$/.test(key) && /\.(ttf|otf|ttc)$/i.test(v));
function field(key, v, spec, onSet) {
  const id = 'f_' + key.replace(/\W/g, '_');
  let h;
  if (isLines(v, spec)) h = `<textarea id="${id}" class="lines" rows="${Math.max(2, (v || []).length + 1)}" spellcheck="false" placeholder="${esc($t('field.onePerLine'))}">${esc((v || []).join('\n'))}</textarea>`;
  else if (isFont(key, v, spec)) {
    const fonts = [...new Set([v, ...(((S.assets || {}).fonts) || []).map(x => x.path)])].filter(Boolean);
    h = `<select id="${id}">${fonts.map(p => `<option value="${esc(p)}" ${p === v ? 'selected' : ''}>${esc(p.split('/').pop())}</option>`).join('')}</select>`;
  } else if (typeof v === 'number') h = `<input id="${id}" type="number" step="${spec.step || (Number.isInteger(v) ? 1 : 0.01)}" ${spec.min != null ? `min="${spec.min}"` : ''} ${spec.max != null ? `max="${spec.max}"` : ''} value="${+v.toFixed(6)}">`;
  else if (typeof v === 'boolean') h = `<input id="${id}" type="checkbox" ${v ? 'checked' : ''}>`;
  else if (typeof v === 'string') h = spec.choices ? `<select id="${id}">${spec.choices.map(c => `<option ${c === v ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>` : `<input id="${id}" type="text" value="${esc(v)}">`;
  else if (isColor(key, v, spec)) h = `<input id="${id}" type="color" value="${hex(v)}">`;
  else h = `<textarea id="${id}">${esc(JSON.stringify(v))}</textarea>`;
  return {
    html: `<label title="${esc(key)}">${esc(key)}</label>${h}`, bind() {
      const el = $(id); if (!el) return;
      el.addEventListener('change', () => {
        let nv;
        if (isLines(v, spec)) { nv = el.value.replace(/\r/g, '').split('\n'); while (nv.length && nv[nv.length - 1] === '') nv.pop(); }
        else if (isFont(key, v, spec)) nv = el.value;
        else if (typeof v === 'number') nv = parseFloat(el.value);
        else if (typeof v === 'boolean') nv = el.checked;
        else if (typeof v === 'string') nv = el.value;
        else if (isColor(key, v, spec)) nv = unhex(el.value);
        else { try { nv = JSON.parse(el.value); el.classList.remove('bad'); } catch (e) { el.classList.add('bad'); return; } }
        if (typeof nv === 'number' && !isFinite(nv)) return;
        onSet(nv);
      });
    }
  };
}
// 外から変わったときの右の欄の描き直し：入力中（右の欄にフォーカス）なら、打っている文字を消さないよう、欄から抜けたときに描き直す
function showSelSafe() {
  const a = document.activeElement;
  if (a && $('sel').contains(a) && /^(TEXTAREA|INPUT|SELECT)$/.test(a.tagName)) { S.pendingSel = true; return; }
  showSel();
}
// 「開始」「長さ」の数の欄の横に、コマ番号（f15）・コマ数（75 コマ）を出す（欄は秒で 3 桁なので、どのコマかが分かりにくかった）。
// 欄の作りは種類ごとに別々（media.js・plan.js・warp.js・上の field）なので、右の欄が作り直されるたびに、ここでまとめて足す
function frameHints() {
  if (!S.tl) return;
  for (const inp of $('sel').querySelectorAll('input[data-k="start"],input[data-k="dur"],#f_start,#f_dur')) {
    if (inp.dataset.fh) continue; inp.dataset.fh = '1';
    const isDur = inp.dataset.k === 'dur' || inp.id === 'f_dur';
    const wrap = document.createElement('span'); wrap.className = 'fnum'; inp.before(wrap); wrap.appendChild(inp);
    const h = document.createElement('span'); h.className = 'fhint'; wrap.appendChild(h);
    const up = () => {
      const v = parseFloat(inp.value), n = Math.round(v * fps());
      h.textContent = isFinite(v) ? (isDur ? $t('fh.frames', { n }) : `f${n}`) : '';
      h.title = $t(isDur ? 'fh.durTip' : 'fh.startTip', { fps: fps() });
    };
    inp.addEventListener('input', up); inp.addEventListener('change', () => setTimeout(up, 0)); up();
  }
}
new MutationObserver(frameHints).observe($('sel'), { childList: true, subtree: true });
$('sel').addEventListener('focusout', () => { if (S.pendingSel) setTimeout(() => { if (S.pendingSel && !$('sel').contains(document.activeElement)) { S.pendingSel = false; showSel(); } }, 0); });
function showSel() {
  const f = S.sel && findClip(S.sel);
  if (!f && S.selTrack && window.MITTLER_INSPECT_TRACK) { const tr = S.tl.tracks.find(t => t.id === S.selTrack); if (tr && window.MITTLER_INSPECT_TRACK(tr)) return; }
  if (!f) { $('sel').className = 'empty'; $('sel').textContent = $t('sel.empty'); return; }
  const c = f.clip; $('sel').className = '';
  if (window.MITTLER_INSPECT && window.MITTLER_INSPECT(c, f)) return;  // TTS・字幕・音・画像（media.js）
  if (c.type !== 'effect') {
    $('sel').innerHTML = `<div class="metaRow"><b>${$t('sel.track')}</b>${esc(f.track.name || f.track.id)}</div><pre>${esc(JSON.stringify(c, null, 2))}</pre>`; return;
  }
  const fx = S.fx[c.effect] || {}, meta = fx.meta || {}, specs = meta.params || {}, w = win(c);
  const movable = !(w.per_cut || w.fixed);
  const top = movable ? [field('start', c.start, { step: 1 / fps() }, nv => change(() => moveClip(c, nv - c.start)))] : [];
  if (movable && (w.start || w.end)) top.push(field('dur', c.dur, { step: 1 / fps(), min: 1 / fps() }, nv => change(() => trimClip(c, 'r', nv - c.dur))));
  const p = c.params || {};
  const fields = Object.keys(p).map(k => field(k, p[k], specs[k] || {}, nv => change(() => { p[k] = nv; }, { keepForm: true })));
  const missing = Object.keys(specs).filter(k => !(k in p));
  $('sel').innerHTML = `<div class="metaRow"><b>${esc(fxLabel(meta, c.effect))}</b>${esc(c.effect)}${c.cut != null ? esc($t('sep.bar') + $t('cut.label', { label: c.cut })) : ''}</div>
    <div class="metaRow"><b>${$t('sel.track')}</b>${esc(f.track.name || f.track.id)}${w.per_cut ? $t('sel.perCut') : w.fixed ? $t('sel.fixed') : ''}</div>
    <div class="btns"><button id="bCode">${$t('sel.openCode')}</button><button id="bOff">${$t(c.disabled ? 'sel.enable' : 'sel.disable')}</button><button id="bDel">${$t('sel.delete')}</button></div>
    ${meta.blender ? `<div class="btns"><button id="bBlRedraw" title="${esc($t('sel.blRedraw.tip'))}">${$t('sel.blRedraw')}</button><button id="bBlClear" title="${esc($t('sel.blClear.tip'))}">${$t('sel.blClear')}</button>${p.scene ? `<button id="bBlScene" title="${esc($t('sel.blScene.tip'))}">${$t('sel.blScene')}</button>` : ''}</div>` : ''}
    <div class="form">${top.map(x => x.html).join('')}${fields.map(x => x.html).join('')}</div>
    ${missing.length ? `<div class="btns"><select id="bAddSel">${missing.map(k => `<option>${esc(k)}</option>`).join('')}</select><button id="bAdd">${$t('sel.addParam')}</button></div>` : ''}
    ${fxDoc(fx) ? `<details><summary class="empty">${$t('sel.doc')}</summary><div class="doc">${esc(fxDoc(fx))}</div></details>` : ''}`;
  for (const x of top.concat(fields)) x.bind();
  $('bCode').onclick = () => openCode(c.effect);
  $('bOff').onclick = () => change(() => { if (c.disabled) delete c.disabled; else c.disabled = true; });
  $('bDel').onclick = () => deleteClip(c.id);
  if (meta.blender) {  // Blender の 3D：ためた絵（作品の work/3d/<クリップ>/）を消す・消して今のコマを描き直す・場面のスクリプトを開く
    const clear = async redraw => {
      let r; try { r = await (await api('/api/blender/clear', { method: 'POST', body: JSON.stringify({ clip: c.id }), headers: { 'Content-Type': 'application/json' } })).json(); } catch (e) { r = { ok: false, error: String(e) }; }
      if (!r.ok) { setStatus($L('st.blClearFailed', { err: r.error }), 'bad'); return; }
      setStatus($L('st.blCleared', { n: r.files }), 'ok');
      if (redraw) invalidateExact();
    };
    $('bBlRedraw').onclick = () => clear(true);
    $('bBlClear').onclick = () => clear(false);
    if ($('bBlScene')) $('bBlScene').onclick = async () => {
      const root = S.tl.root && S.tl.root !== '.' ? S.tl.root.replace(/\/+$/, '') + '/' : '', path = root + String(p.scene);
      const r = await api('/api/open', { method: 'POST', body: JSON.stringify({ path }), headers: { 'Content-Type': 'application/json' } });
      if (r.ok) setStatus($L('st.codeOpened', { path }), 'ok');
    };
  }
  if ($('bAdd')) $('bAdd').onclick = () => {
    const k = $('bAddSel').value, sp = specs[k] || {};
    const v = sp.type === 'bool' ? false : sp.choices ? sp.choices[0] : sp.type === 'color' ? [255, 255, 255] : sp.type === 'text' ? '' : sp.type === 'lines' ? [$t('field.textDefault')]
      : sp.type === 'font' ? ((((S.assets || {}).fonts) || [])[0] || {}).path || '' : (sp.min != null ? sp.min : 1);
    change(() => { c.params = c.params || {}; c.params[k] = v; });
  };
}
function deleteClip(id) {  // リンクしたクリップも一緒に消す（🔗 連動がオンのとき）
  const ids = new Set(linkGroup(id)); if (!ids.size) return;
  change(() => { for (const tr of S.tl.tracks) tr.clips = tr.clips.filter(c => !ids.has(c.id)); S.sel = null; S.multi = new Set(); });
}
// ---------- 右のパネルのタブ（クリップ・色・メタデータ）。最後に開いたタブを覚えておく ----------
function showPane(name) {
  S.pane = name; try { localStorage.setItem('cc.pane', name); } catch (e) { }
  document.querySelectorAll('#paneTabs button').forEach(b => b.classList.toggle('on', b.dataset.p === name));
  document.querySelectorAll('#inspector .pane').forEach(el => { el.hidden = el.dataset.p !== name; });
  if (name === 'meta') updateMetaNow(true);
}
$('paneTabs').addEventListener('click', e => { const b = e.target.closest('button'); if (b) showPane(b.dataset.p); });

// ---------- メタデータ（タブ。歌詞・ト書き・セリフなどをテキストボックスで直す） ----------
// 拍（beats・pulse_grid）は文字ではないので出さない。
// カット（cuts）は 2026-10-31 から直せる（境目のドラッグ・分ける・つなぐ・ラベル・歌詞とト書き）。道具は editor/cutmeta.js（ラベルを参照するクリップの付け替えもそこ）
const META_SKIP = new Set(['beats', 'pulse_grid']);
const META_FIXED = new Set(['beats', 'pulse_grid']);  // タイムラインでつかんで動かさないもの（カットは丸ごとは動かさず、端＝境目だけ動かす）
function selectMeta(m, it) {
  S.metaSel = m ? { m: m.id, it } : null;
  if (m) { S.sel = null; S.multi = new Set(); markSel(); }
  document.querySelectorAll('#laneList .item').forEach(el => { const mm = (S.tl.meta || []).find(x => x.id === el.dataset.meta); el.classList.toggle('sel', !!(m && mm === m && mm.items[+el.dataset.i] === it)); });
  if (!m) return;
  S.metaTab = m.id; showPane('meta'); buildMetaPanel();
  const i = S.metaItems.indexOf(it), row = document.querySelector(`#metaBody .mrow[data-i="${i}"]`);
  document.querySelectorAll('#metaBody .mrow.picked').forEach(el => el.classList.remove('picked'));
  if (row) { row.classList.add('picked'); row.scrollIntoView({ block: 'nearest' }); }
}
function addMetaItem(m, t) {  // t に新しい項目（次の項目の頭か2秒まで）
  const next = m.items.filter(x => x.start > t).sort((a, b) => a.start - b.start)[0];
  const it = { start: t, end: rT(Math.min(next ? next.start : t + 2, t + 2)) };  // 前は 3 桁に丸めていて、終わりがコマに乗らなかった
  if (it.end - it.start < 1 / fps()) it.end = rT(t + 1);
  for (const [k] of metaFields(m)) it[k] = k === 'value' ? 0.5 : '';
  change(() => { m.items.push(it); m.items.sort((a, b) => a.start - b.start); }, { keepForm: true });
  return it;
}
function deleteMetaSel() {
  const m = S.metaSel && (S.tl.meta || []).find(x => x.id === S.metaSel.m), it = S.metaSel && S.metaSel.it; if (!m) return;
  if (m.kind === 'cuts') { if (window.MITTLER_CUTMETA) MITTLER_CUTMETA.remove(m, it); buildTimeline(); return; }  // カットは前のカットに吸わせる（参照の付け替えも。cutmeta.js）
  change(() => { const k = m.items.indexOf(it); if (k >= 0) m.items.splice(k, 1); }, { keepForm: true });
  S.metaSel = null; buildTimeline(); buildMetaPanel(); setStatus($L('st.deleted'), 'ok');
}
const metaList = () => (S.tl.meta || []).filter(m => !META_SKIP.has(m.kind) && Array.isArray(m.items));
const curMeta = () => metaList().find(m => m.id === S.metaTab);
function metaFields(m) {  // 項目の中の、テキストボックスで直す欄（名前は $L：使うときに今の言葉の文になる）
  if (m.kind === 'cuts') return [['lyric', $L('mf.lyric')], ['togaki', $L('mf.togaki')]];
  if (m.kind === 'sections') return [['value', $L('mf.value')]];
  if (m.kind === 'dialogue') return [['who', $L('mf.who')], ['text', $L('mf.line')]];
  return [['text', '']];
}
function buildMetaPanel() {
  if (!S.tl) return;
  const ms = metaList();
  if (!ms.length) { $('metaTabs').innerHTML = ''; $('metaBody').innerHTML = `<div class="empty">${$t('meta.none')}</div>`; return; }
  if (!ms.some(m => m.id === S.metaTab)) S.metaTab = (ms.find(m => m.kind === 'lyrics') || ms[0]).id;
  $('metaTabs').innerHTML = ms.map(m => `<button class="tab${m.id === S.metaTab ? ' on' : ''}" data-id="${esc(m.id)}">${esc(m.name || KIND[m.kind] || m.kind)}<span class="n">${m.items.length}</span></button>`).join('');
  const m = curMeta(), isCut = m.kind === 'cuts', CM = window.MITTLER_CUTMETA;
  // 行 i が指す項目（並び直しのあとも、作ったときの項目を指す）と世代。作り直しで外れる古い欄が
  // フォーカスを失うときに出す change は、古い世代なので無視する（新しい並びの別の項目に当たっていた）
  S.metaItems = m.items.slice(); const gen = ++S.metaGen;
  const rows = m.items.map((it, i) => {
    const fs = metaFields(m).map(([k, nm]) => {
      const v = it[k] == null ? '' : it[k];
      if (typeof v === 'number') return `<label class="mlab">${nm}</label><input class="mval" data-k="${k}" type="number" step="0.05" value="${v}">`;
      return `${nm ? `<label class="mlab">${nm}</label>` : ''}<textarea class="mtext" data-k="${k}" rows="${Math.min(6, Math.max(1, String(v).split('\n').length + Math.floor(String(v).length / 26)))}">${esc(v)}</textarea>`;
    }).join('');
    const times = `<input class="ms" type="number" step="${1 / fps()}" value="${+it.start.toFixed(3)}">${$t('sep.range')}<input class="me" type="number" step="${1 / fps()}" value="${+it.end.toFixed(3)}">`;
    if (isCut) {  // カット：ラベル・つなぐ・消す・時刻（頭・終わりを変えると隣のカットも一緒。cutmeta.js）
      const w = CM ? CM.mismatch(it) : null;
      return `<div class="mrow cutrow${w ? ' warn' : ''}" data-i="${i}" data-gen="${gen}"><div class="mhead"><button class="jump" title="${esc($t('meta.jump'))}">${$t('meta.cut')}</button>`
        + `<input class="mlabel" type="text" value="${esc(it.label)}" title="${esc($t('meta.labelTip'))}">`
        + `<button class="mjp" title="${esc($t('meta.joinPrev'))}" ${i ? '' : 'disabled'}>←</button><button class="mjn" title="${esc($t('meta.joinNext'))}" ${i < m.items.length - 1 ? '' : 'disabled'}>→</button>`
        + `<button class="mdel" title="${esc($t('meta.delCut'))}" ${m.items.length > 1 ? '' : 'disabled'}>×</button></div>`
        + `<div class="mhead">${times}</div>${w ? `<div class="mwarn">${MITTLER_ICON('triangle-alert')} ${esc(CM.warnText(it, w))}<br><button class="malign" title="${esc($t('meta.align.tip'))}">${$t('meta.align')}</button></div>` : ''}${fs}</div>`;
    }
    return `<div class="mrow" data-i="${i}" data-gen="${gen}"><div class="mhead"><button class="jump" title="${esc($t('meta.jump'))}">${fmt(it.start)}</button>${times}<button class="mdel" title="${esc($t('meta.del'))}">×</button></div>${fs}</div>`;
  }).join('');
  $('metaBody').innerHTML = (isCut
    ? `<div class="btns"><button id="mSplit">${$t(m.items.length ? 'meta.split' : 'meta.firstCut')}</button>${(() => { const n = CM ? m.items.filter(x => CM.mismatch(x)).length : 0; return n ? `<button id="mAlignAll" title="${esc($t('meta.alignAll.tip'))}">${$t('meta.alignAll', { n })}</button>` : ''; })()}</div><div class="empty mnote">${$t('meta.cutNote')}</div>`
    : `<div class="btns"><button id="mAdd">${$t('meta.addHere')}</button></div>`) + rows;
  S.metaNow = -2; updateMetaNow(true);
}
function updateMetaNow(force) {
  const m = S.tl && curMeta(); if (!m) return;
  const i = S.metaItems.findIndex(x => S.t >= x.start && S.t < x.end);
  if (i === S.metaNow && !force) return; S.metaNow = i;
  document.querySelectorAll('#metaBody .mrow').forEach(el => el.classList.toggle('now', +el.dataset.i === i));
  const el = document.querySelector(`#metaBody .mrow[data-i="${i}"]`);
  if (el && !$('metaBody').contains(document.activeElement)) el.scrollIntoView({ block: 'nearest' });
}
$('metaTabs').addEventListener('click', e => { const b = e.target.closest('.tab'); if (!b) return; S.metaTab = b.dataset.id; buildMetaPanel(); });
$('metaBody').addEventListener('click', e => {
  const m = curMeta(); if (!m) return;
  if (e.target.id === 'mAdd') {
    const it = addMetaItem(m, snapFrame(S.t));
    buildMetaPanel(); const i = m.items.indexOf(it); const ta = document.querySelector(`#metaBody .mrow[data-i="${i}"] textarea, #metaBody .mrow[data-i="${i}"] input.mval`); if (ta) ta.focus();
    return;
  }
  if (e.target.id === 'mSplit' && window.MITTLER_CUTMETA) { MITTLER_CUTMETA.splitAtPlayhead(); return; }
  if (e.target.id === 'mAlignAll' && window.MITTLER_CUTMETA) { MITTLER_CUTMETA.alignAll(); return; }
  const row = e.target.closest('.mrow'); if (!row || +row.dataset.gen !== S.metaGen) return; const it = S.metaItems[+row.dataset.i]; if (!it) return;
  if (e.target.classList.contains('jump')) seek(snapFrame(it.start + 0.5 / fps()));
  if (m.kind === 'cuts' && window.MITTLER_CUTMETA) {  // つなぐ・消す（参照の付け替えも。cutmeta.js）
    if (e.target.classList.contains('malign')) MITTLER_CUTMETA.alignVideo([it]);  // 🎞️ 映像をカットに合わせる
    else if (e.target.classList.contains('mjp')) MITTLER_CUTMETA.join(m, it, -1);
    else if (e.target.classList.contains('mjn')) MITTLER_CUTMETA.join(m, it, 1);
    else if (e.target.classList.contains('mdel')) MITTLER_CUTMETA.remove(m, it);
    return;
  }
  if (e.target.classList.contains('mdel')) { change(() => { const k = m.items.indexOf(it); if (k >= 0) m.items.splice(k, 1); }, { keepForm: true }); buildMetaPanel(); }
});
$('metaBody').addEventListener('input', e => { if (e.target.tagName === 'TEXTAREA') { e.target.style.height = 'auto'; e.target.style.height = e.target.scrollHeight + 2 + 'px'; } });
$('metaBody').addEventListener('change', e => {
  // 作り直しで外れた古い欄からの合図（入力中に並び直したときの blur など）は無視する
  const m = curMeta(), row = e.target.closest('.mrow'); if (!m || !row || +row.dataset.gen !== S.metaGen) return; const it = S.metaItems[+row.dataset.i]; if (!it || !m.items.includes(it)) return;
  const cl = e.target.classList;
  if (cl.contains('mlabel') && window.MITTLER_CUTMETA) { if (!MITTLER_CUTMETA.rename(m, it, e.target.value)) e.target.value = it.label; return; }  // カットのラベル（参照も一緒に）
  if (cl.contains('mtext')) change(() => { it[e.target.dataset.k] = e.target.value; }, { keepForm: true });
  else if (cl.contains('mval')) { const v = parseFloat(e.target.value); if (isFinite(v)) change(() => { it[e.target.dataset.k] = v; }, { keepForm: true }); }
  else if (cl.contains('ms') || cl.contains('me')) {
    const s = parseFloat(row.querySelector('.ms').value), en = parseFloat(row.querySelector('.me').value);
    const bad = !isFinite(s) || !isFinite(en) || en <= s;
    row.querySelectorAll('.ms,.me').forEach(x => x.classList.toggle('bad', bad));
    if (bad) { setStatus($L('st.endAfterStartBoth'), 'warn'); return; }  // 途中の状態は戻さない（続けてもう片方を直せるように）
    if (m.kind === 'cuts' && window.MITTLER_CUTMETA) { MITTLER_CUTMETA.setTimes(m, it, s, en); buildTimeline(); return; }  // カット：隣のカットの端も一緒に（cutmeta.js）
    // 直した欄だけ書く（欄は 3 桁なので、直していないほうを書くと値が 3 桁に削れる）。コマにそろえる（ドラッグと同じ）
    const isS = cl.contains('ms'), v = Math.max(0, snapFrame(isS ? s : en));
    if (isS ? !(v < it.end) : !(v > it.start)) { setStatus($L('st.endAfterStart'), 'warn'); return; }
    change(() => { if (isS) it.start = v; else it.end = v; m.items.sort((a, b) => a.start - b.start); }, { keepForm: true });
    buildMetaPanel();
  }
});
function showMetaNow() { updateMetaNow(); }

// ---------- コード ----------
async function openCode(name) {
  const path = `effects/${name}.py`;
  const r = await api('/api/open', { method: 'POST', body: JSON.stringify({ path }), headers: { 'Content-Type': 'application/json' } });
  if (r.ok) { setStatus($L('st.codeOpened', { path }), 'ok'); return; }
  const t = await (await fetch('/api/file?path=' + encodeURIComponent(path), { cache: 'no-store' })).text();
  $('codeName').textContent = path; $('codeText').value = t; $('codePanel').hidden = false; $('codeText').focus();
}
$('codeClose').onclick = () => { $('codePanel').hidden = true; };
$('codeSave').onclick = async () => {
  const path = $('codeName').textContent;
  const r = await api('/api/file?path=' + encodeURIComponent(path), { method: 'PUT', body: $('codeText').value });
  if (r.ok) setStatus($L('st.codeSaved', { path }), 'busy'); else setStatus($L('st.codeSaveFailed'), 'bad');
};
$('codeText').addEventListener('keydown', e => {
  if (e.key === 'Tab') { e.preventDefault(); const t = e.target, s = t.selectionStart; t.value = t.value.slice(0, s) + '    ' + t.value.slice(t.selectionEnd); t.selectionStart = t.selectionEnd = s + 4; }
  if (e.key === 's' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $('codeSave').click(); }
});

// ---------- 色の卓（カットごと：明るさ b・コントラスト c・ビブランス v・彩度 s。effects/grade.py と同じ式＝editor/calc.js の gradePixel） ----------
function gradeClip(label) {
  const same = c => (label === '' ? c.cut == null : String(c.cut) === String(label));  // カットの無い作品：全体に1つ（cut なし）
  for (const tr of S.tl.tracks) for (const c of tr.clips || []) if (c.type === 'effect' && c.effect === 'grade' && same(c)) return { clip: c, track: tr };
  return null;
}
function ensureGradeTrack() {
  let tr = S.tl.tracks.find(t => t.effect === 'grade' || /^t_grade/.test(t.id)); if (tr) return tr;
  tr = { id: 't_grade_0', name: $t('track.grade'), kind: 'effect', effect: 'grade', clips: [] };  // トラックの名前（作品の中身）は、作るときの画面の言葉で
  const i = S.tl.tracks.findIndex(t => /^t_light/.test(t.id));  // 光とトーンマップのすぐ上（先頭がいちばん手前）
  S.tl.tracks.splice(i < 0 ? 0 : i, 0, tr); return tr;
}
// 色のつまみ：鍵と名前（名前は $L：使うときに今の言葉の文になる）
const GK = [['b', $L('grade.b')], ['c', $L('grade.c')], ['v', $L('grade.v')], ['s', $L('grade.s')]];
function buildGradePanel() {
  if (!S.tl) { $('gradePanel').innerHTML = ''; return; }
  const cu = cutAt(S.t) || { label: '', start: 0, end: dur() }; S.gradeCut = cu.label;  // カットの表が無い・空なら全体
  const g = gradeClip(cu.label), p = g ? g.clip.params : {};
  $('gradePanel').innerHTML = `<h2>${cu.label === '' ? $t('grade.titleAll') : $t('grade.titleCut', { label: esc(cu.label) })}</h2>` + GK.map(([k, nm]) =>
    `<div class="slider"><span>${nm}</span><input id="g_${k}" type="range" min="0.5" max="1.5" step="0.01" value="${p[k] != null ? p[k] : 1}"><span id="gv_${k}">${(p[k] != null ? p[k] : 1).toFixed(2)}</span></div>`).join('') +
    `<div class="btns"><button id="gReset">${$t(cu.label === '' ? 'grade.reset' : 'grade.resetCut')}</button></div>`;
  const vals = () => Object.fromEntries(GK.map(([k]) => [k, parseFloat($('g_' + k).value)]));
  for (const [k] of GK) {
    const el = $('g_' + k);
    el.addEventListener('input', () => { $('gv_' + k).textContent = parseFloat(el.value).toFixed(2); previewGrade(vals()); });
    el.addEventListener('change', () => setGrade(cu, vals()));
  }
  $('gReset').onclick = () => setGrade(cu, { b: 1, c: 1, v: 1, s: 1 });
}
function setGrade(cu, v) {
  change(() => {
    const g = gradeClip(cu.label); const ident = GK.every(([k]) => Math.abs(v[k] - 1) < 1e-9);
    if (ident) { if (g) g.track.clips = g.track.clips.filter(c => c !== g.clip); return; }  // 1.0 なら色の手直しそのものを外す（元の絵とビット単位で同じに）
    const params = Object.fromEntries(GK.map(([k]) => [k, +v[k].toFixed(3)]).filter(([, x]) => x !== 1));
    if (g) g.clip.params = params;
    else ensureGradeTrack().clips.push(Object.assign({ id: 'grade_' + (cu.label === '' ? 'all' : cu.label), type: 'effect', effect: 'grade', start: cu.start, dur: +(cu.end - cu.start).toFixed(6) },
      cu.label === '' ? {} : { cut: String(cu.label) }, { params }));
  }, { keepForm: true });
  S.exactT = null; buildGradePanel();
}
// スライダーを動かしているあいだは、いまの絵に同じ式をかけて見せる（おおよそ：本物は字・ネオンの前にかかる。離すと描き直す）
function previewGrade(v) { const cur = gradeClip(S.gradeCut); previewGradeWith(v, cur ? cur.clip.params : {}); }
// p0＝いまの絵にもうかかっている値（色の卓ならそのカットの grade、クリップの色ならそのクリップの grade）
function previewGradeWith(v, p0) {
  const img = $('frameImg'); if (img.hidden || !img.naturalWidth) return;
  const cv = $('gradeCv'), sc = $('screen'); const w = Math.round(sc.clientWidth), h = Math.round(sc.clientHeight);
  cv.width = w; cv.height = h; cv.hidden = false; const g = cv.getContext('2d'); g.drawImage(img, 0, 0, w, h);
  p0 = p0 || {};
  const d = g.getImageData(0, 0, w, h), a = d.data;
  const r = k => (v[k] || 1) / (p0[k] || 1);  // いまの絵にはもう p0 がかかっているので、変化分だけ（おおよそ）
  const b = r('b'), c = r('c'), vv = r('v'), s = r('s');
  const px = MITTLER_CALC.gradePixel;  // effects_lib/common/grade.py と同じ式（editor/calc.js。同じことは tools/smoke_same.py が確かめる）
  for (let i = 0; i < a.length; i += 4) {
    const [R, G, B] = px(a[i] / 255, a[i + 1] / 255, a[i + 2] / 255, b, c, vv, s);
    a[i] = R * 255; a[i + 1] = G * 255; a[i + 2] = B * 255;
  }
  g.putImageData(d, 0, 0); showSrc($L('src.gradePreview'));
}
// ---------- クリップの色（映像・画像・🎬 のクリップの grade：{b, c, v, s}。クリップごとに色の調整を持たせる） ----------
// 色の卓と同じつまみ・同じ式（effects_lib/common/grade.py＝editor/calc.js の gradePixel）。エンジンはそのクリップの絵を読んだ直後（エフェクトより前）にかける。
// クリップを動かす・分ける・写すと色も一緒。カットの色の卓とは別で、両方かかる。全部 1 なら JSON に書かない（grade を消す＝元の絵とビット単位で同じ）
function clipGradeHTML(c) {
  const p = c.grade || {};
  return `<div class="cgrade"><h3>${$t('cgrade.title')}</h3>` + GK.map(([k, nm]) =>
    `<div class="slider"><span>${nm}</span><input data-cg="${k}" type="range" min="0.5" max="1.5" step="0.01" value="${p[k] != null ? p[k] : 1}"><span data-cgv="${k}">${(p[k] != null ? p[k] : 1).toFixed(2)}</span></div>`).join('')
    + `<div class="btns"><button data-cg="reset" ${c.grade ? '' : 'disabled'}>${$t('grade.reset')}</button></div>
    <div class="tdim">${$t('cgrade.note')}</div></div>`;
}
function bindClipGrade(el, c) {
  const sec = el.querySelector('.cgrade'); if (!sec) return;
  const vals = () => Object.fromEntries(GK.map(([k]) => [k, parseFloat(sec.querySelector(`[data-cg="${k}"]`).value)]));
  for (const [k] of GK) {
    const inp = sec.querySelector(`[data-cg="${k}"]`);
    inp.addEventListener('input', () => {
      sec.querySelector(`[data-cgv="${k}"]`).textContent = parseFloat(inp.value).toFixed(2);
      if (c.start <= S.t && S.t < c.start + c.dur) previewGradeWith(vals(), c.grade);  // 再生位置にかかっているクリップなら、おおよその色を見せる
    });
    inp.addEventListener('change', () => { setClipGrade(c.id, vals(), true); const f = findClip(c.id), b = sec.querySelector('[data-cg="reset"]'); if (b) b.disabled = !(f && f.clip.grade); });
  }
  sec.querySelector('[data-cg="reset"]').onclick = () => setClipGrade(c.id, { b: 1, c: 1, v: 1, s: 1 }, false);
}
function setClipGrade(id, v, keepForm) {
  const f = findClip(id); if (!f) return; const c = f.clip;
  change(() => {
    const params = Object.fromEntries(GK.map(([k]) => [k, +(+v[k]).toFixed(3)]).filter(([, x]) => x !== 1));
    if (Object.keys(params).length) c.grade = params; else delete c.grade;
  }, { keepForm });
  S.exactT = null;
}

// ---------- マウス・キー ----------
function timeAt(e) { const r = $('lanes').getBoundingClientRect(); return (e.clientX - r.left) / S.pps; }

// ---------- スナップ（動画編集ソフトのあれ）：クリップの移動・端の伸び縮み・再生位置のドラッグが、近く（8px 以内）の目印に吸いつく ----------
// 目印：ほかのクリップの頭と終わり・再生位置・カットの境目・拍・タイムラインの先頭と末尾。🧲（S キー）でオン・オフ、ドラッグ中の Alt で一時的に逆。
const SNAP_PX = 8;
const SNAP_KINDS = [['clips', $L('snap.clips')], ['playhead', $L('snap.playhead')], ['cuts', $L('snap.cuts')], ['beats', $L('snap.beats')], ['edges', $L('snap.edges')]];  // 名前は $L
S.snap = Object.assign({ on: true, clips: true, playhead: true, cuts: true, beats: true, edges: true }, (() => { try { return JSON.parse(localStorage.getItem('cc.snap') || '{}'); } catch (e) { return {}; } })());
function saveSnap() { try { localStorage.setItem('cc.snap', JSON.stringify(S.snap)); } catch (e) { } refreshSnapUI(); }
function refreshSnapUI() {
  const b = $('snapBtn'); b.classList.toggle('on', !!S.snap.on);
  const on = SNAP_KINDS.filter(([k]) => S.snap[k]).map(x => x[1]).join($t('sep.list'));
  b.title = on ? $t(S.snap.on ? 'snap.tipOn' : 'snap.tipOff', { list: on }) : $t(S.snap.on ? 'snap.tipOnNone' : 'snap.tipOffNone');
  $('snapMenu').innerHTML = SNAP_KINDS.map(([k, n]) => `<label><input type="checkbox" data-snap="${k}" ${S.snap[k] ? 'checked' : ''}> ${n}</label>`).join('');
}
// 吸いつく先の一覧 [[秒, 名前], …]（except＝動かしているクリップの id、withPlayhead＝再生位置も入れるか）
function snapTargets(except, withPlayhead, exceptItem) {
  const out = [], sn = S.snap, ex = except instanceof Set ? except : new Set(except ? [except] : []);
  const T = k => $t('snapt.' + k), cs = $t('snapt.clipStart'), ce = $t('snapt.clipEnd');
  if (sn.edges) out.push([0, T('start')], [dur(), T('end')]);
  if (sn.playhead && withPlayhead) out.push([S.t, T('playhead')]);
  if (sn.clips) for (const tr of S.tl.tracks || []) {
    if (tr.shy && S.hideShy) continue;
    for (const c of tr.clips || []) { if (ex.has(c.id)) continue; out.push([c.start, cs], [c.start + c.dur, ce]); }
  }
  for (const m of S.tl.meta || []) {
    if (sn.clips && !META_FIXED.has(m.kind) && m.kind !== 'cuts' && Array.isArray(m.items) && !(m.shy && S.hideShy)) for (const it of m.items) { if (it === exceptItem) continue; const n = m.name || KIND[m.kind] || m.kind; out.push([it.start, $t('snapt.itemStart', { name: n })], [it.end, $t('snapt.itemEnd', { name: n })]); }
    if (m.kind === 'cuts' && sn.cuts) for (const it of m.items || []) { if (it === exceptItem || (exceptItem instanceof Set && exceptItem.has(it))) continue; const label = it.label != null ? it.label : ''; out.push([it.start, $t('snapt.cutStart', { label })]); if (it.end != null) out.push([it.end, $t('snapt.cutEnd', { label })]); }
    if (m.kind === 'beats' && sn.beats) {
      const bs = Array.isArray(m.items) && m.items.length ? m.items.map(b => [+b[0], !!b[1]]) : (m.times || []).map(t => [+t, false]);
      const bar = T('bar'), beat = T('beat');
      for (const [t, down] of bs) out.push([t, down ? bar : beat]);
    }
  }
  return out;
}
// t のいちばん近い目印（SNAP_PX 以内）。吸いつかないなら null
function snapNear(t, targets) {
  let best = null, bd = SNAP_PX / S.pps;
  for (const [x, k] of targets) { const d = Math.abs(x - t); if (d < bd) { bd = d; best = [x, k]; } }
  return best;
}
const snapping = e => !!S.snap.on !== !!(e && e.altKey);  // Alt で一時的に逆
function showSnap(hit) {
  const el = $('snapLine');
  if (!hit) { el.style.display = 'none'; return; }
  el.style.display = 'block'; el.style.left = (hit[0] * S.pps) + 'px'; el.title = hit[1];
}
const movable = c => { const w = win(c); return !w.fixed && !w.per_cut; };
const clipEl = id => document.querySelector(`#laneList .clip[data-id="${CSS.escape(id)}"]`);
$('lanes').addEventListener('mousedown', e => {
  if (e.button !== 0) return;
  const tool = S.tool || 'select';
  // メタデータ（歌詞・ト書き・セリフ…）の項目：つかんで動かす・端で伸び縮み
  const mi = e.target.closest('.item.ed');
  if (mi) {
    const m = (S.tl.meta || []).find(x => x.id === mi.dataset.meta), it = m && m.items[+mi.dataset.i]; if (!it) return;
    selectMeta(m, it);
    const mode = e.target.classList.contains('grip') ? (e.target.classList.contains('l') ? 'l' : 'r') : 'move';
    if (m.kind === 'cuts') {  // カット：丸ごとは動かさない。端＝境目だけ（隣のカットの端も一緒に。cutmeta.js）
      if (mode === 'move' || !window.MITTLER_CUTMETA) { e.preventDefault(); return; }
      const rg = MITTLER_CUTMETA.edgeRange(m, it, mode), nbEl = rg.nb ? document.querySelector(`#laneList .item[data-meta="${CSS.escape(m.id)}"][data-i="${m.items.indexOf(rg.nb)}"]`) : null;
      S.drag = { meta: m, it, mode, cut: rg, x0: e.clientX, el: mi, left: it.start * S.pps, width: (it.end - it.start) * S.pps, dt: 0, s0: it.start, e0: it.end,
        nb: nbEl ? { el: nbEl, left: rg.nb.start * S.pps, width: (rg.nb.end - rg.nb.start) * S.pps } : null, targets: snapTargets(null, true, new Set([it].concat(rg.nb ? [rg.nb] : []))) };
      e.preventDefault(); return;
    }
    S.drag = { meta: m, it, mode, x0: e.clientX, el: mi, left: it.start * S.pps, width: (it.end - it.start) * S.pps, dt: 0, s0: it.start, e0: it.end, targets: snapTargets(null, true, it) };
    e.preventDefault(); return;
  }
  const cl = e.target.closest('.clip');
  if (cl) {
    const id = cl.dataset.id, f = findClip(id); if (!f) return;
    if (tool === 'razor' && window.MITTLER_CUT) { MITTLER_CUT.razorClick(e, f); e.preventDefault(); return; }
    if (e.ctrlKey || e.metaKey || e.shiftKey) { select(id, true); if (S.pane !== 'sel') showPane('sel'); e.preventDefault(); return; }  // 足す・外す
    if (S.multi && S.multi.has(id) && S.multi.size > 1) { S.sel = id; markSel(); showSel(); } else select(id);  // 選んでいる中をつかんだら、全部のまま
    if (S.pane !== 'sel') showPane('sel');
    if (!movable(f.clip)) return;
    const tg = e.target.classList, c = f.clip;
    let mode = tg.contains('grip') ? (tg.contains('l') ? 'l' : 'r') : tg.contains('fh') ? (tg.contains('l') ? 'fi' : 'fo') : 'move';
    if (tool === 'slip' && mode === 'move') {
      if (!(win(c).trimIn && !(window.MITTLER_WARP && MITTLER_WARP.isPts(c)) && typeof c.warp !== 'string')) { setStatus($L('st.slipOnly'), 'warn'); return; }
      mode = 'slip';
    }
    // 一緒に動かすもの：動かす＝選んでいるもの全部。伸び縮み・スリップ＝つかんだクリップと、端のそろったリンク。フェード＝つかんだクリップだけ
    const edgeOf = (x, side) => side === 'l' ? x.start : x.start + x.dur;
    let ids = mode === 'move' ? selIds() : mode === 'fi' || mode === 'fo' ? [id] : linkGroup(id);
    if (mode === 'l' || mode === 'r') ids = ids.filter(x => x === id || Math.abs(edgeOf(findClip(x).clip, mode) - edgeOf(c, mode)) < 0.5 / fps());
    const items = ids.map(x => findClip(x)).filter(g => g && movable(g.clip) && clipEl(g.clip.id))
      .map(g => ({ id: g.clip.id, el: clipEl(g.clip.id), tr: g.track, left: g.clip.start * S.pps, width: g.clip.dur * S.pps, s0: g.clip.start, in0: g.clip.in || 0 }));
    S.drag = { id, mode, x0: e.clientX, el: cl, items, track: f.track, left: c.start * S.pps, width: c.dur * S.pps, dt: 0, dTrack: 0,
      s0: c.start, e0: c.start + c.dur, targets: snapTargets(new Set(items.map(x => x.id)), true), f0: mode === 'fi' ? (c.fade_in || 0) : (c.fade_out || 0) };
    e.preventDefault(); return;
  }
  if ((e.shiftKey || e.ctrlKey || e.metaKey) && e.target.closest('#laneList')) { startMarquee(e); e.preventDefault(); return; }  // 囲んで選ぶ
  S.dragging = true; S.scrubTargets = snapTargets(null, false); scrubTo(e);
});
// 囲んで選ぶ（Shift・Ctrl を押しながら空いたところをドラッグ）
function startMarquee(e) {
  const r = $('lanes').getBoundingClientRect();
  S.marq = { x0: e.clientX - r.left, y0: e.clientY - r.top, base: new Set(e.ctrlKey || e.metaKey || e.shiftKey ? selIds() : []) };
  const el = $('marq'); el.hidden = false; Object.assign(el.style, { left: S.marq.x0 + 'px', top: S.marq.y0 + 'px', width: '0px', height: '0px' });
}
function updateMarquee(e) {
  const r = $('lanes').getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, q = S.marq;
  Object.assign($('marq').style, { left: Math.min(x, q.x0) + 'px', top: Math.min(y, q.y0) + 'px', width: Math.abs(x - q.x0) + 'px', height: Math.abs(y - q.y0) + 'px' });
}
function finishMarquee() {
  const box = $('marq').getBoundingClientRect(); $('marq').hidden = true; const q = S.marq; S.marq = null;
  const hit = [...document.querySelectorAll('#laneList .clip')].filter(el => { const b = el.getBoundingClientRect(); return b.right > box.left && b.left < box.right && b.bottom > box.top && b.top < box.bottom; }).map(el => el.dataset.id);
  const all = new Set(q.base); for (const id of hit) for (const x of linkGroup(id)) all.add(x);
  S.multi = all; if (!all.has(S.sel)) S.sel = [...all][0] || null; if (S.sel) S.selTrack = null;
  markSel(); showSel(); if (hit.length) setStatus($L('st.marqSelected', { n: all.size }));
}
// 動かしているクリップを上下のトラックへ：つかんだクリップと同じ種類のトラックだけ（映像は映像、音は音）
const kindKey = tr => tr.kind === 'media' ? 'video' : tr.kind;
function dragTrackDelta(e, d) {
  const lanes = [...document.querySelectorAll('#laneList .lane[data-track]')];
  const li = lanes.findIndex(l => { const b = l.getBoundingClientRect(); return e.clientY >= b.top && e.clientY < b.bottom; });
  if (li < 0) return d.dTrack || 0;
  const i0 = lanes.findIndex(l => l.dataset.track === d.track.id); if (i0 < 0) return 0;
  const delta = li - i0; if (!delta) return 0;
  for (const it of d.items) {
    if (kindKey(it.tr) !== kindKey(d.track)) continue;
    const j = lanes.findIndex(l => l.dataset.track === it.tr.id), to = lanes[j + delta];
    const tt = to && S.tl.tracks.find(t => t.id === to.dataset.track);
    if (!tt || kindKey(tt) !== kindKey(it.tr)) return 0;
  }
  return delta;
}
function dragTargetTrack(it, d) {
  if (!d.dTrack || kindKey(it.tr) !== kindKey(d.track)) return it.tr;
  const lanes = [...document.querySelectorAll('#laneList .lane[data-track]')];
  const j = lanes.findIndex(l => l.dataset.track === it.tr.id), to = lanes[j + d.dTrack];
  return (to && S.tl.tracks.find(t => t.id === to.dataset.track)) || it.tr;
}
// 再生位置のドラッグ：目印に吸いつく（吸いつかなければコマにそろえる）
function scrubTo(e) {
  const t = timeAt(e), hit = snapping(e) ? snapNear(t, S.scrubTargets || []) : null;
  showSnap(hit); seek(hit ? hit[0] : snapFrame(t));
}
window.addEventListener('mousemove', e => {
  if (S.drag && (S.drag.mode === 'fi' || S.drag.mode === 'fo')) {  // フェードのつまみ
    const d = S.drag, c = (findClip(d.id) || {}).clip; if (!c) return;
    const raw = (e.clientX - d.x0) / S.pps, v = Math.max(0, Math.min(c.dur, snapFrame(d.f0 + (d.mode === 'fi' ? raw : -raw)))); d.val = v;
    const fd = d.el.querySelector(d.mode === 'fi' ? '.fade.in' : '.fade.out'), h = d.el.querySelector(d.mode === 'fi' ? '.fh.l' : '.fh.r');
    if (fd) fd.style.width = v * S.pps + 'px'; if (h) h.style[d.mode === 'fi' ? 'left' : 'right'] = v * S.pps + 'px';
    setStatus($L(d.mode === 'fi' ? 'drag.fadeIn' : 'drag.fadeOut', { v: v.toFixed(3) })); return;
  }
  if (S.drag && S.drag.mode === 'slip') {  // スリップ：位置と長さはそのまま、映す素材の場所（in）をずらす
    const d = S.drag, c = (findClip(d.id) || {}).clip; if (!c) return; d.dt = snapFrame((e.clientX - d.x0) / S.pps);
    const it = d.items.find(x => x.id === d.id) || { in0: c.in || 0 }, nin = window.MITTLER_CUT ? MITTLER_CUT.slipIn(c, it.in0, d.dt) : Math.max(0, it.in0 - d.dt);
    d.el.classList.add('dragging'); setStatus($L('drag.slip', { t: fmt(nin), d: (nin - it.in0 >= 0 ? '+' : '') + (nin - it.in0).toFixed(3) })); return;
  }
  if (S.drag) {
    const d = S.drag, raw = (e.clientX - d.x0) / S.pps; d.dt = snapFrame(raw); d.hit = null;
    if (snapping(e)) {  // 動かす：頭か終わりの近いほうが吸いつく。伸び縮み：動かしている端が吸いつく
      const edges = d.mode === 'move' ? [d.s0, d.e0] : d.mode === 'l' ? [d.s0] : [d.e0];
      let best = null;
      for (const e0 of edges) { const h = snapNear(e0 + raw, d.targets); if (h && (!best || Math.abs(h[0] - (e0 + raw)) < best.dist)) best = { h, dt: h[0] - e0, dist: Math.abs(h[0] - (e0 + raw)) }; }
      if (best) { d.dt = +best.dt.toFixed(6); d.hit = best.h; }
    }
    if (d.mode === 'move') { const lo = d.meta ? d.s0 : Math.min(...d.items.map(x => x.s0)); if (d.dt < -lo) { d.dt = -lo; d.hit = null; } }  // 先頭より前には出さない
    if (d.cut) {  // カットの境目：隣のカットを1コマより短くしない・すき間や重なりを作らない（cutmeta.js の edgeRange）
      const e0 = d.mode === 'l' ? d.s0 : d.e0, v = Math.max(d.cut.lo, Math.min(d.cut.hi, e0 + d.dt));
      if (Math.abs(v - (e0 + d.dt)) > 1e-9) { d.dt = +(v - e0).toFixed(6); d.hit = null; }
    }
    showSnap(d.hit);
    const px = d.dt * S.pps;
    const els = d.meta ? [{ el: d.el, left: d.left, width: d.width }] : d.items;
    for (const x of els) {
      x.el.classList.add('dragging');
      if (d.mode === 'move') x.el.style.left = (x.left + px) + 'px';
      else if (d.mode === 'l') { x.el.style.left = (x.left + px) + 'px'; x.el.style.width = Math.max(3, x.width - px) + 'px'; }
      else x.el.style.width = Math.max(3, x.width + px) + 'px';
    }
    if (d.nb) {  // 隣のカット（境目の向こう側）も一緒に
      d.nb.el.classList.add('dragging');
      if (d.mode === 'l') d.nb.el.style.width = Math.max(3, d.nb.width + px) + 'px';
      else { d.nb.el.style.left = (d.nb.left + px) + 'px'; d.nb.el.style.width = Math.max(3, d.nb.width - px) + 'px'; }
    }
    const hitTxt = d.hit ? $t('drag.snapHit', { name: d.hit[1], t: fmt(d.hit[0]) }) : '', dSign = (d.dt >= 0 ? '+' : '') + d.dt.toFixed(3);
    if (d.cut) { setStatus($t(d.nb ? 'drag.cutBoundary' : d.mode === 'l' ? 'drag.cutStart' : 'drag.cutEnd', { label: d.it.label, t: fmt((d.mode === 'l' ? d.s0 : d.e0) + d.dt), d: dSign }) + hitTxt); return; }
    if (!d.meta && d.mode === 'move') {  // 上下のトラックへ
      d.dTrack = dragTrackDelta(e, d);
      for (const x of d.items) { const to = dragTargetTrack(x, d), lane = document.querySelector(`#laneList .lane[data-track="${CSS.escape(to.id)}"]`); if (lane && x.el.parentNode !== lane) lane.appendChild(x.el); }
    }
    const many = !d.meta && d.items.length > 1;
    setStatus($t((d.mode === 'move' ? 'drag.move' : 'drag.len') + (many ? 'N' : ''), { n: d.items ? d.items.length : 1, d: dSign })
      + (d.dTrack ? $t('drag.track', { dir: d.dTrack > 0 ? '↓' : '↑', n: Math.abs(d.dTrack) }) : '') + hitTxt);
    return;
  }
  if (S.marq) { updateMarquee(e); return; }
  if (S.dragging) { scrubTo(e); return; }
  if (S.tool === 'razor' && window.MITTLER_CUT) MITTLER_CUT.razorHover(e);
});
window.addEventListener('mouseup', () => {
  if (S.drag) {
    const d = S.drag; S.drag = null; const r6 = rT, mf = 1 / fps();  // コマに乗っていればコマの時刻そのもの、いなければ 6 桁
    if (d.meta && d.cut) {  // カットの境目（cutmeta.js：隣のカット・カットごとのエフェクトも一緒に、1回の取り消し）
      if (Math.abs(d.dt) > 1e-9) MITTLER_CUTMETA.moveEdge(d.meta, d.it, d.mode, (d.mode === 'l' ? d.s0 : d.e0) + d.dt);
      buildTimeline(); if (d.meta.items.includes(d.it)) selectMeta(d.meta, d.it);
    } else if (d.meta) {
      const m = d.meta, it = d.it;
      if (Math.abs(d.dt) > 1e-9 && m.items.includes(it)) {
        change(() => {
          if (d.mode === 'move') { it.start = r6(it.start + d.dt); it.end = r6(it.end + d.dt); }
          else if (d.mode === 'l') it.start = r6(Math.min(it.end - mf, it.start + d.dt));
          else it.end = r6(Math.max(it.start + mf, it.end + d.dt));
          m.items.sort((a, b) => a.start - b.start);
        }, { keepForm: true });
        S.metaSel = { m: m.id, it }; buildTimeline(); buildMetaPanel(); selectMeta(m, it);
      } else buildTimeline();
    } else if (d.mode === 'fi' || d.mode === 'fo') {
      const f = findClip(d.id);
      if (f && d.val != null && Math.abs(d.val - d.f0) > 1e-9) change(() => { f.clip[d.mode === 'fi' ? 'fade_in' : 'fade_out'] = r6(d.val); }); else buildTimeline();
    } else if (d.mode === 'slip') {
      if (Math.abs(d.dt) > 1e-9) change(() => { for (const x of d.items) { const g = findClip(x.id); if (g) g.clip.in = r6(window.MITTLER_CUT ? MITTLER_CUT.slipIn(g.clip, x.in0, d.dt) : Math.max(0, x.in0 - d.dt)); } });
      else buildTimeline();
    } else if (Math.abs(d.dt) > 1e-9 || d.dTrack) {
      change(() => {
        for (const x of d.items) {
          const g = findClip(x.id); if (!g) continue; const c = g.clip;
          if (d.mode === 'move') {
            const to = dragTargetTrack({ tr: g.track }, d);
            moveClip(c, d.dt);
            if (to !== g.track) { g.track.clips = g.track.clips.filter(y => y !== c); to.clips.push(c); to.clips.sort((a, b) => a.start - b.start); }
          } else trimClip(c, d.mode, d.dt);
        }
      });
    } else buildTimeline();
  }
  if (S.marq) finishMarquee();
  S.dragging = false; showSnap(null);
});
$('snapBtn').addEventListener('click', () => { S.snap.on = !S.snap.on; saveSnap(); setStatus($L(S.snap.on ? 'st.snapOn' : 'st.snapOff')); });
$('snapMenuBtn').addEventListener('click', e => { e.stopPropagation(); $('snapMenu').hidden = !$('snapMenu').hidden; });
$('snapMenu').addEventListener('change', e => { const k = e.target.dataset.snap; if (k) { S.snap[k] = e.target.checked; saveSnap(); } });
document.addEventListener('mousedown', e => { if (!e.target.closest('.snapWrap')) $('snapMenu').hidden = true; });
refreshSnapUI();
$('headList').addEventListener('click', e => {
  const CM = window.MITTLER_CUTMETA;
  const ad = e.target.closest('.madd');  // メタデータの段の ＋（cutmeta.js）
  if (ad && CM) { const m = (S.tl.meta || []).find(x => x.id === ad.dataset.meta); if (m) CM.addAt(m, snapFrame(S.t)); return; }
  const am = e.target.closest('[data-addmeta]');  // カット・ト書きの段を作る
  if (am && CM) { CM.addLane(am.dataset.addmeta); return; }
  const sh = e.target.closest('.shy');
  if (sh) {
    const it = sh.dataset.track ? S.tl.tracks.find(t => t.id === sh.dataset.track) : (S.tl.meta || []).find(x => x.id === sh.dataset.meta);
    if (it) change(() => { if (it.shy) delete it.shy; else it.shy = true; });
    return;
  }
  const m = e.target.closest('.mute'); const h = e.target.closest('.head'); const v = e.target.closest('.vis');
  if (m) { const tr = S.tl.tracks.find(t => t.id === m.dataset.track); if (tr) change(() => { if (tr.muted || tr.hidden) { delete tr.muted; delete tr.hidden; } else tr.muted = true; }); return; }
  if (v) { const tr = S.tl.tracks.find(t => t.id === v.dataset.track); if (tr) change(() => { if (tr.hidden) delete tr.hidden; else tr.hidden = true; }); return; }
  if (h && h.dataset.track) { S.selTrack = h.dataset.track; S.sel = null; buildTimeline(); showSel(); if (S.pane !== 'sel') showPane('sel'); }
});
// トラックの空いたところをダブルクリック：そのトラックに新しいクリップ（TTS・字幕。media.js）
$('lanes').addEventListener('dblclick', e => {
  if (e.target.closest('.clip')) return;
  const ml = e.target.closest('.lane.meta');
  if (ml && window.MITTLER_CUTMETA) {  // カットの段：そこで分ける（カットが無ければ最初のカット）。cutmeta.js
    const m = (S.tl.meta || []).find(x => x.id === ml.dataset.meta);
    if (m && m.kind === 'cuts' && Array.isArray(m.items)) { if (!e.target.closest('.grip')) MITTLER_CUTMETA.addAt(m, snapFrame(timeAt(e))); return; }
  }
  if (e.target.closest('.item')) return;
  if (ml) {
    const m = (S.tl.meta || []).find(x => x.id === ml.dataset.meta); if (!m || META_FIXED.has(m.kind) || !Array.isArray(m.items)) return;
    const it = addMetaItem(m, snapFrame(timeAt(e))); selectMeta(m, it);
    const i = S.metaItems.indexOf(it), ta = document.querySelector(`#metaBody .mrow[data-i="${i}"] textarea, #metaBody .mrow[data-i="${i}"] input.mval`); if (ta) ta.focus();
    return;
  } const lane = e.target.closest('.lane'); if (!lane || !lane.dataset.track || !window.MITTLER_LANE_DBL) return;
  window.MITTLER_LANE_DBL(S.tl.tracks.find(t => t.id === lane.dataset.track), snapFrame(timeAt(e)));
});
$('lanesWrap').addEventListener('scroll', () => { $('headList').style.transform = `translateY(${-$('lanesWrap').scrollTop}px)`; });
$('lanesWrap').addEventListener('wheel', e => { if (!e.ctrlKey) return; e.preventDefault(); setZoom(S.pps * (e.deltaY < 0 ? 1.2 : 1 / 1.2), e); }, { passive: false });
// 拡大：いちばん小さいのは全体がちょうど1画面に収まる倍率、大きいのは 400px/秒。スライダーは対数（小さい倍率も動かしやすく）。
// 短い作品（全体が 400px/秒でも 1 画面に足りない）は、上限を「全体が収まる倍率」まで上げる（前は 3 秒の作品が左 1/3 に寄ったままで、「全体」を押しても広がらなかった）
const MAX_PPS = 400;
function fitPps() { return Math.max(0.2, ($('lanesWrap').clientWidth - 24) / (dur() + padSec())); }
const maxPps = () => Math.max(MAX_PPS, fitPps());
function zoomRange() { const z = $('zoom'); z.min = Math.log(fitPps()).toFixed(3); z.max = Math.log(maxPps()).toFixed(3); z.value = Math.log(S.pps); z.disabled = maxPps() - fitPps() < 1e-6; }
function setZoom(pps, e) {
  const wr = $('lanesWrap'); const ax = e ? e.clientX - wr.getBoundingClientRect().left : wr.clientWidth / 2; const tAt = (wr.scrollLeft + ax) / S.pps;
  S.pps = Math.max(fitPps(), Math.min(maxPps(), pps)); zoomRange(); buildTimeline(); wr.scrollLeft = tAt * S.pps - ax;
}
function zoomFit() { setZoom(fitPps()); $('lanesWrap').scrollLeft = 0; }
$('zoom').addEventListener('input', e => setZoom(Math.exp(+e.target.value)));
$('fit').addEventListener('click', zoomFit);
$('shyBtn').addEventListener('click', () => { S.hideShy = !S.hideShy; try { localStorage.setItem('cc.hideShy:' + S.file, S.hideShy ? '1' : ''); } catch (e) { } buildTimeline(); });
$('play').addEventListener('click', () => setPlaying(!S.playing));
// 先頭へ・末尾へ（Home・End と同じ）。タイムラインの見えている所もそこへ
$('toStart').addEventListener('click', () => { seek(0); $('lanesWrap').scrollLeft = 0; });
// 1コマ送り・戻し（ボタンと、再生の操作の上のマウスホイール。Shift で1秒）。再生中なら止めてから
function stepFrames(n) { if (S.playing) setPlaying(false); seek(snapFrame(Math.max(0, Math.min(dur(), S.t + n / fps())))); followPlayhead(); }
$('stepBack').addEventListener('click', () => stepFrames(-1));
$('stepFwd').addEventListener('click', () => stepFrames(1));
$('pvScale').value = String(S.pvScale); $('pvScale').addEventListener('change', e => setPvScale(e.target.value));
$('transport').addEventListener('wheel', e => {
  e.preventDefault(); const d = e.deltaY || e.deltaX; if (!d) return;
  stepFrames((d > 0 ? 1 : -1) * (e.shiftKey ? Math.round(fps()) : 1));
}, { passive: false });
// 📐 動画の大きさ：FHD 横（1920×1080）・HD 横（1280×720）・SD 横（854×480、16:9）・FHD 縦（1080×1920）・正方形（1080×1080）。タイムラインの width・height を変える（Ctrl+Z で戻せる）
const SIZES = [[1920, 1080, $L('size.fhdH'), 'rectangle-horizontal'], [1280, 720, $L('size.hdH'), 'rectangle-horizontal'], [854, 480, $L('size.sdH'), 'rectangle-horizontal'], [1080, 1920, $L('size.fhdV'), 'rectangle-vertical'], [1080, 1080, $L('size.square'), 'square']];  // 名前は $L。印は Lucide のアイコン
function refreshSizeBtn() {
  if (!S.tl) return;
  const W = S.tl.width || 1920, H = S.tl.height || 1080, cur = SIZES.find(s => s[0] === W && s[1] === H);
  $('sizeBtn').innerHTML = `${MITTLER_ICON('ratio')} ${esc(cur ? cur[2] : `${W}×${H}`)}`;
  $('sizeMenu').innerHTML = SIZES.map(([w, h, n, ic]) => `<button data-size="${w}x${h}" class="${w === W && h === H ? 'on' : ''}">${MITTLER_ICON(ic)} ${$t('size.item', { name: n, w, h })}</button>`).join('')
    + `<div class="tdim">${$t('size.note')}</div>`;
}
$('sizeBtn').addEventListener('click', e => { e.stopPropagation(); refreshSizeBtn(); $('sizeMenu').hidden = !$('sizeMenu').hidden; });
$('sizeMenu').addEventListener('click', e => {
  const b = e.target.closest('[data-size]'); if (!b) return;
  const [w, h] = b.dataset.size.split('x').map(Number); $('sizeMenu').hidden = true;
  if (S.tl.width === w && S.tl.height === h) return;
  change(() => { S.tl.width = w; S.tl.height = h; });
  fitScreen(); refreshSizeBtn();
  setStatus($L('st.sizeSet', { w, h }), 'ok');
});
document.addEventListener('mousedown', e => { if (!e.target.closest('.sizeWrap')) $('sizeMenu').hidden = true; });

// 🔄 画面の再読み込み：タイムラインの保存を待ってから読み直す。再生位置と選んでいるクリップは引き継ぐ
$('reloadBtn').addEventListener('click', () => {
  if (S.playing) setPlaying(false);
  $('reloadBtn').disabled = true; setStatus($L('st.reloading'), 'busy');
  afterSaved(() => { try { sessionStorage.setItem('cc.reload', JSON.stringify({ t: S.t, sel: S.sel || null })); } catch (e) { } location.reload(); });
});

// 📷 表示中のコマを PNG で保存（再生中なら止めて、そのコマ）。保存先は output/stills/、押すと「📂 開く」
$('stillBtn').addEventListener('click', async () => {
  if (S.playing) setPlaying(false);
  const t = snapFrame(S.t), b = $('stillBtn'); b.disabled = true; setStatus($L('st.stillRendering', { t: fmt(t) }), 'busy');
  try {
    const body = { t };
    const r = await (await api('/api/still', { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } })).json();
    if (!r.ok) throw new Error(r.error || $t('st.codeSaveFailed'));
    S.lastStill = r.path; setStatus($L('st.stillSaved', { path: r.path, mb: (r.bytes / 1e6).toFixed(1) }), 'act');
  } catch (e) { setStatus($L('st.stillFailed', { err: e.message || e }), 'bad'); }
  finally { b.disabled = false; }
});
// 上の状態の文字（📷 保存しました…）を押すと、保存した PNG をエクスプローラーで
$('status').addEventListener('click', async () => {
  if (!S.lastStill || !statusIs('st.stillSaved')) return;
  try { await api('/api/reveal', { method: 'POST', body: JSON.stringify({ path: S.lastStill }), headers: { 'Content-Type': 'application/json' } }); } catch (e) { }
});
// 押せる知らせ（「ここを押すと…」。ボタンの形で出る）は、キーボードでも押せる（Tab で移って Enter・Space）
$('status').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && $('status').dataset.level === 'act') { e.preventDefault(); e.stopPropagation(); $('status').click(); } });
$('toEnd').addEventListener('click', () => { seek(dur()); const wr = $('lanesWrap'); wr.scrollLeft = Math.max(0, dur() * S.pps - wr.clientWidth + 80); });
$('undo').addEventListener('click', undo);
$('redo').addEventListener('click', redo);
window.addEventListener('keydown', e => {
  // Ctrl+S：保存は自動だが、押したら「何も起きない」にしない（前は VS Code やブラウザに素通しで、何も出なかった）。
  // 待っている保存があればすぐ流す。欄に打っている途中なら、欄から抜けて（＝その値を入れて）から。コードの窓の Ctrl+S（コードの保存）はそちらの決まりのまま
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 's' && e.target.id !== 'codeText') {
    e.preventDefault();
    const a = document.activeElement; if (a && a.closest && a.closest('input,textarea,select')) a.blur();
    setTimeout(saveNow, 0); return;
  }
  if (e.target.closest && e.target.closest('input,textarea,select')) return;
  const k = e.key, ctl = e.ctrlKey || e.metaKey, C = window.MITTLER_CUT, lk = k.toLowerCase(); let used = true;
  if (k === ' ') setPlaying(!S.playing);
  else if (e.altKey && (k === 'ArrowRight' || k === 'ArrowLeft') && C) C.nudge((k === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 10 : 1));  // 選んだクリップを1コマ（Shift で10コマ）
  else if ((k === 'ArrowUp' || k === 'ArrowDown') && C) C.jumpEdit(k === 'ArrowDown' ? 1 : -1);  // 前・次の編集点（クリップの端）
  else if (ctl && lk === 'k' && C) C.splitAtPlayhead(e.shiftKey);
  else if (ctl && lk === 'c' && C) C.copy();
  else if (ctl && lk === 'v' && C) C.paste();
  else if (ctl && lk === 'd' && C) C.duplicate();
  else if (ctl && lk === 'a' && C) C.selectAll();
  else if (ctl && ((lk === 'z' && e.shiftKey) || lk === 'y')) redo();
  else if (!ctl && !e.altKey && C && (lk === 'v' || lk === 'c' || lk === 'y')) C.setTool({ v: 'select', c: 'razor', y: 'slip' }[lk]);
  else if (k === 'ArrowRight') seek(snapFrame(S.t + (e.shiftKey ? 1 : 1 / fps())));
  else if (k === 'ArrowLeft') seek(snapFrame(S.t - (e.shiftKey ? 1 : 1 / fps())));
  else if (k === 'Home') $('toStart').click(); else if (k === 'End') $('toEnd').click();
  else if (k === 'Escape') { select(null); if (window.MITTLER_CUT) MITTLER_CUT.setTool('select'); }
  else if ((k === 'f' || k === 'F') && !e.ctrlKey && !e.metaKey) zoomFit();
  else if ((k === 's' || k === 'S') && !e.ctrlKey && !e.metaKey) $('snapBtn').click();
  else if ((k === 'Delete' || k === 'Backspace') && S.metaSel) deleteMetaSel();
  else if ((k === 'Delete' || k === 'Backspace') && selIds().length && window.MITTLER_CUT) { if (e.shiftKey) MITTLER_CUT.rippleDelete(); else MITTLER_CUT.deleteSel(); }
  else if ((k === 'Delete' || k === 'Backspace') && S.selTrack && window.MITTLER_DEL_TRACK) { const tr = S.tl.tracks.find(t => t.id === S.selTrack); if (tr) MITTLER_DEL_TRACK(tr); }  // 選んだトラックを消す（クリップがあれば2回）
  else if (lk === 'z' && ctl) undo();
  else used = false;
  if (used) e.preventDefault();
});
window.addEventListener('resize', () => { fitScreen(); if (S.tl) { if (S.pps < fitPps()) setZoom(fitPps()); else zoomRange(); } });

// 変更通知：タイムライン（自分の保存でなければ読み直す）・エフェクトのコード・スクリプト・素材
function listen() {
  const es = new EventSource('/api/events');
  es.addEventListener('change', async ev => {
    const kinds = JSON.parse(ev.data).kinds;
    let redraw = kinds.includes('effect');
    if (kinds.includes('timeline') && !S.saveTimer && !S.saving) {
      const e0 = S.edits;
      const r = await fetch('/api/timeline', { cache: 'no-store' }); const j = await r.json();
      // 読んでいるあいだに画面で直していたら、読んだ中身（古い）で上書きしない（自分の保存の通知はあとで届く）
      if (S.edits === e0 && !S.saveTimer && !S.saving && JSON.stringify(j.timeline) !== JSON.stringify(S.tl)) {  // 外（Claude Code など）で直された
        // 読み直す前の中身を取り消しの記録に積む（外の直しも 1 回の単位。undo）。やり直しの記録は、画面で直したときと同じく捨てる
        S.undo.push({ tl: JSON.stringify(S.tl), ext: true }); if (S.undo.length > 200) S.undo.shift(); S.redo = [];
        const prevTl = S.tl;
        S.tl = j.timeline; S.lastSaved = JSON.stringify(S.tl); if (S.sel && !findClip(S.sel)) S.sel = null;
        // 再生用の動画（preview.proxy）が外で変わった（API の proxy・export）：読み込み直す
        const src = S.tl.preview && S.tl.preview.proxy ? projUrl(S.tl.preview.proxy) : '';
        if ($('proxy').getAttribute('src') !== src) { if (src) $('proxy').setAttribute('src', src); else $('proxy').removeAttribute('src'); }
        buildTimeline(); showSelSafe(); buildGradePanel(); buildMetaPanel(); setStatus($L('st.extReloaded'), 'ok'); redraw = true; S.ver++;
        if (window.MITTLER_FOLLOW) MITTLER_FOLLOW.onExternal(prevTl, S.tl);  // AI を追う（オートモード）：変わったクリップの真ん中へ（editor/remote.js）
      }
    }
    if (kinds.includes('effect')) { loadEffects(); S.ver++; }
    if (kinds.includes('characters')) { await loadChars(); buildTimeline(); showSelSafe(); }
    // 絵・動画のファイルが変わった（同じ名前で上書きも）：URL の印を変えて、サムネ・テイクの絵（plan.js）・プレビューを読み直す
    if (kinds.includes('media')) { S.assetVer++; buildTimeline(); redraw = true; S.ver++; }
    if (window.MITTLER_ON_CHANGE) window.MITTLER_ON_CHANGE(kinds);
    if (redraw) invalidateExact();
  });
  // API の見える操作（tools/mittler_api.py の ui。サーバー → 編集画面）：editor/remote.js がして、/api/ui/<id>/done で答える
  es.addEventListener('ui', ev => { if (window.MITTLER_REMOTE) MITTLER_REMOTE.run(JSON.parse(ev.data)); });
}
async function pollStatus() {
  try {
    const st = await (await api('/api/status', { cache: 'no-store' })).json();
    // error・note はサーバーが今の言葉で返す（server/pyrender.js）
    if (!st.ready) { if (st.error) setStatus($L('st.renderer', { err: st.error }), 'bad', { toast: false }); else setStatus($L('st.rendererStarting'), 'busy'); setTimeout(pollStatus, 2000); return; }
    if (st.note) setStatus(st.note); else setStatus(S.reloaded ? $L('st.reloaded') : '', S.reloaded ? 'ok' : ''); loadEffects(); invalidateExact();  // note：描画サーバーからの知らせ（あれば）
  } catch (e) { setTimeout(pollStatus, 3000); }
}
// 画面の言葉を切り替えたら（上のバーの EN／日本語。editor/i18n.js）：その場で作り直す（開き直さない）。ほかのファイルの部品は、それぞれが MITTLER_I18N.onChange で作り直す
MITTLER_I18N.onChange(() => {
  if (!S.tl) return;
  paintStatus(); if (S.srcMsg != null) showSrc(S.srcMsg);
  $('file').title = $t('file.title', { name: S.tl.name || '', file: S.file });
  buildTimeline(); showSelSafe(); buildGradePanel(); buildMetaPanel(); refreshSnapUI(); refreshDurBtn(); refreshSizeBtn(); draw();
});

(async () => {
  await loadTimeline();
  let p0 = 'sel'; try { p0 = localStorage.getItem('cc.pane') || 'sel'; } catch (e) { }
  showPane(p0);
  if (window.MITTLER_MEDIA_INIT) window.MITTLER_MEDIA_INIT();
  if (window.MITTLER_CUT) window.MITTLER_CUT.init();  // カット編集の道具のバー
  if (window.MITTLER_ASSETS) window.MITTLER_ASSETS.load();
  if (window.MITTLER_ASSETS) window.MITTLER_ASSETS.setOpen(null);  // アセット窓（閉じていたら閉じたまま）
  buildGradePanel(); pollStatus(); draw();
  try {  // 🔄 で読み直したとき：前の再生位置と選んでいたクリップに戻す
    const rl = JSON.parse(sessionStorage.getItem('cc.reload') || 'null'); sessionStorage.removeItem('cc.reload');
    if (rl) { seek(+rl.t || 0); if (rl.sel && findClip(rl.sel)) select(rl.sel); S.reloaded = true; setStatus($L('st.reloaded'), 'ok'); }
  } catch (e) { }
  listen(); window.MITTLER_EDITOR = S; S.seek = seek; S.select = select; S.change = change;
  Object.assign(S, { setPlaying, stepFrames, showPane, setZoom, zoomFit, fitPps, undoNow: undo, redoNow: redo, followPlayhead });  // API の見える操作（editor/remote.js）が使う
})();
