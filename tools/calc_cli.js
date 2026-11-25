// tools/smoke_same.py から呼ぶ：editor/calc.js（編集画面とサーバーの計算）に標準入力の JSON を通して、結果を JSON で返す。
//   node tools/calc_cli.js < {"warp": [{"w": {points, smooth}, "ts": [秒…]}…], "grade": [{"px": [[R,G,B]…]（0〜1）, "p": {b,c,v,s}}…]}
//   → {"warp": [[動画の秒…]…], "grade": [[[R,G,B]…]…]}（grade は 0〜1 に切る前）
'use strict';
const calc = require('../editor/calc');
const chunks = [];
process.stdin.on('data', d => chunks.push(d));
process.stdin.on('end', () => {
  const q = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const out = {
    warp: (q.warp || []).map(c => c.ts.map(t => calc.warpMap(c.w, t))),
    grade: (q.grade || []).map(c => c.px.map(([r, g, b]) => calc.gradePixel(r, g, b, c.p.b ?? 1, c.p.c ?? 1, c.p.v ?? 1, c.p.s ?? 1))),
  };
  process.stdout.write(JSON.stringify(out));
});
