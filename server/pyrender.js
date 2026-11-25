// Mittler: Python エンジンのタイムライン（format "mittler/py1"。前の名前の "claude-cut/py1" も同じ形）を、このPCの描画サーバー（`python -m mittler serve`、127.0.0.1 だけ）で描く。
// - 起動：このPCで描ける python を決めて、描画サーバーを起動する。描画サーバーは作品のファイルをそのまま読む（タイムライン・effects が変われば自分で読み直す）。
//   python：設定の python（VS Code の mittler.render.python、単体は --render-python）があればそれ。無ければ、タイムラインの render.python → PATH の python の順に
//   numpy・opencv・Pillow を import できるものを探す。
// - 1コマは GET http://127.0.0.1:<port>/frame?t= を中継する。
// - 描画サーバーが途中で止まったら、次に1コマ頼んだときに別のポートで起動し直す。
// ほかの PC（GPU のあるデスクトップなど）で描くときは、VS Code の Remote-SSH でその PC に接続して作品を開く（拡張もこのサーバーもその PC で動く）。
// 拡張が自分で ssh する「ssh のモード」（送り係・ssh のポート転送）は 2026-10-30 に外した。
'use strict';
const { spawn, execFile } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

const I18N = require('./i18n');
const KE = I18N.keyedError, L = I18N.L;

const ROOT = path.resolve(__dirname, '..');
const newPort = () => 47900 + Math.floor(Math.random() * 90);
// 止まった理由の文：st.error は日本語（ログ・前からの読み手のため）、st.err は鍵つきの例外（サーバーが /api/status で今の言葉に直して返す）

// タイムラインに書かれた python（render.python・settings.analysis_python）を子プロセスとして起動する前の確かめ（決まりは docs/インストールガイド.md「タイムラインに書かれた python」）。
// 通すのは「名前だけの python（PATH から探す）」か「この PC に実在するファイルの絶対パスで、ファイルの名前が python（python.exe・python3.12・pythonw.exe など）」。
// 通らなければ理由（I18N.L の入れ子の鍵。文字にすると日本語、鍵つきの例外の値にすると画面の言葉）、通れば ''。PC の設定（VS Code の mittler.* ・単体の --render-python など）はその PC の人が書いたものなので確かめない
const PY_NAME = /^python(w)?(\d+(\.\d+)*)?(\.exe)?$/i;
function checkPython(v) {
  const s = String(v == null ? '' : v).trim();
  if (!s) return L('srv.py.empty');
  if (!/[\\/]/.test(s)) return PY_NAME.test(s) ? '' : L('srv.py.notPython', { s });
  if (!path.isAbsolute(s)) return L('srv.py.notAbs', { s });
  if (!PY_NAME.test(path.basename(s))) return L('srv.py.notPythonFile', { s: path.basename(s) });
  try { if (!fs.statSync(s).isFile()) return L('srv.py.notFile', { s }); } catch (e) { return L('srv.py.missing', { s }); }
  return '';
}

// opts: { project, timelineName, render: { python }（タイムラインの render）, defaultPython（タイムラインに render.python が無いときの既定）,
//         defaultFfmpegDirs（PC の設定の ffmpegDir が無いときに探すフォルダ。既定値は server/defaults.js）,
//         local: { python, ffmpegDir }（PC ごとの設定。空でもよい）, log }
function start(opts) {
  const { project, timelineName, render = {}, log = () => { } } = opts;
  const hint = opts.local || {};
  let local = null;  // 描く python が決まったら { python, ffmpegDir }
  const st = { ready: false, error: '', note: '', proc: null, port: newPort(), dead: false, launches: 0 };

  // ffmpeg・ffprobe（1コマ目の絵・長さ・再生用の動画。手元のサーバーも使う）
  function usePath(l) {
    if (l && l.ffmpegDir && !String(process.env.PATH).split(path.delimiter).includes(l.ffmpegDir)) process.env.PATH = l.ffmpegDir + path.delimiter + process.env.PATH;
  }

  // 描く python を決める。設定の python はそのまま使う。無ければ、順に試して import できたものを使う（結果は覚えておく。見つからなかったときは 5 分たったらもう一度）
  // タイムラインの render.python：PC の設定があればそちらが勝つ（違えばログで知らせる）。設定が無ければ、確かめて（checkPython）通ったものだけ候補にする
  let probe = null, probeAt = 0, hintOk = false, hintBad = null, warnedTl = false;
  const canImport = py => new Promise(res => execFile(py, ['-c', 'import numpy, cv2, PIL'], { timeout: 60000, windowsHide: true }, (e, so, se) => res(e ? { e, se: String(se || '') } : null)));
  function findLocal() {
    if (hint.python) {
      if (render.python && render.python !== hint.python && !warnedTl) { warnedTl = true; log(`タイムラインの render.python（${render.python}）は使わない：この PC の設定の python（${hint.python}）で描く`); }
      // ffmpeg のフォルダ：PC の設定があればそれ。無ければ既定の場所（server/defaults.js。ffmpeg.exe があれば）→ 無ければ PATH。
      // 前は、python を設定していると既定の場所を探さなかった（python だけ設定した PC で、PATH に無い ffmpeg が見つからなくなる。2026-11-12）
      const ffmpegDir = hint.ffmpegDir || (opts.defaultFfmpegDirs || []).find(d => d && fs.existsSync(path.join(d, 'ffmpeg.exe'))) || '';
      const found = { python: hint.python, ffmpegDir, from: 'この PC の設定' };  // from はログだけ
      if (hintOk) return Promise.resolve(found);
      if (hintBad && Date.now() - hintBad.at < 10000) return Promise.resolve(hintBad.r);
      // 設定の python も、起動の前に確かめる（2026-11-12）。前は確かめずに起動していて、無いファイルだと 1 コマごとに 90 秒待ち、
      // numpy・opencv の無い python だと、落ちては起動し直すのを繰り返し、画面には標準エラーの切れ端しか出なかった
      return canImport(hint.python).then(bad => {
        if (!bad) { hintOk = true; return found; }
        const last = bad.se.trim().split(/\r?\n/).pop() || String(bad.e.message || bad.e).split(/\r?\n/)[0];
        const why = bad.e.code === 'ENOENT' ? L('srv.py.settingMissing', { py: hint.python }) : L('srv.py.settingNoImport', { py: hint.python, last });
        hintBad = { at: Date.now(), r: { error: KE('srv.py.fixSetting', { why }) } };
        return hintBad.r;
      });
    }
    if (probe || (probeAt && Date.now() - probeAt < 300000)) return Promise.resolve(probe);
    let fromTl = '';
    if (render.python) { const why = checkPython(render.python); if (why) log(`タイムラインの render.python は使わない：${why}`); else fromTl = render.python; }
    const label = py => (py === fromTl ? 'タイムラインの render.python' : py === opts.defaultPython ? '既定' : 'PATH');
    // 前と同じ順：タイムラインに render.python があればそれ（通ったときだけ）、無ければ既定 → PATH の python
    const cands = [...new Set([render.python ? fromTl : opts.defaultPython, 'python'].filter(Boolean))].filter(p => !/[\\/]/.test(p) || fs.existsSync(p));
    // ffmpeg のフォルダ：PC の設定 → 既定の場所（server/defaults.js。あれば）→ 無ければ PATH の ffmpeg（Windows 専用：ffmpeg.exe を探す）
    const ffmpegDir = [hint.ffmpegDir, ...(opts.defaultFfmpegDirs || [])].find(d => d && fs.existsSync(path.join(d, 'ffmpeg.exe'))) || '';
    return (async () => {
      for (const py of cands) {
        const ok = await new Promise(res => execFile(py, ['-c', 'import numpy, cv2, PIL'], { timeout: 60000, windowsHide: true }, e => res(!e)));
        if (ok) return { python: py, ffmpegDir, from: label(py) };
      }
      return null;
    })().then(r => { probe = r; probeAt = Date.now(); return r; });
  }
  async function ensure() {
    if (local) return local;
    const l = await findLocal();
    if (!l) throw KE('srv.py.noRenderPython');
    if (l.error) throw l.error;
    local = l; usePath(l); log(`描く python：${l.python}（${l.from}）${l.ffmpegDir ? `（ffmpeg：${l.ffmpegDir}）` : ''}`);
    return local;
  }

  function launch() {
    if (st.closing) return;  // 止められたあと：起動しない（起動すると取り残される）
    const port = st.port; st.launches++; st.dead = false; st.error = ''; st.err = null;
    const p = spawnLocal(port);
    st.proc = p;
    let served = false;
    let buf = '';
    const onData = d => { buf += d; if (/serving /.test(buf) && st.proc === p) { st.ready = true; served = true; st.fails = 0; } if (buf.length > 4000) buf = buf.slice(-2000); };
    p.stdout.on('data', onData); p.stderr.on('data', d => { onData(d); log('[engine] ' + String(d).trim()); });
    // 起動できなかった（python のファイルが無いなど）：exit は来ないので、ここで「動いていない」にする。前は st.proc が残り、1 コマ頼むたびに 90 秒待ってからエラーになった
    p.on('error', e => {
      if (st.proc === p) { st.proc = null; st.ready = false; st.dead = true; failed(); }
      setErr(KE('srv.pr.launchFail', { err: e.message, retry: retryNote() })); log(st.error);
    });
    p.on('exit', code => {
      if (st.proc !== p) return;
      st.ready = false; st.proc = null;
      // ポートが使われていた（ほかの描画サーバーなど）：別のポートですぐ起動し直す（serve.py はほかのサーバーと同じポートに入らない）
      if (!served && !st.closing && /10048|10013|Address already in use|only one usage/i.test(buf) && st.launches < 8) {
        log(`ポート ${st.port} が使われていたので、別のポートで起動し直します`); st.port = newPort(); launch(); return;
      }
      if (!st.closing) {
        st.dead = true;
        if (!served) failed();  // 1 コマも描けないまま止まった：続けて起動し直さない（間隔をあける）
        // 理由が先に見えるように、標準エラーの最後の行（Python のエラーの行）を頭に出す
        const last = buf.trim().split(/\r?\n/).filter(s => s.trim()).pop() || '';
        setErr(KE('srv.pr.died', { code, last: last.trim().slice(0, 300), tail: served ? L('srv.pr.nextFrame') : retryNote() }));
        log(st.error + (served ? '' : ' ／ ' + buf.slice(-300)));
      }
    });
  }
  // 起動してすぐ止まるのが続くとき（numpy の無い python など）：/api/status（編集画面が 2 秒ごとに聞く）のたびに起動し直さないよう、間隔を 2・4・8…60 秒とあける
  function failed() { st.fails = (st.fails || 0) + 1; st.retryAt = Date.now() + Math.min(60000, 1000 * 2 ** st.fails); }
  const retryNote = () => L('srv.pr.retry', { n: Math.max(1, Math.round(((st.retryAt || 0) - Date.now()) / 1000)) });
  function setErr(e) { st.err = e && e.key ? e : null; st.error = String((e && e.message) || e || ''); }
  // 念のため：手元のサーバーがどんな止まり方をしても、子のプロセスは残さない（描画サーバーは 30 分使われないと自分で止まる）。
  // 聞き手は 1 つだけ（前は起動のたびに足していた）。close() で外す
  const onExit = () => { const p = st.proc; if (p && p.exitCode === null) try { p.kill(); } catch (e) { } };
  process.once('exit', onExit);
  function spawnLocal(port) {
    const env = Object.assign({}, process.env, { PYTHONUNBUFFERED: '1' });
    if (local.ffmpegDir) env.PATH = local.ffmpegDir + path.delimiter + env.PATH;
    return spawn(local.python || 'python', ['-X', 'utf8', '-B', '-m', 'mittler', 'serve', path.join(project, timelineName), '--port', String(port)],
      { cwd: path.join(ROOT, 'pyengine'), env, windowsHide: true });
  }

  const ready = ensure().then(() => { launch(); return true; }, e => { setErr(e); log(st.error); return false; });

  function get(pth, timeout) {
    return new Promise((ok, ng) => {
      const req = http.get({ host: '127.0.0.1', port: st.port, path: pth, timeout }, res => {
        const bufs = []; let done = false; res.on('data', b => bufs.push(b));
        res.on('end', () => { done = true; ok({ status: res.statusCode, headers: res.headers, body: Buffer.concat(bufs) }); });
        // 返事の途中で描画サーバーが落ちた：終わらせる（前は end が来ないまま待ち続け、プレビューの「描いている 1 枚」がふさがったままになった。2026-11-12）
        res.on('error', ng); res.on('close', () => { if (!done) ng(KE('srv.pr.cut')); });
      });
      req.on('error', ng); req.on('timeout', () => req.destroy(new Error('timeout')));
    });
  }
  // o.prof：計測（描画サーバーが X-Mittler-Prof と、ログに1行の JSON で内訳を出す）。o.scale：プレビューの縮小（0〜1。等倍で描いてから縮める。1・無しは等倍）
  // o.draft：ドラフト品質（ctx.draft。対応したエフェクトだけが軽く描く。描画サーバーのキャッシュは別の枠）
  const frame = (t, q, fmt, o = {}) => {
    const sc = +o.scale > 0 && +o.scale < 1 ? '&scale=' + (+o.scale) : '';
    return get(`/frame?t=${encodeURIComponent(t)}&q=${q || 88}${fmt ? '&fmt=' + fmt : ''}${o.prof ? '&prof=1' : ''}${sc}${o.draft ? '&draft=1' : ''}`, 120000);
  };

  // 止まっている（途中で止まった・最初に python が見つからなかった）：別のポートで起動し直す（同時に来ても1回だけ）
  function relaunch() {
    if (st.fails && Date.now() < st.retryAt) return Promise.resolve();  // 続けて失敗している：間隔があくまで起動しない（st.error はそのまま返る）
    if (!st.relaunching) {
      st.relaunching = (async () => {
        log('描画サーバーを起動し直します');
        try { await ensure(); } catch (e) { failed(); setErr(e); return; }
        if (!st.proc && !st.closing) { st.port = newPort(); launch(); }
      })().finally(() => { st.relaunching = null; });
    }
    return st.relaunching;
  }
  async function waitReady(ms = 90000) {
    await ready;
    if (!st.proc && !st.ready && !st.closing) await relaunch();
    const t0 = Date.now();
    while (!st.ready && st.proc && Date.now() - t0 < ms) await new Promise(r => setTimeout(r, 200));
    if (st.ready) return;
    throw st.err || (st.error ? new Error(st.error) : KE('srv.pr.noStart'));
  }

  return {
    st, frame, waitReady,
    ready,                                  // 最初の起動の準備（描く python が決まって起動したら true、見つからなければ false。st.err に理由）

    ensure,                                 // 描く python を決めて返す { python, ffmpegDir }（書き出し・解析も同じ python・ffmpeg を使う）
    get local() { return local; },
    get port() { return st.port; },
    // 止める：先に描画サーバーに /quit を送り、それからプロセスを止める
    close() {
      st.closing = true; log(`止める：ready=${st.ready} proc=${!!st.proc}`);
      process.removeListener('exit', onExit);
      const kill = () => { if (st.proc) st.proc.kill(); };
      if (!st.ready) {  // 起動の途中：起動しきるのを少し待って /quit を送る（間に合わなければプロセスだけ止める。描画サーバーは 30 分使われないと自分で止まる）
        if (!st.proc) return;
        const t0 = Date.now();
        const wait = () => { if (st.ready) return quitNow(); if (Date.now() - t0 > 20000 || !st.proc || st.proc.exitCode !== null) return kill(); setTimeout(wait, 200); };
        return wait();
      }
      return quitNow();
      function quitNow() {
        const req = http.get({ host: '127.0.0.1', port: st.port, path: '/quit', timeout: 3000 }, res => { res.resume(); res.on('end', () => setTimeout(kill, 300)); });
        req.on('error', kill); req.on('timeout', () => { req.destroy(); kill(); });
      }
    },
    async effects() {
      const r = await get('/effects', 60000);
      return JSON.parse(r.body.toString('utf8'));
    },
    // 部品の置き場（effects_lib/common）にあって、作品の effects/ にまだ無いエフェクト（編集画面のアセット窓の「作品に入れる」。2026-11-13）
    async effectsLib() {
      const r = await get('/effects_lib', 60000);
      return JSON.parse(r.body.toString('utf8'));
    },
    // ためた絵の地図（描画サーバーの /cachemap。コマごとの鍵、ためていなければ ''。2026-11-16）
    async cachemap(from, to) {
      await this.waitReady();
      const r = await get('/cachemap?from=' + (+from || 0) + (to != null && to !== '' ? '&to=' + (+to) : ''), 120000);
      if (r.status !== 200) throw new Error(r.body.toString('utf8').trim().split('\n').slice(-1)[0] || ('HTTP ' + r.status));
      return JSON.parse(r.body.toString('utf8'));
    },
    // JPEG のキャッシュを捨てる（Blender の 3D のためた絵を消したあと。描画サーバーが動いていなければ何もしない）
    async flush() {
      if (!st.ready) return;
      try { await get('/flush', 30000); } catch (e) { }
    },
    // 音ハメ（mittler/onbeat.py）：映像クリップ1本の時間の付け替えを作る。動きの解析は初回だけ数秒〜数十秒
    async warp(q) {
      const r = await get('/warp?q=' + encodeURIComponent(JSON.stringify(q)), 600000);
      if (r.status !== 200) throw new Error(r.body.toString('utf8').trim().split('\n').slice(-1)[0] || ('HTTP ' + r.status));
      return JSON.parse(r.body.toString('utf8'));
    },
  };
}

module.exports = { start, checkPython };
