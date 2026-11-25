// HTML のレイヤー（pyengine/mittler/htmllayer.py）が、ページのスクリプトより先に読ませる下地（2026-11-18）。
// 絵が「クリップの頭からの秒」だけで決まるように（前のコマを覚えない・並列の書き出しで区間に分けても同じ絵）、時刻と乱数を Mittler が決める：
//   Date.now()・performance.now() … いまのコマの時刻（クリップの頭からの秒。Date は 2026-01-01 を 0 秒として）
//   Math.random() … 種（params.seed）とコマ番号で決まる乱数。ページを読むとき（作るとき）は種だけで決まる
//   requestAnimationFrame … 1 コマ描くたびに 1 回だけ呼ぶ（three.js の setAnimationLoop もこれで動く）。時刻は上の performance.now
// ページの書き方（docs/エフェクトの書き方.md の「HTML のレイヤー」）：
//   mittler.W・H（描く大きさ px）・fps・scale（マスター書き出しの倍率）・draft（下書きか）・args（クリップの args）・dur（クリップの長さ 秒）・t（いまの秒）
//   mittler.onFrame((t, args) => { … t 秒の絵を描く … })   … 1 コマごとに呼ぶ（async でもよい）。絵は t だけで決める（前のコマからの差分で動かさない）
//   mittler.ready(promise)                                  … 画像・書体などを読み終わるまで待ってほしいとき（描いている間に書体の読み込みが始まったら、下地が読み終わってから描き直す）
//   背景は透明（body も canvas も透明のまま。three.js は alpha: true で setClearColor(0x000000, 0)）
(() => {
  const init = window.__MITTLER_INIT || {};
  const T0 = Date.UTC(2026, 0, 1);
  let T = 0;
  Date.now = () => T0 + Math.round(T * 1000);
  const P = window.performance;
  try { Object.defineProperty(P, 'now', { value: () => T * 1000, configurable: true }); } catch (e) { P.now = () => T * 1000; }
  // 乱数：mulberry32。種と「いまのコマ」で決める
  let s = 0;
  const seedTo = n => { s = ((init.seed >>> 0) * 2654435761 + (n >>> 0) * 40503 + 1) >>> 0; };
  const rnd = () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  seedTo(0xffffffff);
  Math.random = rnd;
  let raf = [], rid = 0;
  window.requestAnimationFrame = cb => { raf.push([++rid, cb]); return rid; };
  window.cancelAnimationFrame = id => { raf = raf.filter(x => x[0] !== id); };
  const fns = [];
  let readyP = Promise.resolve();
  window.mittler = {
    W: init.W, H: init.H, fps: init.fps, scale: init.scale || 1, draft: !!init.draft, seed: init.seed, args: init.args || {}, dur: init.dur || 0, t: 0,
    onFrame(fn) { fns.push(fn); },
    ready(p) { readyP = Promise.all([readyP, p]); },
    random: rnd,
  };
  window.__mittlerReady = async () => {
    await readyP;
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    return true;
  };
  const drawOnce = async (t, n) => {
    T = t; mittler.t = t; seedTo(n || 0);
    for (const fn of fns) await fn(t, mittler.args);
    const cbs = raf; raf = [];
    for (const [, cb] of cbs) cb(T * 1000);
  };
  // 書体の読み込み待ち（2026-11-22）：ブラウザは書体を「初めて使われたとき」に読むので、Canvas の fillText は、その書体を初めて使うコマだけ
  // 代わりの書体で描かれていた（字体がカクッと変わる。並列の書き出しは区間ごとに新しいブラウザなので、区間の頭ごとに起きた）。
  // 描いている間に書体の読み込みが始まったら、読み終わるのを待って同じ時刻を描き直す（同じ時刻・同じ種なので同じ絵になる）。
  // 使った書体だけを読む（前の版は宣言された書体を全部先に読んでいて、大きな書体が多いと重かった）
  window.__mittlerRender = async (t, args, n) => {
    if (args) mittler.args = args;
    await drawOnce(t, n);
    for (let i = 0; i < 3 && document.fonts && document.fonts.status === 'loading'; i++) {
      await document.fonts.ready;
      await drawOnce(t, n);
    }
    return true;
  };
})();
