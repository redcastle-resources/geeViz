// Executes layout() for the three seeding modes. One JSON line.
const fs = require("fs");
const vm = require("vm");
const sandbox = { console: { log() {}, warn() {}, error() {} } };
sandbox.window = sandbox;
sandbox.setInterval = () => 0;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const W = sandbox.geeVizWindParticles;

const W_PX = 1700, H_PX = 1200, N = 2975;
const mk = mode => W._layout({ w: W_PX, h: H_PX, cfg: { layout: mode } }, N);

const rnd = mk("random");
const grid = mk("grid");
const rg1 = mk("randomGrid");
const rg2 = mk("randomGrid");

const xs = [...new Set(grid.map(p => p[0]))].sort((a, b) => a - b);
const ys = [...new Set(grid.map(p => p[1]))].sort((a, b) => a - b);
const gaps = xs.slice(1).map((v, i) => v - xs[i]);

process.stdout.write(JSON.stringify({
  randomCount: rnd.length,
  gridCount: grid.length,
  randomGridCount: rg1.length,
  cols: xs.length,
  rows: ys.length,
  dx: gaps[0],
  dy: ys[1] - ys[0],
  dxSpread: Math.max(...gaps) - Math.min(...gaps),
  offsetsDiffer: rg1[0][0] !== rg2[0][0] || rg1[0][1] !== rg2[0][1],
}));
