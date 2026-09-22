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

// Tiles the speed raster composited. Counting drawImage is how "did it
// paint" and "did it skip a repaint it did not need" become observable.
let drawnTiles = 0;

// The module's clock, under the probe's control, so the back-offs can be
// stepped past deterministically instead of slept through.
let nowFake = 0;
let clearCalls = 0;   // clearRect calls, across every 2d context

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
  // A clock the probe drives, so the back-offs can be stepped past.
  performance: { now: () => nowFake },
};
sandbox.window = sandbox;
sandbox.document = {
  hidden: false,
  addEventListener() {},
  createElement: () => ({
    width: 0, height: 0, style: {},
    getContext: () => ({
      clearRect() { clearCalls++; }, setTransform() {}, beginPath() {},
      moveTo() {}, lineTo() {}, stroke() {},
      // The speed raster's scratch tile, and the composite onto the
      // canvas. Counting drawImage is how "did it actually paint" and
      // "did it skip a repaint it did not need" become observable.
      createImageData: (w, h) => ({ width: w, height: h,
                                    data: new Uint8ClampedArray(w * h * 4) }),
      putImageData() {},
      drawImage() { drawnTiles++; },
      globalAlpha: 1,
    }),
  }),
};
sandbox.google = {
  maps: {
    Point: function (x, y) { this.x = x; this.y = y; },
    LatLng: function (lat, lng) {
      this.la = lat; this.ln = lng;
      this.lat = () => lat; this.lng = () => lng;
    },
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
  overlayMapTypes: overlay,
  addListener() {},
  getZoom: () => 4,
  getCenter: () => ({ lat: () => 40, lng: () => -100 }),
  // No getDiv: observeInView bails out and leaves inView true, which is
  // what a browser without IntersectionObserver also does.
};
sandbox.layerObj = LAYERS;
// A tile request that never resolves. This probe only needs tiles to be
// ABSENT -- the tilecache probe is the one that exercises loading.
sandbox.Image = function () { this.onload = null; this.onerror = null; };
// The viewer builds queryObj asynchronously, so it starts ABSENT here --
// retargetQuery has to cope with that and retry, which is the case that
// actually happens in a browser.
sandbox.queryObj = {};
sandbox.ee = {
  Deserializer: {
    fromJSON: (raw) => ({ decodedFrom: raw }),
  },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const W = sandbox.geeVizWindParticles;

W.scan();

// Real Maps returns an eager LatLng; buildField and the speed raster
// both reuse one Point and mutate it between calls, so a stub that
// closed over the point would report every corner as the last one read.
function snapshotLatLng(span, lat0, lon0, deg) {
  return (p) => {
    const x = p.x, y = p.y;
    return { lat: () => lat0 - (y / span) * deg,
             lng: () => lon0 + (x / span) * deg };
  };
}

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
  // 1, not 0.9: setFrameOpacity pushes the LAPSE's opacity onto the
  // raised frame, and a slider at full is 1. Using 0.9 here would make
  // the opacity numbers below read as a product of two coincidences.
  LAYERS[frameIds[i]].opacity = 1;
  W._refreshRunState();
}

// The Maps API calls onAdd when the overlay joins the map; the stub
// does not, so do it by hand. This is what builds the canvas the
// opacity now rides on.
st.overlay.onAdd();

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

// Dimmed to nothing, but still ON. Every frame goes to opacity 0 and
// none looks "raised" -- yet the lapse is playing and its checkbox is
// ticked. It must keep running, or dragging the raster's opacity down
// would silently kill the particles too.
selectFrame(4);
frameIds.forEach((id) => { LAYERS[id].opacity = 0; });
W._refreshRunState();
out.whenDimmedToZero = { frameId: st.frameId, running: st.running };

// Switched OFF, which is a different thing: no frame is visible. Then
// nothing should be drawing a field nobody can see.
frameIds.forEach((id) => { LAYERS[id].visible = false; });
W._refreshRunState();
out.whenSwitchedOff = { running: st.running };
frameIds.forEach((id) => { LAYERS[id].visible = true; });

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

// Opacity. The raised frame carries the LAPSE's own opacity setting
// (selectFrame pushes timeLapseObj[id].opacity onto it), so it is a
// faithful reading of that slider -- but it has to scale the configured
// particleOpacity, not replace it, and it has to scale the PRISTINE
// value or each drag compounds on the last.
st.cfg.baseOpacity = 0.9; st.cfg.opacity = 0.9;
selectFrame(2);
out.opacityAtFull = +st.canvas.style.opacity;
out.fadeIsEased = /opacity \d+ms/.test(st.canvas.style.transition || "");
frameIds.forEach(function (k) { LAYERS[k].opacity = 0; });
LAYERS[frameIds[2]].opacity = 0.5;          // slider dragged to 50%
W._refreshRunState();
out.opacityAtHalf = +st.canvas.style.opacity;
W._refreshRunState();                        // idle ticks must not compound
W._refreshRunState();
out.opacityAfterIdleTicks = +st.canvas.style.opacity;
// The stroke alpha is the trail's SHAPE and must survive a drag: it is
// taper and head boost, not a user preference.
out.strokeAlphaUntouched = +st.cfg.opacity.toFixed(4);

// A playing lapse zeroes every frame before raising the next. A
// refresh landing in that gap must not blank the layer.
frameIds.forEach(function (k) { LAYERS[k].opacity = 0; });
W._refreshRunState();
out.opacityDuringFrameGap = +st.canvas.style.opacity;

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

// ---- the merged layer: one lapse drawing both halves -----------------
{
  const N2 = 3, LAP = "merged";
  const L2 = {};
  const fids = [];
  const TILE = new Uint8ClampedArray(256 * 256 * 4);
  for (let i = 0; i < 256 * 256; i++) {
    TILE[i * 4] = 200; TILE[i * 4 + 1] = 90;
    TILE[i * 4 + 2] = 128; TILE[i * 4 + 3] = 255;
  }
  for (let i = 0; i < N2; i++) {
    const id = LAP + "-f" + i;
    fids.push(id);
    L2[id] = {
      layerId: i, visible: true, opacity: i === 0 ? 1 : 0, name: id,
      layer: { sh: (c, z) => "https://t.example/" + i + "/" + z + "/" + c.x
                             + "/" + c.y },
      viz: {
        windParticles: true, isTimeLapse: true, timeLapseID: LAP,
        windTileMin: -40, windTileMax: 40, particleColor: "#fff",
        windSpeedRaster: true,
        windSpeedPalette: ["3d6ea3", "4ca44c", "ffffff"],
        windRampMinMs: 0, windRampMaxMs: 30,
        windQueryItem: "SERIALIZED_SPEED_IC",
      },
    };
  }
  sandbox.layerObj = L2;
  sandbox.map.getDiv = () => ({ offsetWidth: 512, offsetHeight: 512 });
  W.scan();
  const mst = W._adopted["tl:" + LAP];
  out.merged = { adopted: !!mst, frames: mst ? Object.keys(mst.frames).length : 0,
                 speedRaster: mst ? mst.cfg.speedRaster : null };

  // onAdd builds BOTH canvases, the raster under the trails.
  mst.overlay.onAdd();
  out.mergedHasSpeedCanvas = !!mst.speedCanvas && !!mst.speedCtx;

  // The query must be retargeted once queryObj exists -- and it did NOT
  // exist at adoption, so this is the retry path.
  out.retargetBeforePanel = mst.queryRetargeted;
  sandbox.queryObj[LAP] = { queryItem: "THE_UV_ENCODING" };
  W._refreshRunState();
  out.retargetAfterPanel = mst.queryRetargeted;
  out.queryItemNow = sandbox.queryObj[LAP].queryItem
    && sandbox.queryObj[LAP].queryItem.decodedFrom;

  // Two opacities, independent. The lapse's own slider drives the
  // raster; particleDim drives the trails.
  mst.cfg.baseOpacity = 0.9;
  fids.forEach((id) => { L2[id].opacity = 0; });
  L2[fids[1]].opacity = 0.4;            // lapse slider at 40%
  mst.particleDim = 1;
  W._refreshRunState();
  out.speedAlphaAt40 = +mst.speedCanvas.style.opacity;
  out.particleAlphaUnaffected = +mst.canvas.style.opacity;
  mst.particleDim = 0.5;                 // particle slider at 50%
  W._refreshRunState();
  out.speedAlphaStill40 = +mst.speedCanvas.style.opacity;
  out.particleAlphaAtHalf = +mst.canvas.style.opacity;
  out.bothCanvasesEased =
    /opacity \d+ms/.test(mst.speedCanvas.style.transition || "") &&
    /opacity \d+ms/.test(mst.canvas.style.transition || "");

  // The raster paints from the tiles the particles already decoded.
  mst.origin = { x: 0, y: 0 }; mst.w = 512; mst.h = 512; mst.tileZoom = 4;
  mst.proj = { fromDivPixelToLatLng: snapshotLatLng(512, 45, -110, 20),
               fromLatLngToDivPixel: (ll) => ({ x: 0, y: 0 }) };
  Object.keys(mst.frames).forEach((fid) => {
    for (let tx = 0; tx < 16; tx++) {
      for (let ty = 0; ty < 16; ty++) {
        mst.tiles[fid + "/4/" + tx + "/" + ty] = TILE;
      }
    }
  });
  out.paintDrew = W._renderSpeedRaster(mst);
  out.paintCached = typeof mst.speedKey === "string";
  out.paintTileDraws = drawnTiles;
  const before = drawnTiles;
  W._ensureSpeedRaster(mst);             // unchanged view: must not repaint
  out.paintSkippedWhenUnchanged = drawnTiles === before;


  mst.frameId = fids[2];                 // new hour: must repaint
  mst.speedKey = null; mst.paintAgainAt = 0;   // as refreshRunState does
  W._ensureSpeedRaster(mst);
  out.paintRedrewOnFrameChange = drawnTiles > before;

  // An INCOMPLETE paint must back off. A repaint is tens of tiles of
  // per-pixel palette lookup; retrying at the animation rate while a
  // lapse streams its next hour locked the tab hard enough that the
  // page stopped answering script at all.
  //
  // Everything cold again -- the one-entry tile memo too, or getTile
  // answers from it and the paint still looks complete.
  mst.tiles = Object.create(null);
  mst.memoData = null; mst.memoFrame = null;
  mst.speedKey = null; mst.paintAgainAt = 0;
  nowFake = 5000;
  W._renderSpeedRaster(mst);
  out.paintBackoffArmed = mst.paintAgainAt > 5000;
  const armedAt = mst.paintAgainAt;
  nowFake = 5000 + 5;
  W._ensureSpeedRaster(mst);
  out.paintHeldWhileBackedOff = mst.paintAgainAt === armedAt;
  nowFake = armedAt + 1;
  W._ensureSpeedRaster(mst);
  // Not measured in DRAWS: the cache is cold and the stubbed Image
  // never resolves, so there is nothing to draw. A paint having RUN is
  // what re-arms the clock.
  out.paintResumedAfterBackoff = mst.paintAgainAt > armedAt;
}

// ---- where the legend entry is filed --------------------------------
// The viewer builds a lapse's legend under the FIRST FRAME's id, not
// the lapse's, because it nulls classLegendDict on every frame but the
// first. Looking only under the lapse id found nothing and returned
// quietly, so the lapse kept the old chip legend while the single-frame
// layer got the colour bar.
{
  const lst = W._adopted["tl:merged"];
  out.legendIdsLapse = W._legendContainerIds(lst);
  out.legendIdsLapseHasFrames =
    Object.keys(lst.frames).every((f) => out.legendIdsLapse.indexOf(f) > -1);
  out.legendIdsLapseFirst = out.legendIdsLapse[0];
  const pst3 = W._adopted["plain"];
  out.legendIdsPlain = pst3 ? W._legendContainerIds(pst3) : null;
}

// ---- the raster's opacity comes from viz.opacity --------------------
// geeViz sets layer.opacity from viz.opacity, so a merged layer added
// with {opacity: 0.6} must start its raster at 0.6, and one added
// without the param at 1 -- not at whatever the particle control says.
{
  const OID = "solo";
  sandbox.layerObj[OID] = {
    layerId: 20, visible: true, opacity: 0.6, name: OID,
    layer: { sh: (c, z) => "https://t.example/solo/" + z },
    viz: {
      windParticles: true, windSpeedRaster: true,
      windTileMin: -40, windTileMax: 40, particleColor: "#fff",
      windSpeedPalette: ["3d6ea3", "4ca44c", "ffffff"],
      windRampMinMs: 0, windRampMaxMs: 30,
    },
  };
  W.scan();
  const sst = W._adopted[OID];
  sst.overlay.onAdd();
  sst.particleDim = 0.3;                 // particle control moved
  W._refreshRunState();
  out.vizOpacityRaster = +sst.speedCanvas.style.opacity;
  out.vizOpacityLeavesParticles = +sst.canvas.style.opacity;
  sandbox.layerObj[OID].opacity = 1;
  W._refreshRunState();
  out.vizOpacityRasterFull = +sst.speedCanvas.style.opacity;
}

// ---- switching the layer OFF must wipe BOTH canvases ----------------
// Reported from a real map: the trails vanished and the speed raster
// stayed painted over the ground, with nothing in the panel able to
// remove it. Only st.ctx was being cleared.
{
  const st2 = W._adopted["tl:merged"] || W._adopted[Object.keys(W._adopted)[0]];
  const fids2 = Object.keys(st2.frames);
  // On, and painted.
  fids2.forEach((k) => { sandbox.layerObj[k].visible = true;
                         sandbox.layerObj[k].opacity = 0; });
  sandbox.layerObj[fids2[0]].opacity = 1;
  W._refreshRunState();
  out.offOnRunningWhileOn = st2.running;

  st2.speedKey = "painted";                 // pretend a complete paint
  const wipesBefore = clearCalls;

  // Off: every frame's checkbox unticked.
  fids2.forEach((k) => { sandbox.layerObj[k].visible = false; });
  W._refreshRunState();
  out.offOnRunningWhileOff = st2.running;
  out.offOnWipedBothCanvases = clearCalls - wipesBefore >= 2;
  out.offOnSpeedKeyForgotten = st2.speedKey === null;

  // ...and back on, which must repaint rather than trust the old key.
  fids2.forEach((k) => { sandbox.layerObj[k].visible = true; });
  W._refreshRunState();
  out.offOnRunningAfterBack = st2.running;
  out.offOnRepaintsOnReturn = st2.speedKey === null;
}

// ---- a REMOVED layer must take its overlay with it ------------------
// Map.clearMap() empties the registry. An overlay whose frames have all
// disappeared has nothing left to draw, and leaving it behind
// accumulates a canvas pair per wind layer ever added.
{
  const st3 = W._adopted[Object.keys(W._adopted)[0]];
  const before = Object.keys(W._adopted).length;
  out.dropHadOverlay = !!st3;
  // Empty the registry, exactly as clearMap does.
  Object.keys(sandbox.layerObj).forEach((k) => delete sandbox.layerObj[k]);
  W._refreshRunState();
  out.dropAdoptedBefore = before;
  out.dropAdoptedAfter = Object.keys(W._adopted).length;
  out.dropCanvasesReleased = st3.canvas === null && st3.speedCanvas === null;
  out.dropTilesReleased = Object.keys(st3.tiles).length === 0;
  out.dropStopped = st3.running === false;
}

console.log(JSON.stringify(out, null, 1));
