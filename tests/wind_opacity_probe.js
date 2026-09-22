// Drives the real wind-particles.js and reports the alpha that actually
// lands on each of the two canvases. Read by test_wind_opacity.py.
//
// A grouped wind layer draws TWO things from one set of tiles, so the
// question "what does viz opacity do" has two answers and they are set
// in different places. The raster rides the viewer's own opacity slider,
// which it gets from `viz.opacity` for free. The particle canvas rides
// `st.particleDim`, a control the viewer has never heard of -- and that
// sat hard-coded at 1, so `opacity` dimmed half the picture.
//
// None of that is visible from the source: both values flow through
// refreshRunState into setCanvasAlpha, and the only way to tell whether
// a number reached the pixels is to read the element it was written to.
"use strict";

const fs = require("fs");
const vm = require("vm");

const SRC = process.argv[2];

// ---- the browser, as much of it as the module touches ---------------
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
  getElementById: () => null,
  createElement: () => ({
    width: 0, height: 0, style: {},
    getContext: () => ({
      clearRect() {}, setTransform() {}, beginPath() {}, moveTo() {},
      lineTo() {}, stroke() {},
      createImageData: (w, h) => ({ width: w, height: h,
                                    data: new Uint8ClampedArray(w * h * 4) }),
      putImageData() {}, drawImage() {}, globalAlpha: 1,
    }),
  }),
};
sandbox.google = {
  maps: {
    Point: function (x, y) { this.x = x; this.y = y; },
    OverlayView: function () {
      this.setMap = function () {};
      this.getPanes = () => ({ overlayLayer: { appendChild() {} } });
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
const LAYERS = Object.create(null);
sandbox.layerObj = LAYERS;
sandbox.queryObj = {};
sandbox.Image = function () { this.onload = null; this.onerror = null; };
sandbox.ee = { Deserializer: { fromJSON: (raw) => ({ decodedFrom: raw }) } };
// No jQuery: addParticleSlider's slider() call throws and is caught, so
// the DOM control is skipped while st.particleDim -- the thing that
// actually reaches the canvas -- is still set from the viz. That is the
// separation being tested, so it is deliberate.

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, { filename: SRC });
const W = sandbox.geeVizWindParticles;

let slot = 0;

/** Add one grouped wind layer with the given viz, adopt it, and report
 *  the alpha on each canvas. */
function paint(name, viz) {
  const id = name;
  LAYERS[id] = {
    layerId: slot, visible: true, name: id,
    // What the viewer puts on the registry entry: the layer's live
    // opacity, seeded from viz.opacity. The raster follows THIS.
    opacity: viz.opacity !== undefined ? viz.opacity : 1,
    layer: { sh: (c, z) => "https://tiles.example/" + z },
    viz: Object.assign({
      windParticles: true, windTileMin: -40, windTileMax: 40,
    }, viz),
  };
  overlay.setAt(slot, "UV_TILES_" + slot);
  slot++;

  W.scan();
  const st = W._adopted[id];
  if (!st) return { adopted: false };
  st.overlay.onAdd();          // the Maps API would; the stub does not
  W._refreshRunState();

  return {
    adopted: true,
    particleDim: st.particleDim,
    speedOpacity: st.cfg.speedOpacity,
    speedRaster: st.cfg.speedRaster,
    // THE PIXELS. setCanvasAlpha writes these.
    speedCanvasAlpha: st.speedCanvas ? +st.speedCanvas.style.opacity : null,
    particleCanvasAlpha: st.canvas ? +st.canvas.style.opacity : null,
    // The trail's own stroke alpha is a separate, unscaled thing.
    strokeAlpha: st.cfg.opacity,
  };
}

const out = {};

// ---- 1. the reported bug --------------------------------------------
// opacity 0.8 on a grouped layer must dim BOTH halves.
out.grouped08 = paint("grouped-0.8", {
  windSpeedRaster: true, opacity: 0.8, windParticleDim: 0.8,
});

// ---- 2. default is untouched ----------------------------------------
out.groupedDefault = paint("grouped-default", {
  windSpeedRaster: true, opacity: 1, windParticleDim: 1,
});

// ---- 3. windSpeedOpacity splits the two -----------------------------
// weather.py folds it into viz.opacity (the raster's slider) and leaves
// the master on windParticleDim.
out.split = paint("grouped-split", {
  windSpeedRaster: true, opacity: 0.3, windParticleDim: 0.8,
});

// ---- 4. a hand-built viz falls back to opacity ----------------------
// Someone setting windParticles directly, not going through
// addWindLayer, has no windParticleDim. Reading 1 there is the old bug
// wearing a different hat.
out.fallback = paint("grouped-fallback", {
  windSpeedRaster: true, opacity: 0.4,
});

// ---- 5. out-of-range is clamped, not propagated ---------------------
out.clampHigh = paint("clamp-high", {
  windSpeedRaster: true, opacity: 1, windParticleDim: 7,
});
out.clampLow = paint("clamp-low", {
  windSpeedRaster: true, opacity: 1, windParticleDim: -3,
});

// ---- 6. UNGROUPED: particles are their own layer ---------------------
// No raster here, so the particle canvas follows the layer's own opacity
// slider -- and must NOT also be scaled by particleDim, or the two would
// multiply and 0.8 would render as 0.64.
out.ungrouped = paint("ungrouped", { opacity: 0.8 });

// ---- 7. the sliders stay independent afterwards ----------------------
{
  const st = W._adopted["grouped-0.8"];
  st.particleDim = 0.25;
  W._refreshRunState();
  out.afterParticleDrag = {
    particle: +st.canvas.style.opacity,
    speedUnchanged: +st.speedCanvas.style.opacity,
  };
  // ...and the raster's slider moves the raster alone.
  LAYERS["grouped-0.8"].opacity = 0.5;
  W._refreshRunState();
  out.afterSpeedDrag = {
    speed: +st.speedCanvas.style.opacity,
    particleUnchanged: +st.canvas.style.opacity,
  };
}

// ---- 8. particleOpacity is a separate, unscaled knob -----------------
// It is the alpha at the trail head -- a look, not a dimmer -- and must
// not be folded into the layer opacity or the two would compound.
out.strokeIsIndependent = paint("stroke", {
  windSpeedRaster: true, opacity: 0.5, windParticleDim: 0.5,
  particleOpacity: 0.9,
}).strokeAlpha;

console.log(JSON.stringify(out, null, 1));
