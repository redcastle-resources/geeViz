// Exercises the real tile fetch and field build, and prints one JSON
// line. Read by test_wind_tile_encoding.py.
//
// These behaviors used to be pinned by asserting exact source lines,
// which broke the moment the code moved and told you nothing about
// whether it still worked. What actually matters here is arithmetic and
// bookkeeping, and both can be run:
//
//   * in-flight accounting -- a tile that 404s must leave the queue
//     exactly like one that loads, or the layer spins forever;
//   * a PREFETCH must not enter that queue at all, because buildField
//     reads st.inflight to decide the frame on screen is fully resolved;
//   * an incomplete field must not be cached as final;
//   * and the field being DRAWN must survive a frame change whose tiles
//     have not arrived -- otherwise the particles freeze on every step
//     of a time lapse.
"use strict";

const fs = require("fs");
const vm = require("vm");

const TILE_PX = 256;

// ---- a browser, with a controllable Image ----------------------------
// Which URLs fail is decided here, so both outcomes are reachable.
const FAIL = /\/fail\//;
let pending = [];          // [{img, url}] -- resolved on demand

const sandbox = {
  console: { log() {}, warn() {}, error() {} },
  setInterval: () => 0,
  requestAnimationFrame: () => 1,
  performance: { now: () => nowFake },
};
let nowFake = 0;
sandbox.window = sandbox;
sandbox.Image = function () {
  const self = this;
  this.onload = null;
  this.onerror = null;
  Object.defineProperty(this, "src", {
    set(u) { pending.push({ img: self, url: u }); },
    get() { return ""; },
  });
};
sandbox.document = {
  hidden: false,
  addEventListener() {},
  createElement: () => ({
    width: 0, height: 0, style: {},
    getContext: () => ({
      drawImage() {},
      clearRect() {}, setTransform() {}, beginPath() {},
      moveTo() {}, lineTo() {}, stroke() {},
      // A uniform tile: u and v both mid-scale plus a bit, alpha solid.
      getImageData: (x, y, w, h) => ({
        data: (() => {
          const a = new Uint8ClampedArray(w * h * 4);
          for (let i = 0; i < w * h; i++) {
            a[i * 4] = 160; a[i * 4 + 1] = 100;
            a[i * 4 + 2] = 128; a[i * 4 + 3] = 255;
          }
          return a;
        })(),
      }),
    }),
  }),
};
sandbox.google = {
  maps: {
    Point: function (x, y) { this.x = x; this.y = y; },
    OverlayView: function () {
      this.setMap = function () {};
      // mapPane is the one that matters: it is where
      // map.overlayMapTypes render, so it is the pane the canvases
      // are appended to. overlayLayer is kept here only so a stub
      // that still names it does not read as the right answer.
      this.getPanes = () => ({ mapPane: { appendChild() {} },
                               overlayLayer: { appendChild() {} } });
      this.getProjection = () => null;
    },
  },
};
sandbox.map = {
  overlayMapTypes: { setAt() {}, getArray: () => [], getAt: () => null },
  addListener() {},
  getZoom: () => 4,
  getCenter: () => ({ lat: () => 40, lng: () => -100 }),
};
sandbox.layerObj = {};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const W = sandbox.geeVizWindParticles;

// Settle every outstanding Image, success or failure by URL.
function settle() {
  const batch = pending;
  pending = [];
  batch.forEach(({ img, url }) => {
    if (FAIL.test(url)) { if (img.onerror) img.onerror(); }
    else if (img.onload) img.onload();
  });
  return batch.length;
}

// Real Maps returns an eager LatLng. buildField and warmNextFrames both
// reuse a single Point and mutate it between calls, so a stub that
// closed over the point would report every corner as the last one read.
function snapshotLatLng(span, lat0, lon0, deg) {
  return (p) => {
    const x = p.x, y = p.y;
    return { lat: () => lat0 - (y / span) * deg,
             lng: () => lon0 + (x / span) * deg };
  };
}

function urlFor(tag) {
  return (c, z) => "https://tiles.example/" + tag + "/" + z + "/" + c.x
                   + "/" + c.y;
}

function newSt(extra) {
  const st = {
    id: "s", frameId: "f0", isLapse: false,
    frames: { f0: urlFor("f0") },
    getTileUrl: urlFor("f0"),
    cfg: { tileMin: -40, tileMax: 40, speed: 0.5, minSpeed: 1, maxSpeed: 30 },
    tiles: Object.create(null), tileFails: Object.create(null),
    tileZoom: 4, inflight: 0, burst: 0,
    field: null, fieldOk: null, fieldW: 0, fieldH: 0,
    fieldB: null, fieldOkB: null, fieldBW: 0, fieldBH: 0,
    buildAgainAt: 0, fieldSpacing: 8, fieldKey: null, fieldAny: false,
    canvas: null, ctx: null, particles: null, running: false,
    origin: { x: 0, y: 0 }, proj: null, w: 0, h: 0, warned: false,
  };
  return Object.assign(st, extra || {});
}

const out = {};

// ---- 1. a tile that loads leaves the queue ---------------------------
{
  const st = newSt();
  W._getTile(st, 4, 1, 2);
  out.loadInflightDuring = st.inflight;
  settle();
  out.loadInflightAfter = st.inflight;
  out.loadDecoded = st.tiles["f0/4/1/2"] instanceof Uint8ClampedArray;
}

// ---- 2. a tile that 404s leaves it too -------------------------------
{
  const st = newSt({ frames: { f0: urlFor("fail") },
                     getTileUrl: urlFor("fail") });
  W._getTile(st, 4, 1, 2);
  out.errInflightDuring = st.inflight;
  settle();
  out.errInflightAfter = st.inflight;
  out.errCachedFalse = st.tiles["f0/4/1/2"] === false;
}

// ---- 3. a getTileUrl that throws is never counted --------------------
{
  const st = newSt({
    frames: { f0: () => { throw new Error("boom"); } },
    getTileUrl: () => { throw new Error("boom"); },
  });
  W._getTile(st, 4, 1, 2);
  out.throwInflight = st.inflight;
  out.throwCachedFalse = st.tiles["f0/4/1/2"] === false;
  out.throwQueued = pending.length;
  pending = [];
}

// ---- 4. a PREFETCH must not enter the queue --------------------------
// buildField treats st.inflight as "the frame on screen is not resolved
// yet". A warm fetch for a LATER hour counted there would leave every
// build incomplete, the field key never stamped, and the rebuild
// throttle permanently disarmed.
{
  const st = newSt({
    isLapse: true, frameId: "f0",
    frames: { f0: urlFor("f0"), f1: urlFor("f1"), f2: urlFor("f2") },
  });
  W._getTile(st, 4, 1, 2, "f1");           // explicit other frame
  out.warmInflight = st.inflight;
  out.warmQueued = pending.length;
  settle();
  out.warmInflightAfter = st.inflight;
  out.warmDecodedUnderOwnKey =
    st.tiles["f1/4/1/2"] instanceof Uint8ClampedArray;
  out.warmDidNotTouchCurrentFrame = st.tiles["f0/4/1/2"] === undefined;
}

// ---- 5. warmNextFrames covers the view, for the frames ahead ---------
{
  const st = newSt({
    isLapse: true, frameId: "f0",
    frames: { f0: urlFor("f0"), f1: urlFor("f1"), f2: urlFor("f2"),
              f3: urlFor("f3") },
    w: 512, h: 512, origin: { x: 0, y: 0 },
    proj: { fromDivPixelToLatLng: snapshotLatLng(512, 45, -110, 20) },
  });
  W._warmNextFrames(st);
  const asked = pending.map((p) => p.url.split("/")[3]);
  out.warmedFrames = Array.from(new Set(asked)).sort();
  out.warmedCount = pending.length;
  out.warmInflightStillZero = st.inflight;
  pending = [];
}

// ---- 6. an incomplete field is not cached as final -------------------
{
  const st = newSt({
    w: 64, h: 64, origin: { x: 0, y: 0 },
    proj: { fromDivPixelToLatLng: snapshotLatLng(64, 45, -110, 5) },
  });
  // First build: every tile is a miss, so they all go in flight.
  W._buildField(st);
  out.incompleteKey = st.fieldKey;               // must be null
  out.incompleteInflight = st.inflight > 0;
  out.incompleteBackoffArmed = st.buildAgainAt > 0;

  settle();                                      // tiles arrive
  W._buildField(st);
  out.completeKeyStamped = typeof st.fieldKey === "string"
                           && st.fieldKey.length > 0;
  out.completeBackoffCleared = st.buildAgainAt === 0;
  out.completeFieldAny = st.fieldAny === true;

  // 7. ...and a settled field is not rebuilt at all.
  const before = st.fieldKey;
  out.ensureSkipsRebuild = W._ensureField(st) === true && st.fieldKey === before;
}

// ---- 8. THE ONE THAT MATTERS: a frame change must not blank the field -
// The lapse steps to an hour whose tiles are all cold. The field being
// drawn has to survive that, or tick() stops calling frame() and the
// particles freeze on every step.
{
  const st = newSt({
    isLapse: true, frameId: "f0",
    frames: { f0: urlFor("f0"), f1: urlFor("f1") },
    w: 64, h: 64, origin: { x: 0, y: 0 },
    proj: { fromDivPixelToLatLng: snapshotLatLng(64, 45, -110, 5) },
  });
  W._buildField(st); settle(); W._buildField(st);
  out.beforeStepFieldAny = st.fieldAny;
  const liveField = st.field;
  const sample = st.field ? st.field[0] : null;

  // Step the lapse by hand, exactly as refreshRunState does.
  st.frameId = "f1";
  st.getTileUrl = st.frames.f1;
  st.fieldKey = null;
  st.buildAgainAt = 0;

  const drew = W._ensureField(st);          // cold cache for f1
  out.afterStepEnsureTrue = drew === true;
  out.afterStepFieldAny = st.fieldAny;
  out.afterStepKeptSameBuffer = st.field === liveField;
  out.afterStepSampleUnchanged = st.field ? st.field[0] === sample : null;

  settle();                                  // f1's tiles land
  W._buildField(st);
  out.afterTilesFieldAny = st.fieldAny;
  out.afterTilesSwapped = st.field !== liveField;
  out.afterTilesKeyStamped = typeof st.fieldKey === "string";
}

// ---- 9. the rebuild throttle actually throttles -----------------------
{
  const st = newSt({
    w: 64, h: 64, origin: { x: 0, y: 0 },
    proj: { fromDivPixelToLatLng: snapshotLatLng(64, 45, -110, 5) },
  });
  W._buildField(st); settle(); W._buildField(st);   // settled field
  st.fieldKey = null;                               // force incomplete
  st.getTileUrl = urlFor("cold");
  st.frames.f0 = urlFor("cold");
  st.frameId = "cold0";
  nowFake = 1000;
  W._ensureField(st);                    // builds, arms the back-off
  const armed = st.buildAgainAt;
  pending = [];
  nowFake = 1000 + 10;                   // 10 ms later
  W._ensureField(st);
  out.throttleHeld = pending.length === 0 && st.buildAgainAt === armed;
  nowFake = armed + 1;                   // past the back-off
  W._ensureField(st);
  // Not "new requests were made" -- those tiles are already in flight
  // from the first attempt and getTile returns the pending marker
  // without re-fetching. A build having RUN is what re-arms the clock.
  out.throttleReleased = st.buildAgainAt > armed;
}

console.log(JSON.stringify(out, null, 1));
