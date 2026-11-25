// Mittler：🎵 Suno の曲の受け取り口（機能追加案02 v2「Suno 連携は AI 主導・拡張は倉庫に徹する」）。
// 拡張（このサーバー・編集画面）は Suno を一切呼ばない（OAuth も MCP クライアントも無い）。Suno を呼ぶのは VS Code の横の Claude Code（AI）だけ。
// ここがするのは、AI が作った曲のテイク（suno.com の URL・Suno の id・プロンプト・解析）と、採用のときに AI が取ってきたファイルを、
// 確かめてから受け取り（作品の状態フォルダ .mittler（古い作品は .claude-cut）の music.json に積む）、編集画面に知らせること。テイクに入れる・クリップの src を替えるのは編集画面（タイムラインを書くのは1か所）。
// 受け渡しの形の正本は docs/Suno受け渡し契約.md の「Mittler 側の受け渡し」。
'use strict';
const fs = require('fs');
const path = require('path');
const ATOMIC = require('./atomic');  // ファイルの置きかえ（開かれていて失敗したら短く待ってやり直す）
const crypto = require('crypto');
const I18N = require('./i18n');      // 断る理由・知らせの文（鍵は srv.mu.*。例外は鍵つき＝サーバーが今の言葉で返す）
const KE = I18N.keyedError, L = I18N.L;

// 開いてよい URL はこの形だけ（suno.com の曲のページ。id は UUID）。ほかの URL は開かない
const SONG_URL = /^https:\/\/suno\.com\/song\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const AUDIO_EXT = new Set(['.wav', '.mp3']);
const songUrlOk = u => typeof u === 'string' && SONG_URL.test(u);

// audio-analysis の返り値 → Mittler が読む形 {status, bpm, key, time_signature, beats: [[秒, 小節の中の位置 1〜]], sections: [{start, end, label}], terms, labels}。
// 返り値の入れ子の形は確かめきれていない（拍・構成・説明は別々の run）ので、名前で探す（いちばん浅いところから）。読めなければ null
// ok：値の形の条件（例 beats は配列。{beats: {bpm, beats: [...]}} のような入れ子では、配列のほうを取る）
function findKey(o, key, ok = () => true, depth = 0) {
  if (!o || typeof o !== 'object' || Array.isArray(o) || depth > 4) return undefined;
  if (Object.prototype.hasOwnProperty.call(o, key) && ok(o[key])) return o[key];
  for (const v of Object.values(o)) { if (v && typeof v === 'object' && !Array.isArray(v)) { const r = findKey(v, key, ok, depth + 1); if (r !== undefined) return r; } }
  return undefined;
}
const num = v => (typeof v === 'number' && isFinite(v) ? v : typeof v === 'string' && v.trim() && isFinite(+v) ? +v : null);
function normAnalysis(a) {
  if (!a || typeof a !== 'object') return null;
  const out = { status: typeof a.status === 'string' ? a.status : (findKey(a, 'status') || null) };
  const bpm = num(findKey(a, 'bpm', v => num(v) != null)); if (bpm != null) out.bpm = bpm;
  const key = findKey(a, 'key', v => typeof v === 'string' || v === null); if (key !== undefined) out.key = key;
  const ts = findKey(a, 'time_signature', v => typeof v === 'number' || typeof v === 'string'); if (ts !== undefined) out.time_signature = ts;
  const isList = v => Array.isArray(v);
  const beats = findKey(a, 'beats', isList);
  if (Array.isArray(beats)) {
    out.beats = beats.map(b => {
      if (Array.isArray(b)) return [num(b[0]), num(b[1])];
      if (b && typeof b === 'object') return [num(b.time_s != null ? b.time_s : b.time != null ? b.time : b.start_s != null ? b.start_s : b.t), num(b.bar_position != null ? b.bar_position : b.position)];
      return [num(b), null];
    }).filter(b => b[0] != null && b[0] >= 0).map(b => [+b[0].toFixed(4), b[1] == null ? 0 : Math.round(b[1])]).sort((x, y) => x[0] - y[0]);
  }
  const secs = findKey(a, 'sections', isList);
  if (Array.isArray(secs)) {
    out.sections = secs.filter(s => s && typeof s === 'object').map(s => {
      const st = num(s.start_s != null ? s.start_s : s.start), du = num(s.duration_s);
      const en = num(s.end_s != null ? s.end_s : s.end) != null ? num(s.end_s != null ? s.end_s : s.end) : st != null && du != null ? st + du : null;
      return { start: st, end: en, label: s.label != null ? String(s.label) : s.name != null ? String(s.name) : '' };
    }).filter(s => s.start != null && s.end != null && s.end > s.start).map(s => ({ start: +s.start.toFixed(4), end: +s.end.toFixed(4), label: s.label }));
  }
  for (const k of ['terms', 'labels']) { const v = findKey(a, k, isList); if (v) out[k] = v; }
  return out;
}

// audio-lyrics-alignment の返り値（{status, words: [{word, start_s, end_s, success, …}]}。2026-11-15 の MCP の説明：status は complete・processing・unavailable、
// 置けなかった単語は success: false で隣からの推定の区間、インスト曲は words が空）→ {status, words: [[始め, 終わり, 字, 置けたか]], lines: [{start, end, text, bad}]}。
// 行は、単語の字に改行があるところで切る（Suno の単語は行の終わりに "\n" を持つ）。[Verse] のような構成のメモの単語は行にしない。読めなければ null
function normAlignment(a) {
  if (!a || typeof a !== 'object') return null;
  const ws = findKey(a, 'words', v => Array.isArray(v)) || findKey(a, 'aligned_words', v => Array.isArray(v)) || (Array.isArray(a) ? a : null);
  const out = { status: typeof a.status === 'string' ? a.status : (findKey(a, 'status') || null), words: [], lines: [] };
  if (!Array.isArray(ws)) return out;
  for (const w of ws) {
    if (!w || typeof w !== 'object') continue;
    const s = num(w.start_s != null ? w.start_s : w.start), e = num(w.end_s != null ? w.end_s : w.end), t = String(w.word != null ? w.word : w.text != null ? w.text : '');
    if (s == null || e == null) continue;
    out.words.push([+s.toFixed(4), +Math.max(e, s).toFixed(4), t, w.success !== false]);
  }
  out.words.sort((x, y) => x[0] - y[0]);
  // 行：{start, end, text, bad（置けなかった単語の数）, w：[最初の単語の番号, 最後の次]}
  let cur = null;
  const flush = i => { if (cur && cur.text.trim()) out.lines.push({ start: cur.start, end: cur.end, text: cur.text.replace(/\s+/g, ' ').trim(), bad: cur.bad, w: [cur.w0, i] }); cur = null; };
  out.words.forEach(([s, e, t, ok], i) => {
    const clean = t.replace(/\[[^\]]*\]/g, '');
    if (clean.trim()) {
      if (!cur) cur = { start: s, end: e, text: '', bad: 0, w0: i };
      cur.text += clean.replace(/\n/g, ' '); cur.end = Math.max(cur.end, e); if (!ok) cur.bad++;
    }
    if (/\n/.test(t)) flush(i + 1);
  });
  flush(out.words.length);
  return out;
}

// opts：{ project, readTimeline, inside, hiddenIn, probeDur, notify, log, stateDir, openExternal }
function create(o) {
  const file = () => path.join(o.stateDir(), 'music.json');
  let list = [];
  try { list = JSON.parse(fs.readFileSync(file(), 'utf8')); if (!Array.isArray(list)) list = []; } catch (e) { list = []; }
  const save = () => { fs.mkdirSync(o.stateDir(), { recursive: true }); const f = file(), tmp = f + '.part'; fs.writeFileSync(tmp, JSON.stringify(list.slice(-100), null, 1)); ATOMIC.replace(tmp, f); };
  const safe = s => String(s).replace(/[^A-Za-z0-9_-]/g, '_');

  // 作品の中のファイル（素材の根からの相対パス）。作品の外・隠しフォルダ（.git・状態フォルダ .mittler・.claude-cut）は理由つきで断る
  function rel(root, p, whatKey) {
    const s = String(p || '').trim(), what = L(whatKey);
    if (!s) throw KE('srv.mu.noPath', { what });
    if (path.isAbsolute(s) || /^[A-Za-z]:/.test(s) || s.split(/[\\/]/).includes('..')) throw KE('srv.mu.outsideRoot', { what, s, root });
    const f = o.inside(root, s);
    if (!f) throw KE('srv.mu.outside', { what, s });
    if (o.hiddenIn(root, f)) throw KE('srv.mu.hidden', { what, s });
    if (!fs.existsSync(f) || !fs.statSync(f).isFile()) throw KE('srv.mu.notFound', { what, s });
    return { abs: f, rel: path.relative(root, f).split(path.sep).join('/') };
  }
  function clipOf(tl, id) {
    const c = (tl.tracks || []).flatMap(t => t.clips || []).find(x => x.id === id);
    if (!c) throw KE('srv.mu.noClip', { id });
    if (c.type !== 'audio') throw KE('srv.mu.notAudio', { id, type: c.type });
    return c;
  }
  const pendingTakes = clip => list.filter(d => !d.applied && d.clip === clip && d.kind === 'take');
  // テイクの名前：t<n>（クリップのテイク・まだ編集画面が入れていない納品・assets/music/<クリップ>_t<n>.* と重ならない最小の次の番号）
  function nextTake(root, c) {
    const used = new Set([...((c.music || {}).takes || []).map(k => k.id), ...pendingTakes(c.id).map(d => d.take)]);
    let n = 0; for (const id of used) { const m = /^t(\d+)$/.exec(id || ''); if (m) n = Math.max(n, +m[1]); }
    const dir = path.join(root, 'assets', 'music');
    let names = []; try { names = fs.readdirSync(dir); } catch (e) { }
    for (n = n + 1; used.has('t' + n) || names.some(x => x.startsWith(`${safe(c.id)}_t${n}.`)); n++);
    return 't' + n;
  }
  async function audioFile(root, src) {
    const f = rel(root, src, 'srv.mu.what.audio');
    const ext = path.extname(f.abs).toLowerCase();
    if (!AUDIO_EXT.has(ext)) throw KE('srv.mu.ext', { p: f.rel });
    const dur = await o.probeDur(f.abs).catch(() => 0);
    if (!(dur > 0)) throw KE('srv.mu.unreadable', { p: f.rel });
    return { rel: f.rel, abs: f.abs, format: ext.slice(1), dur: +dur.toFixed(3) };
  }
  function readSidecar(root, p) {
    const f = rel(root, p, 'srv.mu.what.sidecar');
    let j; try { j = JSON.parse(fs.readFileSync(f.abs, 'utf8')); } catch (e) { throw KE('srv.mu.scJson', { p: f.rel, err: e.message }); }
    if (!j || typeof j !== 'object' || Array.isArray(j)) throw KE('srv.mu.scObj', { p: f.rel });
    if (j.source !== 'suno-mcp') throw KE('srv.mu.scSource', { p: f.rel });
    if (!UUID.test(String(j.suno_id || ''))) throw KE('srv.mu.scId', { p: f.rel });
    if (!songUrlOk(j.song_url)) throw KE('srv.mu.scUrl', { p: f.rel });
    if (SONG_URL.exec(j.song_url)[1] !== j.suno_id) throw KE('srv.mu.scMismatch', { p: f.rel });
    return { j, f };
  }
  const writeJson = (f, j) => { fs.mkdirSync(path.dirname(f), { recursive: true }); const tmp = f + '.part'; fs.writeFileSync(tmp, JSON.stringify(j, null, 1) + '\n'); ATOMIC.replace(tmp, f); };

  // POST /api/music/take
  //   新しいテイク：{clip, sidecar[, src]}（src は、もうファイルを取ってあるとき）
  //   採用のファイル：{clip, take, src}（そのテイクの音のファイル。採用待ちなら、編集画面がクリップの src をこれにする）
  async function take(q) {
    const tl = o.readTimeline(), root = path.resolve(o.project, tl.root || '.');
    const c = clipOf(tl, String(q.clip || ''));
    const id = 'mu_' + new Date().toISOString().replace(/[-:T.Z]/g, '').slice(0, 14) + '_' + crypto.randomBytes(3).toString('hex');
    const now = new Date().toISOString();
    if (q.take) {
      const tk = String(q.take);
      const k = ((c.music || {}).takes || []).find(x => x.id === tk) || (pendingTakes(c.id).find(d => d.take === tk) || {}).data;
      if (!k) throw KE('srv.mu.noTake', { id: c.id, tk });
      const a = await audioFile(root, q.src);
      const side = k.sidecar && o.inside(root, k.sidecar);
      if (side && fs.existsSync(side)) {  // サイドカー（このサーバーが書いたもの）にファイルを書き足す
        try { const j = JSON.parse(fs.readFileSync(side, 'utf8')); Object.assign(j, { src: a.rel, format: a.format, dur_file: a.dur, downloaded: now }); writeJson(side, j); } catch (e) { o.log('サイドカーを書き足せない: ' + e.message); }
      }
      const adopt = (c.music || {}).adopt;
      const d = { id, kind: 'file', clip: c.id, take: tk, src: a.rel, format: a.format, dur: a.dur, created: now, applied: false };
      list.push(d); save(); o.notify('music');
      o.log(`曲のファイルを受け取った：${c.id} の ${tk} → ${a.rel}（${a.dur} 秒）`);
      return { ok: true, id, clip: c.id, take: tk, src: a.rel, dur: a.dur,
        note: I18N.tr(o.lang ? o.lang() : 'ja', adopt && adopt.take === tk ? 'srv.mu.noteAdopt' : 'srv.mu.noteAttach') };
    }
    if (!q.sidecar) throw KE('srv.mu.noSidecar');
    const { j } = readSidecar(root, q.sidecar);
    const known = [...((c.music || {}).takes || []), ...pendingTakes(c.id).map(d => d.data)].find(k => k && k.suno_id === j.suno_id);
    if (known) throw KE('srv.mu.dup', { sid: j.suno_id, id: c.id, tk: known.id || '' });
    const a = q.src ? await audioFile(root, q.src) : null;
    const tk = nextTake(root, c);
    const canon = `assets/music/${safe(c.id)}_${tk}.suno.json`;
    const side = Object.assign({}, j, { clip: c.id, take: tk, delivered: now }, a ? { src: a.rel, format: a.format, dur_file: a.dur, downloaded: now } : {});
    writeJson(path.join(root, ...canon.split('/')), side);
    const an = normAnalysis(j.analysis), al = normAlignment(j.lyrics_alignment);
    // 注意（受け取りは断らない＝もう作ってしまったもの）：生成の引数 create_args が無い・同じ生成の 2 本目（同じ created・同じ create_args）
    // （2026-11-15：今の Suno MCP の audio-create には clip_count が無く、suno.com のサインインでは 1 回で必ず 2 本できる。1 本だけは頼めない）
    const warnings = [], lang = o.lang ? o.lang() : 'ja';
    if (!j.create_args || typeof j.create_args !== 'object') warnings.push(I18N.tr(lang, 'srv.mu.warnNoArgs'));
    else if (j.create_args.clip_count != null && +j.create_args.clip_count !== 1) warnings.push(I18N.tr(lang, 'srv.mu.warnClipCount', { n: j.create_args.clip_count }));
    const sameGen = [...((c.music || {}).takes || []), ...pendingTakes(c.id).map(d => d.data)].find(k => k && j.created && k.created === j.created && j.create_args &&
      JSON.stringify(k.create_args || null) === JSON.stringify(j.create_args));
    if (sameGen) warnings.push(I18N.tr(lang, 'srv.mu.warnSameGen', { tk: sameGen.id }));
    const data = { id: tk, suno_id: j.suno_id, song_url: j.song_url, title: j.title || '', prompt: j.prompt || '', style: j.style || '', model: j.model || '',
      created: j.created || now, sidecar: canon };
    for (const k of ['lyrics', 'instrumental']) if (j[k] != null) data[k] = j[k];
    if (num(j.dur) != null) data.dur = num(j.dur); else if (a) data.dur = a.dur;
    if (num(j.credits) != null) data.credits = num(j.credits);
    if (an) data.analysis = an;
    if (al) data.lyrics_alignment = al;  // 歌詞の単語・行の時刻（採用のときに編集画面が歌詞のメタデータに入れる。editor/music.js の putMeta）
    if (j.create_args && typeof j.create_args === 'object') data.create_args = j.create_args;
    if (a) Object.assign(data, { src: a.rel, format: a.format, downloaded: now });
    const d = { id, kind: 'take', clip: c.id, take: tk, data, created: now, applied: false };
    list.push(d); save(); o.notify('music');
    o.log(`曲のテイクを受け取った：${c.id} の ${tk}（Suno ${j.suno_id}${a ? '・' + a.rel : ''}）` + (warnings.length ? ' 注意：' + warnings.join(' / ') : ''));
    return { ok: true, id, clip: c.id, take: tk, sidecar: canon, file: `assets/music/${safe(c.id)}_${tk}.wav`, analysis: an ? { status: an.status, bpm: an.bpm, beats: (an.beats || []).length, sections: (an.sections || []).length } : null,
      lyrics_alignment: al ? { status: al.status, words: al.words.length, lines: al.lines.length, uncertain: al.words.filter(w => !w[3]).length } : null, warnings };
  }
  function applied(id) { const d = list.find(x => x.id === id); if (d) { d.applied = true; save(); } return !!d; }
  // ▶ suno.com で聞く：ユーザーのブラウザ（VS Code の外の既定のブラウザ）で曲のページを開く。https://suno.com/song/<id> の形だけ
  function open(url) {
    if (!songUrlOk(url)) throw KE('srv.mu.badUrl');
    const how = o.openExternal(url);
    o.log(`suno.com の曲のページを開く（${how}）: ${url}`);
    return { ok: true, how };
  }
  return { take, applied, open, list: () => list };
}

module.exports = { create, normAnalysis, normAlignment, songUrlOk, SONG_URL };
