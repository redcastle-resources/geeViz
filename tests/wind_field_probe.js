// Executes countFor and fieldAt and prints one JSON line.
// Driven by test_wind_tile_encoding.py. The count and the grid read are
// arithmetic; arithmetic deserves to be run rather than grepped.
const fs = require("fs");
const vm = require("vm");

const src = fs.readFileSync(process.argv[2], "utf8");
const sandbox = { console: { log() {}, warn() {}, error() {} } };
sandbox.window = sandbox;
sandbox.setInterval = () => 0;
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const W = sandbox.geeVizWindParticles;

const cfg = { count: null, density: 1.75, minCount: 400, maxCount: 20000 };

// A 5x5 grid at 10px spacing: dx ramps with the column, dy constant.
const gw = 5, gh = 5, sp = 10;
const f = new Float32Array(gw * gh * 2);
const ok = new Uint8Array(gw * gh).fill(1);
for (let gy = 0; gy < gh; gy++) {
  for (let gx = 0; gx < gw; gx++) {
    const i = (gy * gw + gx) * 2;
    f[i] = gx;
    f[i + 1] = 2;
  }
}
const st = { field: f, fieldOk: ok, fieldW: gw, fieldH: gh, fieldSpacing: sp };
const ramp = [10, 12.5, 15, 17.5, 20]
  .map(x => Number(W._fieldAt(st, x, 15)[0].toFixed(6)));
const outside = W._fieldAt(st, -5, 5);

// Knock out the FAR corner (i11), not the near one. A check that only
// looks at i00 still rejects a missing near corner, so testing that one
// cannot tell a full check from a partial one.
ok[(1 + 1) * gw + (1 + 1)] = 0;           // i11 for the cell at (12, 12)
const missingCorner = W._fieldAt(st, 12, 12);
// ...and the near corner too, separately.
const ok2 = new Uint8Array(gw * gh).fill(1);
ok2[1 * gw + 1] = 0;
const missingNear = W._fieldAt(
  { field: f, fieldOk: ok2, fieldW: gw, fieldH: gh, fieldSpacing: sp }, 12, 12);

process.stdout.write(JSON.stringify({
  w800: W._countFor(cfg, 800),
  w1280: W._countFor(cfg, 1280),
  w1700: W._countFor(cfg, 1700),
  w1920: W._countFor(cfg, 1920),
  clampLo: W._countFor(cfg, 100),
  clampHi: W._countFor(cfg, 99999),
  explicit: W._countFor(Object.assign({}, cfg, { count: 900 }), 1700),
  ramp: ramp,
  outside: outside,
  missingCorner: missingCorner,
  missingNear: missingNear,
}));
