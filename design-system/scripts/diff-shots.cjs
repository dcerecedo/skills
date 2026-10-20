#!/usr/bin/env node
// ds-inventory compare mode: diff the screenshots of two inventories, state by state.
//
//   npm install --prefix <scratch> pixelmatch@5 pngjs@7
//   NODE_PATH=<scratch>/node_modules node diff-shots.cjs <before/inventory.json> <after/inventory.json> <out-dir> [threshold]
//
// Matches states by id (viewport/route/state). Writes <out-dir>/<id>.diff.png for each changed
// state and prints JSON: per state the share of changed pixels, plus states present on one side only.
// Different page heights are compared over the shared area and reported as a size change.
const fs = require('fs');
const path = require('path');
const { PNG } = require('pngjs');
const pm = require('pixelmatch');
const pixelmatch = pm.default || pm;

const [beforePath, afterPath, outDir, thr] = process.argv.slice(2);
if (!beforePath || !afterPath || !outDir) {
  console.error('usage: diff-shots.cjs <before inventory.json> <after inventory.json> <out-dir> [threshold=0.1]');
  process.exit(2);
}
const threshold = thr ? Number(thr) : 0.1;
const load = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const shotOf = (inv, invPath) => Object.fromEntries(inv.states.filter((s) => s.screenshot).map((s) => {
  const p = path.isAbsolute(s.screenshot) ? s.screenshot : path.join(path.dirname(invPath), s.screenshot);
  return [s.id, p];
}));
const before = shotOf(load(beforePath), beforePath);
const after = shotOf(load(afterPath), afterPath);
fs.mkdirSync(outDir, { recursive: true });

const crop = (img, w, h) => {
  if (img.width === w && img.height === h) return img;
  const out = new PNG({ width: w, height: h });
  PNG.bitblt(img, out, 0, 0, w, h, 0, 0);
  return out;
};

const states = [];
for (const id of Object.keys(before)) {
  if (!after[id]) continue;
  if (!fs.existsSync(before[id]) || !fs.existsSync(after[id])) {
    states.push({ id, error: 'screenshot file missing' });
    continue;
  }
  const a = PNG.sync.read(fs.readFileSync(before[id]));
  const b = PNG.sync.read(fs.readFileSync(after[id]));
  const w = Math.min(a.width, b.width);
  const h = Math.min(a.height, b.height);
  const diff = new PNG({ width: w, height: h });
  const changed = pixelmatch(crop(a, w, h).data, crop(b, w, h).data, diff.data, w, h, { threshold });
  const share = changed / (w * h);
  let diffFile = null;
  if (changed > 0) {
    diffFile = path.join(outDir, id.replace(/[^a-z0-9_-]+/gi, '--') + '.diff.png');
    fs.writeFileSync(diffFile, PNG.sync.write(diff));
  }
  states.push({ id, changedPixels: changed, share: Number(share.toFixed(5)), diff: diffFile,
    sizeChange: a.width !== b.width || a.height !== b.height
      ? { before: [a.width, a.height], after: [b.width, b.height] } : null });
}
states.sort((x, y) => (y.share || 0) - (x.share || 0));
console.log(JSON.stringify({
  threshold,
  states,
  onlyBefore: Object.keys(before).filter((id) => !after[id]),
  onlyAfter: Object.keys(after).filter((id) => !before[id]),
}, null, 1));
