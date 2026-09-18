// Drives the real wind-particles.js against a simulated time lapse and
// prints one JSON line. Read by test_wind_timelapse_frames.py.
//
// Two things are being checked that source text cannot tell you.
//
// 1. N frames must collapse into ONE overlay. Every frame of a wind
//    lapse is its own geeImage layer carrying windParticles, so the
//    naive reading of the registry adopts nine particle fields and
//    draws nine independent flows on top of each other.
//
// 2. The overlay must follow the frame the LAPSE is showing, and the
//    viewer does not show frames by ticking checkboxes. For a geeImage
//    lapse it turns every frame visible at once and then raises one
//    frame's OPACITY (lcms-viewer: turnOnTimeLapseLayers, then
//    selectFrame -> setFrameOpacity). Selecting on `visible` yields a
//    perfectly animated flow locked to frame 0 -- no error, no visual
//    tell beyond a forecast that never evolves.
"use strict";

const fs = require("fs");
const vm = require("vm");

// ---- a map, and the positional overlay array the viewer relies on ----
function MVCArray() { this.a = []; }
MVCArray.prototype.setAt = function (i, v) {
  while (this.a.length < i) this.a.push(undefined);
  this.a[i] = v;
};
MVCArray.prototype.getArray = function () { return this.a; };
MVCArray.prototype.getAt = function (i) { return this.a[i]; };

const overlay = new MVCArray();

// Nine frames of one lapse, exactly as the viewer registers them: all
// visible, all at opacity 0, until selectFrame raises one.
const N = 9;
const LAPSE = "GFS-wind-particles";
const LAYERS = {};
const frameIds = [];
for (let i = 0; i < N; i++) {
  const id = LAPSE + "-frame" + i;
  frameIds.push(id);
  LAYERS[id] = {
    layerId: i,
    visible: true,
    opacity: 0,
    name: id,
    // The ImageMapType. getTileUrl is deliberately absent so
    // findTileUrlFn has to go hunting, the way it does against the
    // minified viewer build.
    layer: { sh: (c, z) => "https://tiles.example/" + i + "/" + z
                           + "/" + c.x + "/" + c.y },
    viz: {
      windParticles: true,
      isTimeLapse: true,
      timeLapseID: LAPSE,
      windTileMin: -40, windTileMax: 40,
      particleColor: "#fff",
    },
  };
  overlay.setAt(i, "UV_TILES_" + i);
}

// A plain, non-lapse particle layer alongside it. It has no
// timeLapseID, so it must keep its own overlay and must keep being
// driven by `visible` -- the opacity rule above would be wrong for it.
LAYERS["plain"] = {
  layerId: N, visible: true, opacity: 1, name: "plain",
  layer: { sh: (c, z) => "https://tiles.example/plain/" + z },
  viz: { windParticles: true, windTileMin: -40, windTileMax: 40 },
};
overlay.setAt(N, "PLAIN_TILES");

// ---- the browser, as much of it as the module touches ----------------
const sandbox = {
  console: { log() {}, warn() {}, error() {} },
  setInterval: () => 0,
  requestAnimationFrame: () => 1,
  cancelAnimationFrame: () => {},
  performance: { now: () => 0 },
};
sandbox.window = sandbox;
sandbox.document = {
  hidden: false,
  addEventListener() {},
  createElement: () => ({
    style: {},
    getContext: () => ({ clearRect() {}, setTransform() {}, beginPath() {},
                         moveTo() {}, lineTo() {}, stroke() {} }),
  }),
};
sandbox.google = {
  maps: {
    OverlayView: function () {
      this.setMap = function () {};
      this.getPanes = () => ({ overlayLayer: { appendChild() {} } });
      this.getProjection = () => null;
    },
  },
};
sandbox.map = {
  overlayMapTypes: overlay,
  addListener() {},
  getZoom: () => 4,
  getCenter: () => ({ lat: () => 40, lng: () => -100 }),
  // No getDiv: observeInView bails out and leaves inView true, which is
  // what a browser without IntersectionObserver also does.
};
sandbox.layerObj = LAYERS;

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const W = sandbox.geeVizWindParticles;

W.scan();

const out = {};
const adopted = W._adopted;
out.overlayIds = Object.keys(adopted).sort();

// Grouping: one entry for the nine frames, one for the plain layer.
const st = adopted["tl:" + LAPSE];
out.adoptedLapse = !!st;
out.frameCount = st ? Object.keys(st.frames).length : 0;
out.perFrameOverlays = frameIds.filter((id) => !!adopted[id]).length;

// Every frame's encoded RGB must be off the map, not just the showing
// one -- an unhidden frame paints a magenta-green wash over the base map.
out.overlayAfterScan = overlay.getArray().slice();

// The Maps API calls onAdd when the overlay is added to the map; the
// stub above does not, so do it by hand. This is what builds the canvas
// the stacking checks below read.
st.overlay.onAdd();
adopted["plain"].overlay.onAdd();

// ---- now play the lapse, the way the viewer plays it -----------------
// selectFrame: zero every frame, raise the chosen one.
function selectFrame(i) {
  frameIds.forEach((id) => { LAYERS[id].opacity = 0; });
  LAYERS[frameIds[i]].opacity = 0.9;
  W._refreshRunState();
}

out.beforeAnyFrame = { frameId: st ? st.frameId : null,
                       running: st ? st.running : null };

selectFrame(0);
out.atFrame0 = { frameId: st.frameId, url: st.getTileUrl({ x: 1, y: 2 }, 3) };

// Mark the trails so a reseed is detectable, then advance.
st.particles = ["TRAIL_MARKER"];
st.fieldKey = "stale";

selectFrame(4);
out.atFrame4 = { frameId: st.frameId, url: st.getTileUrl({ x: 1, y: 2 }, 3) };
out.particlesSurvivedFrameChange = st.particles
  && st.particles[0] === "TRAIL_MARKER";
out.fieldKeyCleared = st.fieldKey === null;

selectFrame(8);
out.atFrame8 = { frameId: st.frameId, url: st.getTileUrl({ x: 1, y: 2 }, 3) };

// Cumulative mode: frames 0..current all carry the lapse opacity, and
// the current frame is the last of them.
frameIds.forEach((id, i) => { LAYERS[id].opacity = i <= 5 ? 0.9 : 0; });
W._refreshRunState();
out.cumulative = { frameId: st.frameId };

// Stopped: every frame back to zero. Nothing is showing, so nothing
// should be drawing the encoded field of a frame the user cannot see.
frameIds.forEach((id) => { LAYERS[id].opacity = 0; });
W._refreshRunState();
out.whenAllZero = { frameId: st.frameId, running: st.running };

// Stacking: the canvas takes its z-index from the frame on screen.
// For a lapse st.id is the group key and is not a registry entry at
// all, so looking the layerId up by it finds nothing and the canvas
// keeps whatever z-index it had -- dragging the lapse in the layer
// list then moves the rasters and leaves the particles behind.
// An unset zIndex is "" or undefined, and JSON.stringify DROPS an
// undefined value -- which would reach the test as a missing key and a
// KeyError instead of a readable failure. Normalise to null.
function zOf(s) {
  var z = s.canvas ? s.canvas.style.zIndex : undefined;
  return (z === undefined || z === "") ? null : z;
}

selectFrame(3);
out.zAtFrame3 = zOf(st);
LAYERS[frameIds[3]].layerId = 7;            // as updateMapLayerOrder does
W._refreshRunState();
out.zAfterReorder = zOf(st);
LAYERS[frameIds[3]].layerId = 3;

// ---- and the plain layer is still driven by `visible` ----------------
const pst = adopted["plain"];
out.plain = { adopted: !!pst, isLapse: pst ? pst.isLapse : null,
              running: pst ? pst.running : null };
LAYERS["plain"].visible = false;
W._refreshRunState();
out.plainAfterHide = pst.running;
LAYERS["plain"].visible = true;
W._refreshRunState();
out.plainAfterShow = pst.running;

console.log(JSON.stringify(out, null, 1));
