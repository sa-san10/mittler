// Mittler：🎬 動画化予定のプロンプトの参照（CSS の @import 風。書き方は docs/タイムライン形式.md の plan）を読んで、生成に送るものを組み立てる。
//   @import char(kurochan) as クロ;          キャラ：立ち絵（characters.json の images[差分] か image）＋外見の文（look、無ければ profile）
//   @import char(achao, smile) as あちゃ;    立ち絵の差分
//   @import image("assets/images/room.png") as 部屋;
//   @import frame(start);  frame(plan_002, end);   自分／ほかの予定クリップの開始・終了の絵
//   @import style(anime-cel);                作品の styles/anime-cel.md の文（省略せずに足す）
//   @import audio("assets/voice/x.wav", 1.20s, 4.50s);  audio(tts_p01_s01_t01);  audio(here);   声の参照（動画のプロンプトだけ）
// 1行に「;」で区切って何個書いてもよい。@import で始まらない行が本文。
// まちがい・注意の文（errors・warnings）は ctx.lang の言葉（無ければ日本語）。送るプロンプト（【参照】・参照画像N・声などの名前）は言葉を切り替えても変えない（生成の結果が変わらないように）
'use strict';
const fs = require('fs');
const path = require('path');
const I18N = require('./i18n');

const IMPORT_RE = /^@import\s+([a-z]+)\s*\((.*)\)\s*(?:as\s+(\S+?))?\s*$/i;

// 「,」で区切る（"…" の中の「,」は区切らない）。前後の空白と引用符を取る
function splitArgs(s) {
  const out = []; let cur = '', q = null;
  for (const ch of s) {
    if (q) { if (ch === q) q = null; else cur += ch; continue; }
    if (ch === '"' || ch === "'") { q = ch; continue; }
    if (ch === ',') { out.push(cur.trim()); cur = ''; continue; }
    cur += ch;
  }
  if (cur.trim() || out.length) out.push(cur.trim());
  return out;
}
const secs = v => { const m = /^(-?[\d.]+)\s*s?$/i.exec(String(v).trim()); return m ? parseFloat(m[1]) : NaN; };

function parse(text, lang) {
  const imports = [], body = [];
  for (const line of String(text || '').split(/\r?\n/)) {
    if (!/^\s*@import\b/i.test(line)) { body.push(line); continue; }
    for (const part of line.split(';').map(x => x.trim()).filter(Boolean)) {
      const m = IMPORT_RE.exec(part);
      if (!m) { imports.push({ src: part, error: I18N.tr(lang || 'ja', 'pr.syntax') }); continue; }
      imports.push({ src: part, kind: m[1].toLowerCase(), args: splitArgs(m[2]), alias: m[3] || '' });
    }
  }
  return { imports, body: body.join('\n').trim() };
}

// ctx：{ root（素材の根の絶対パス）, project（作品のフォルダ）, tl（タイムライン）, chars（characters.json の中身）, clip（この予定クリップ）, which（start_frame｜end_frame｜video） }
function resolve(text, ctx) {
  const L = (k, v) => I18N.tr(ctx.lang || 'ja', k, v);
  const { imports, body } = parse(text, ctx.lang);
  const plans = (ctx.tl.tracks || []).flatMap(t => t.clips || []).filter(c => c.type === 'plan');
  const chars = (ctx.chars && ctx.chars.characters) || [];
  const exists = rel => !!rel && fs.existsSync(path.join(ctx.root, rel));
  for (const im of imports) {
    if (im.error) continue;
    const a = im.args;
    if (im.kind === 'char') {
      const c = chars.find(x => x.id === a[0]) || chars.find(x => x.name === a[0]);
      if (!c) { im.error = L('pr.noChar', { c: a[0] }); continue; }
      const variant = a[1] || 'default';
      const img = (c.images || {})[variant] || (variant === 'default' ? c.image : null);
      if (a[1] && !img) { im.error = L('pr.noVariant', { name: c.name, v: a[1] }); continue; }
      im.name = c.name; im.alias = im.alias || c.name; im.text = c.look || c.profile || '';
      if (img) { if (exists(img)) im.image = img; else im.warn = L('pr.noStand', { img }); }
    } else if (im.kind === 'image') {
      if (!a[0]) { im.error = L('pr.noImagePath'); continue; }
      if (!exists(a[0])) { im.error = L('pr.noImage', { p: a[0] }); continue; }
      im.image = a[0]; im.alias = im.alias || path.basename(a[0]).replace(/\.\w+$/, '');
    } else if (im.kind === 'frame') {
      const [x, y] = a.length >= 2 ? [a[0], a[1]] : [null, a[0]];
      const end = (y || '').toLowerCase();
      if (end !== 'start' && end !== 'end') { im.error = L('pr.frameSyntax'); continue; }
      const c = x ? plans.find(p => p.id === x || p.label === x) : ctx.clip;
      if (!c) { im.error = L('pr.noPlan', { x }); continue; }
      if (c === ctx.clip && ctx.which === end + '_frame') { im.error = L('pr.self'); continue; }
      const src = (c[end + '_frame'] || {}).src;
      if (!src) { im.error = x ? L('pr.noFrameOf.' + end, { label: c.label || c.id }) : L('pr.noFrame.' + end); continue; }
      if (!exists(src)) { im.error = L('pr.noFrameFile', { src }); continue; }
      im.image = src; im.alias = im.alias || `${x ? (c.label || c.id) + 'の' : ''}${end === 'start' ? 'スタート' : 'エンド'}の絵`;
    } else if (im.kind === 'style') {
      const f = path.join(ctx.project, 'styles', `${a[0]}.md`);
      if (!a[0] || !fs.existsSync(f)) { im.error = L('pr.noStyle', { s: a[0] || '?' }); continue; }
      im.text = fs.readFileSync(f, 'utf8').trim(); im.alias = im.alias || a[0];
    } else if (im.kind === 'audio') {
      if (ctx.which !== 'video') { im.error = L('pr.audioVideoOnly'); continue; }
      if (a[0] === 'here') im.audio = { here: true };
      else if (a.length >= 3) {
        const t0 = secs(a[1]), t1 = secs(a[2]);
        if (!exists(a[0])) { im.error = L('pr.noAudio', { p: a[0] }); continue; }
        if (!(t1 > t0 && t0 >= 0)) { im.error = L('pr.badCut'); continue; }
        im.audio = { src: a[0], in: t0, out: t1 };
      } else {
        const c = (ctx.tl.tracks || []).flatMap(t => t.clips || []).find(x => x.id === a[0] && x.type === 'tts');
        if (!c) { im.error = L('pr.noTts', { id: a[0] }); continue; }
        const tk = (c.takes || []).find(k => k.id === c.activeTake);
        if (!tk) { im.error = L('pr.notGen', { id: a[0] }); continue; }
        im.audio = { src: tk.src, in: c.in || 0, out: (c.in || 0) + c.dur, clip: c.id };
      }
      im.alias = im.alias || '声';
    } else im.error = L('pr.unknown', { k: im.kind });
  }
  // 送るもの：本文＋参照の説明（画像は「参照画像N」の順に渡す）＋画風の文
  const refs = [], lines = [], styles = [], audio = [];
  for (const im of imports) {
    if (im.error) continue;
    if (im.image) { let i = refs.indexOf(im.image); if (i < 0) { refs.push(im.image); i = refs.length - 1; } im.n = i + 1; }  // 同じ画像は1枚にまとめる
    if (im.kind === 'char') lines.push(`・${im.alias}${im.alias !== im.name ? `（${im.name}）` : ''}${im.n ? `＝参照画像${im.n}` : ''}${im.text ? `：${im.text}` : ''}`);
    else if (im.kind === 'image' || im.kind === 'frame') lines.push(`・${im.alias}＝参照画像${im.n}`);
    else if (im.kind === 'style') styles.push(im.text);
    else if (im.kind === 'audio') audio.push(im.audio);
  }
  let full = body;
  if (lines.length) full += `\n\n【参照】\n${lines.join('\n')}`;
  if (styles.length) full += `\n\n【画風】\n${styles.join('\n\n')}`;
  const errors = imports.filter(im => im.error).map(im => im.src + L('sep.who') + im.error);
  const warnings = imports.filter(im => im.warn).map(im => im.src + L('sep.who') + im.warn);
  return { imports, body, prompt: full.trim(), refs, audio, errors, warnings };
}

module.exports = { parse, resolve };
