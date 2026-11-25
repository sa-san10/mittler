// Mittler：編集画面とサーバーで同じ計算（Python のエンジンと同じ式）。ブラウザ（editor/index.html が先に読む → window.MITTLER_CALC）と
// Node（server/server.js が require）の両方で使う。JS の中ではここが1か所。Python と同じことは tools/smoke_same.py が確かめる。
// - warpMap：映像クリップの時間の付け替えの点 {points, smooth} → クリップの頭から t 秒で映す動画の秒（pyengine/mittler/warp.py の Points と同じ）。
//   点のあいだは直線、点の外は端の傾きでのばす（点が1つなら傾き 1）、smooth（秒）があれば幅 smooth の9点の平均。
// - gradePixel：色の卓（effects_lib/common/grade.py と同じ式）。sRGB の値（0〜1）のまま 明るさ b → コントラスト c → ビブランス v → 彩度 s。0〜1 に切る前の値を返す。
'use strict';
(function (root) {
  const sorted = pts => pts.map(p => [+p[0], +p[1]]).sort((a, b) => a[0] - b[0]);
  function lin(a, u) {
    const n = a.length;
    if (n === 1) return a[0][1] + (u - a[0][0]);
    if (u <= a[0][0]) return a[0][1] + (a[1][1] - a[0][1]) / (a[1][0] - a[0][0]) * (u - a[0][0]);
    if (u >= a[n - 1][0]) return a[n - 1][1] + (a[n - 1][1] - a[n - 2][1]) / (a[n - 1][0] - a[n - 2][0]) * (u - a[n - 1][0]);
    for (let i = 1; i < n; i++) if (u <= a[i][0]) return a[i - 1][1] + (a[i][1] - a[i - 1][1]) * (u - a[i - 1][0]) / (a[i][0] - a[i - 1][0]);
    return a[n - 1][1];
  }
  function warpMap(w, t) {
    const a = sorted(w.points), sm = +w.smooth || 0;
    if (sm <= 0) return lin(a, t);
    let s = 0; for (let k = 0; k < 9; k++) s += lin(a, t - sm / 2 + sm * k / 8); return s / 9;
  }
  function gradePixel(R, G, B, b, c, v, s) {
    R *= b; G *= b; B *= b;
    if (c !== 1) { R = (R - .5) * c + .5; G = (G - .5) * c + .5; B = (B - .5) * c + .5; }
    if (v !== 1) {
      const L = .2126 * R + .7152 * G + .0722 * B, m = Math.min(1, Math.max(0, Math.max(R, G, B) - Math.min(R, G, B))), k = 1 + (v - 1) * (1 - m);
      R = L + (R - L) * k; G = L + (G - L) * k; B = L + (B - L) * k;
    }
    if (s !== 1) { const L = .2126 * R + .7152 * G + .0722 * B; R = L + (R - L) * s; G = L + (G - L) * s; B = L + (B - L) * s; }
    return [R, G, B];
  }
  const api = { sorted, lin, warpMap, gradePixel };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.MITTLER_CALC = api;
})(this);
