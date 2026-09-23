// Drives the real wind-particles.js and reports WHICH MAP PANE the
// canvases land in, plus what the second opacity slider does to its own
// track. Read by test_wind_pane_stacking.py.
//
// Panes are the whole of the first question. `map.overlayMapTypes` --
// every geeViz raster layer, and the satellite Labels overlay, which
// addLabelOverlay() parks at `Object.keys(layerObj).length` so it is
// always the top one -- render as containers inside `mapPane`, stacked
// with small z-indexes. The OverlayView panes sit above all of it:
// mapPane 100, overlayLayer 101, and up from there.
//
// So a canvas in overlayLayer is above EVERY tile layer whatever
// z-index it carries, because z-index only orders siblings within one
// stacking context. applyStacking's careful layerId bookkeeping then
// orders the two wind canvases against each other and nothing else --
// and the satellite labels, which the viewer works to keep on top,
// cannot get there.
"use strict";

const fs = require("fs");
const vm = require("vm");

const SRC = process.argv[2];

// ---- panes, named so the probe can tell which one was used ----------
function makePane(name) {
  return {
    paneName: name,
    children: [],
    appendChild(el) {
      if (el.parentPane) {
        el.parentPane.children = el.parentPane.children.filter(c => c !== el);
      }
      el.parentPane = this;
      this.children.push(el);
    },
  };
}
const PANES = {
  mapPane: makePane("mapPane"),
  overlayLayer: makePane("overlayLayer"),
  overlayShadow: makePane("overlayShadow"),
  markerLayer: makePane("markerLayer"),
  overlayMouseTarget: makePane("overlayMouseTarget"),
  floatPane: makePane("floatPane"),
};

function makeEl(tag) {
  const el = {
    tagName: tag.toUpperCase(),
    style: {
      setProperty(k, v) { this[k.replace(/-(\w)/g, (m, c) => c.toUpperCase())] = v; },
    },
    parentPane: null,
    children: [],
    appendChild(c) { this.children.push(c); },
    setAttribute() {}, getAttribute() { return null; },
    addEventListener() {},
    getContext: () => ({
      clearRect() {}, setTransform() {}, beginPath() {}, moveTo() {},
      lineTo() {}, stroke() {},
      createImageData: (w, h) => ({ width: w, height: h,
                                    data: new Uint8ClampedArray(w * h * 4) }),
      putImageData() {}, drawImage() {}, globalAlpha: 1,
    }),
  };
  return el;
}

const DOM = Object.create(null);

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
  getElementById: (id) => DOM[id] || null,
  createElement: makeEl,
  head: makeEl("head"),
  documentElement: makeEl("html"),
};
sandbox.google = {
  maps: {
    Point: function (x, y) { this.x = x; this.y = y; },
    OverlayView: function () {
      this.setMap = function () {};
      this.getPanes = () => PANES;
      this.getProjection = () => null;
    },
  },
};
function MVCArray() { this.a = []; }
MVCArray.prototype.setAt = function (i, v) {
  while (this.a.length < i) this.a.push(undefined);
  this.a[i] = v;
};
MVCArray.prototype.getArray = function () { return this.a; };
MVCArray.prototype.getAt = function (i) { return this.a[i]; };
const overlay = new MVCArray();
sandbox.map = {
  overlayMapTypes: overlay,
  addListener() {},
  getZoom: () => 4,
  getCenter: () => ({ lat: () => 40, lng: () => -100 }),
};

// Two layers: the wind, and something above it (the satellite Labels
// overlay behaves the same way -- an overlayMapType at a higher index).
const LAYERS = {
  Wind: {
    layerId: 0, visible: true, opacity: 0.8, name: "Wind",
    layer: { sh: (c, z) => "https://tiles.example/" + z },
    viz: { windParticles: true, windSpeedRaster: true,
           windTileMin: -40, windTileMax: 40,
           opacity: 0.8, windParticleDim: 0.8 },
  },
};
sandbox.layerObj = LAYERS;
overlay.setAt(0, "WIND_UV_TILES");
sandbox.queryObj = {};
sandbox.Image = function () { this.onload = null; this.onerror = null; };
sandbox.ee = { Deserializer: { fromJSON: (raw) => ({ decodedFrom: raw }) } };

// ---- just enough jQuery to run addParticleSlider --------------------
// The host is the viewer's OWN opacity control, painted with an inline
// rgba() background whose alpha is the speed raster's opacity -- which
// is a different number from the particles' whenever windSpeedOpacity
// is set, and the reason only the RGB may be copied from it.
const HOST_ID = "Wind-opacity";
const hostEl = makeEl("div");
hostEl.style.backgroundColor = "rgba(55, 46, 44, 0.3)";
// The real host carries the viewer's own slider classes plus jQuery
// UI's. The copy must keep the former and drop the latter.
hostEl.className = "simple-layer-opacity-range ui-slider ui-widget";
DOM[HOST_ID] = hostEl;

const sliderOpts = {};
function $(sel) {
  const id = typeof sel === "string" && sel.charAt(0) === "#"
      ? sel.slice(1) : null;
  const el = id ? DOM[id] : null;
  const api = {
    length: el ? 1 : 0,
    0: el,
    addClass(c) { if (el) el.className = ((el.className || "") + " " + c).trim();
                  return api; },
    // One arg reads, two write -- the module reads `class` off the
    // host to clone it, and a stub returning `this` there makes the
    // copy inherit jQuery UI's own classes.
    attr(k, v) {
      if (arguments.length === 1) {
        return k === "class" ? (el ? el.className || "" : "") : null;
      }
      if (el) el[k] = v;
      return api;
    },
    text() { return api; },
    closest() { return { addClass() {} }; },
    // restyleLegend walks the class-legend markup, which this probe
    // does not build. An empty set makes it give up quietly, which
    // is the same thing it does before the panel exists.
    find() { return $("#__none__"); },
    first() { return $("#__none__"); },
    each() { return api; },
    append() { return api; },
    empty() { return api; },
    html() { return api; },
    is() { return false; },
    children() { return $("#__none__"); },
    parent() { return $("#__none__"); },
    remove() { return api; },
    css(prop) {
      if (arguments.length === 1) {
        return el ? el.style[prop.replace(/-(\w)/g, (m, c) => c.toUpperCase())]
                  : undefined;
      }
      return api;
    },
    before(html) {
      // The module builds the slider markup as a string; register the
      // ids it names so later lookups resolve.
      const m = /id='([^']+)'/g;
      let g;
      while ((g = m.exec(html))) DOM[g[1]] = makeEl("div");
      return api;
    },
    slider(opts) {
      if (opts && typeof opts === "object") sliderOpts[id] = opts;
      return api;
    },
  };
  return api;
}
sandbox.$ = $;
sandbox.jQuery = $;


// ---- the viewer's own drag-reorder, as the sortable calls it --------
// It reassigns every layerId and then re-ADDS each visible layer,
// which for a wind layer puts the encoded u/v RGB back on the map.
sandbox.updateMapLayerOrder = function () {
  reorderCalls++;
  const ids = Object.keys(LAYERS);
  ids.forEach((id, i) => { LAYERS[id].layerId = NEW_ORDER[id]; });
  ids.forEach((id) => {
    const L = LAYERS[id];
    if (L.visible) overlay.setAt(L.layerId, L.layer);
  });
};
let reorderCalls = 0;
let NEW_ORDER = {};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, { filename: SRC });
const W = sandbox.geeVizWindParticles;

const out = {};

// ---- 1. adoption, then which pane the canvases land in --------------
W.scan();
const st = W._adopted["Wind"];
out.adopted = !!st;
st.overlay.onAdd();

out.particlePane = st.canvas ? st.canvas.parentPane.paneName : null;
out.speedPane = st.speedCanvas ? st.speedCanvas.parentPane.paneName : null;
out.panesUsed = Object.keys(PANES)
    .filter(k => PANES[k].children.length)
    .sort();

// Within the pane, the raster must be appended BEFORE the trails: they
// share a z-index and a tie is broken by DOM order.
const kids = PANES[out.particlePane].children;
out.speedBeforeParticles =
    kids.indexOf(st.speedCanvas) < kids.indexOf(st.canvas);

// ---- 2. a drag reorder must move BOTH canvases ---------------------
out.zBefore = { particle: st.canvas.style.zIndex,
                speed: st.speedCanvas.style.zIndex };

// The patch has to be installed by now -- scan() does it.
out.reorderPatched = typeof sandbox.updateMapLayerOrder._geeVizOriginal
                     === "function";

// Drag the wind layer up: the viewer gives it layerId 3.
NEW_ORDER = { Wind: 3 };
sandbox.updateMapLayerOrder();

out.origWasCalled = reorderCalls === 1;
out.zAfterDrop = { particle: st.canvas.style.zIndex,
                   speed: st.speedCanvas.style.zIndex };
// ...WITHOUT waiting for the 500 ms refresh tick.
out.repairedSynchronously =
    st.canvas.style.zIndex === "3" && st.speedCanvas.style.zIndex === "3";
// ...and the encoded RGB the reorder put back must be off again.
out.slotAfterDrop = overlay.getAt(3) === null;

// The tick agreeing is not the same as the drop having done it, so check
// it separately: it must be idempotent, not a second correction.
W._refreshRunState();
out.zAfterTick = { particle: st.canvas.style.zIndex,
                   speed: st.speedCanvas.style.zIndex };

// ---- 3. applyStacking with no canvas named does both ----------------
st.canvas.style.zIndex = "99";
st.speedCanvas.style.zIndex = "99";
if (typeof W._applyStacking === "function") {
  W._applyStacking(st);
  out.bothRestacked = { particle: st.canvas.style.zIndex,
                        speed: st.speedCanvas.style.zIndex };
} else {
  out.bothRestacked = "seam absent";
}

// ---- 4. patching twice must not double-wrap -------------------------
const wrappedOnce = sandbox.updateMapLayerOrder;
if (typeof W._patchReorder === "function") {
  W._patchReorder();
  out.patchIsIdempotent = sandbox.updateMapLayerOrder === wrappedOnce;
} else {
  out.patchIsIdempotent = "seam absent";
}

// ---- 5. a repair that throws must not break the viewer's reorder ----
{
  const savedReg = sandbox.layerObj;
  const before = reorderCalls;
  let threw = false;
  // applyStacking reads the registry; make reading it explode.
  Object.defineProperty(sandbox, "layerObj",
      { get() { throw new Error("boom"); }, configurable: true });
  try { sandbox.updateMapLayerOrder(); } catch (e) { threw = true; }
  Object.defineProperty(sandbox, "layerObj",
      { value: savedReg, writable: true, configurable: true });
  out.reorderSurvivesRepairFailure = !threw && reorderCalls === before + 1;
}

// ---- 3. the slider track -------------------------------------------
out.rgbOfTrack = {
  fromRgba: W._rgbOfTrack("rgba(55, 46, 44, 0.3)"),
  fromRgb: W._rgbOfTrack("rgb(1, 2, 3)"),
  fromSpaces: W._rgbOfTrack("rgba(10,20,30,1)"),
  // A theme that never painted the control, or a named color: fall back
  // to the viewer's own track rather than to nothing, because nothing
  // renders as jQuery UI's default grey next to a painted twin.
  fromEmpty: W._rgbOfTrack(""),
  fromNamed: W._rgbOfTrack("transparent"),
};

const SID = "Wind-particle-opacity-slider";
out.sliderBuilt = !!DOM[SID];
out.sliderStartsAtParticleDim =
    sliderOpts[SID] ? sliderOpts[SID].value : null;
// The track must START at the particles' opacity, NOT at the host's
// alpha -- the host is showing the speed raster's, 0.3 here.
out.trackAtCreate = DOM[SID] ? DOM[SID].style.backgroundColor : null;

// ...and follow the handle as it is dragged, the way the viewer's own
// setRangeSliderThumbOpacity does.
sliderOpts[SID].slide({}, { value: 0.25 });
out.trackAfterDrag = DOM[SID].style.backgroundColor;
out.dimAfterDrag = st.particleDim;
sliderOpts[SID].slide({}, { value: 1 });
out.trackAtFull = DOM[SID].style.backgroundColor;

console.log(JSON.stringify(out, null, 1));
