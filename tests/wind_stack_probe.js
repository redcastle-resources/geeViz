/**
 * Does the particle module keep every OTHER layer's overlay slot intact?
 *
 * google.maps.MVCArray is POSITIONAL, and the viewer leans on that
 * entirely: each layer owns the fixed index recorded in layer.layerId,
 * shows itself with setAt(layerId, layer) and hides itself with
 * setAt(layerId, null). Nothing in the viewer ever removeAt()s a layer
 * slot, because removeAt shifts every higher entry down one while the
 * layerId values that address them do not move.
 *
 * This stubs an overlayMapTypes with those exact semantics, drives the
 * module's detach through a refresh, and then replays the viewer's own
 * turnOn / turnOff / updateMapLayerOrder against the result.
 */
"use strict";

function MVCArray() { this.a = []; }
MVCArray.prototype.setAt = function (i, v) {
  while (this.a.length < i) this.a.push(undefined);
  this.a[i] = v;
};
MVCArray.prototype.removeAt = function (i) { return this.a.splice(i, 1)[0]; };
MVCArray.prototype.getArray = function () { return this.a; };
MVCArray.prototype.getAt = function (i) { return this.a[i]; };

// Three layers in slots 0..2; the particle layer is the middle one, so
// a shift is visible on the layer above it.
var LAYERS = {
  speed:     { layerId: 0, visible: true,  layer: "SPEED_TILES",  name: "speed" },
  particles: { layerId: 1, visible: true,  layer: "UV_TILES",     name: "particles" },
  terrain:   { layerId: 2, visible: true,  layer: "TERRAIN_TILES", name: "terrain" },
};

var overlay = new MVCArray();
Object.keys(LAYERS).forEach(function (k) {
  overlay.setAt(LAYERS[k].layerId, LAYERS[k].layer);
});

var global = {
  map: {
    overlayMapTypes: overlay,
    addListener: function () {},
    getZoom: function () { return 5; },
  },
  document: { hidden: false, createElement: function () { return {}; } },
  requestAnimationFrame: function () { return 1; },
  layerObj: LAYERS,
};

// --- the module's detach, as written -------------------------------------
var fs = require("fs");
var src = fs.readFileSync(process.argv[2], "utf8");
var body = src.slice(src.indexOf("function detach(L)"));
body = body.slice(0, body.indexOf("\n  }") + 4);
var detach = new Function("global", body + "; return detach;")(global);

detach(LAYERS.particles);
// Repeatable: the viewer re-adds the RGB on every re-check.
detach(LAYERS.particles);
detach(LAYERS.particles);

var out = { afterDetach: overlay.getArray().slice() };

// --- now replay the viewer's own operations ------------------------------
function turnOff(L) { L.visible = false; overlay.setAt(L.layerId, null); }
function turnOn(L) { L.visible = true; overlay.setAt(L.layerId, L.layer); }

turnOff(LAYERS.terrain);
turnOn(LAYERS.terrain);
out.terrainRoundTrip = overlay.getArray().slice();

// updateMapLayerOrder: reverse the list, reassign layerIds from the
// sorted set, re-add the visible ones.
var order = ["terrain", "particles", "speed"];
var slots = order.map(function (k) { return LAYERS[k].layerId; })
                 .sort(function (a, b) { return a - b; });
order.forEach(function (k, i) { LAYERS[k].layerId = slots[i]; });
order.forEach(function (k) {
  var L = LAYERS[k];
  overlay.setAt(L.layerId, L.visible ? L.layer : null);
});
detach(LAYERS.particles);          // module re-nulls on its refresh tick
out.afterReorder = overlay.getArray().slice();
out.layerIds = {};
Object.keys(LAYERS).forEach(function (k) { out.layerIds[k] = LAYERS[k].layerId; });
out.length = overlay.getArray().length;

console.log(JSON.stringify(out, null, 1));
