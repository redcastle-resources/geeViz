// Executes the real sampleUV/pixelUV against a synthetic tile and
// prints one JSON line. Driven by test_wind_tile_encoding.py.
//
// This exists because the rest of the wind tests assert on SOURCE TEXT,
// which cannot tell a correct bilinear blend from a plausible-looking
// wrong one. Interpolation is arithmetic; arithmetic deserves to be
// run.
const fs = require("fs");
const vm = require("vm");

const src = fs.readFileSync(process.argv[2], "utf8");
const sandbox = { console: { log() {}, warn() {}, error() {} } };
sandbox.window = sandbox;
sandbox.setInterval = () => 0;
sandbox.document = undefined;
sandbox.google = undefined;
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const W = sandbox.geeVizWindParticles;

const TILE_PX = 256;
const TILE_MIN = -40, TILE_MAX = 40;

// Red ramps left->right, green top->bottom, so a decoded u should rise
// smoothly with longitude and v with latitude.
const ramp = new Uint8ClampedArray(TILE_PX * TILE_PX * 4);
for (let y = 0; y < TILE_PX; y++) {
  for (let x = 0; x < TILE_PX; x++) {
    const i = (y * TILE_PX + x) * 4;
    ramp[i] = x; ramp[i + 1] = y; ramp[i + 2] = 0; ramp[i + 3] = 255;
  }
}

const z = 4, n = Math.pow(2, z);
const st = {
  tileZoom: z,
  cfg: { tileMin: TILE_MIN, tileMax: TILE_MAX },
  tiles: {},
  getTileUrl: () => "http://example/",
  inflight: 0, burst: 0, id: "probe",
  // The tile cache is keyed by FRAME as well as tile, so one overlay can
  // serve every frame of a wind time lapse without frame 2 reading
  // frame 1's pixels. Seed under the same key getTile builds, or the
  // probe falls through to a real fetch and dies on `new Image()`,
  // which does not exist in node.
  frameId: "probe",
};
for (let tx = 0; tx < n; tx++) {
  for (let ty = 0; ty < n; ty++) {
    st.tiles[st.frameId + "/" + z + "/" + tx + "/" + ty] = ramp;
  }
}

// Deliberately away from a tile seam: the synthetic tiles repeat, so a
// seam is a real discontinuity in THIS fixture (not in real data).
const lat = 12.34, lon0 = 37.77;
const pxDeg = 360 / (n * TILE_PX);
const samples = [];
for (let k = 0; k <= 40; k++) {
  const uv = W._sampleUV(st, lat, lon0 + (k * pxDeg) / 10);
  samples.push(uv ? uv[0] : null);
}
const steps = [];
for (let i = 1; i < samples.length; i++) steps.push(samples[i] - samples[i - 1]);

const uv = W._sampleUV(st, lat, lon0);
let lo = Infinity, hi = -Infinity;
for (let k = 0; k < 400; k++) {
  const s = W._sampleUV(st, (k % 80) - 40, ((k * 7) % 360) - 180);
  if (!s) continue;
  lo = Math.min(lo, s[0], s[1]); hi = Math.max(hi, s[0], s[1]);
}

process.stdout.write(JSON.stringify({
  nSamples: samples.length,
  nDistinct: new Set(samples.map(v => v.toFixed(9))).size,
  minStep: Math.min(...steps.map(Math.abs)),
  maxStep: Math.max(...steps.map(Math.abs)),
  monotonic: steps.every(s => s >= -1e-9),
  tupleLen: uv.length,
  magOk: Math.abs(uv[2] - Math.hypot(uv[0], uv[1])) < 1e-12,
  decodedLo: lo, decodedHi: hi,
  // one pixel's worth of the stretch, for scale
  perPixel: (TILE_MAX - TILE_MIN) / 255,
}));
