/**
 * Animated wind particles for geeViz, in the style of windy.com.
 *
 * Two layers make the picture, and the raster is the louder one: a
 * smooth speed field underneath (an ordinary geeViz image layer,
 * bicubic-resampled and queryable) with thin fading trails over the
 * top. This file draws only the trails.
 *
 * ---------------------------------------------------------------------
 * WHERE THE NUMBERS COME FROM
 * ---------------------------------------------------------------------
 * From the TILES, decoded. Earth Engine renders u and v into the red and
 * green channels of ordinary PNG map tiles, linearly stretched from
 * WIND_TILE_MIN/MAX m/s onto 0..255 (see geeViz.weather.windTiles). The
 * client fetches the tiles it is looking at, reads their pixels through
 * an offscreen canvas, and inverts the stretch.
 *
 * The stretch is HARD-CODED here and in Python, deliberately. It is the
 * one number both sides must agree on, and a mismatch does not throw --
 * it yields wrong-but-plausible winds, which look like weather rather
 * than like a bug.
 *
 * The predecessor shipped a JSON lattice sampled once over a fixed
 * region. It worked, but panning past the edge of that region simply
 * stopped the animation, and a continent's worth of lattice was ~200 KB
 * on the wire. Tiles stream with the view instead: pan anywhere, at any
 * zoom, and the data follows.
 *
 * ---------------------------------------------------------------------
 * ATTACHMENT
 * ---------------------------------------------------------------------
 * The encoded image is added as a normal geeImage layer, so the viewer
 * mints its tile URL and builds a real layer-list entry (checkbox,
 * opacity). This file then takes the layer OFF the map -- the raw RGB is
 * nonsense to look at -- and keeps its `getTileUrl` to fetch tiles
 * numerically.
 *
 * `layerObj` is declared as a top-level `let`, so it lives in the global
 * LEXICAL environment and is NOT a property of `window`; a bare
 * reference resolves it while `window.layerObj` is undefined.
 *
 * ---------------------------------------------------------------------
 * COST
 * ---------------------------------------------------------------------
 * A real animation loop, so it must not run unseen: it stops when the
 * layer is unchecked and when the page is hidden. An invisible rAF loop
 * draining a battery is how this kind of layer becomes a regret.
 */
(function (global) {
  "use strict";

  // FALLBACK ONLY. The live values arrive per layer in viz
  // (windTileMin/windTileMax) straight from geeViz.weather, so Python is
  // the single source of truth and the two cannot drift. These stand in
  // if a layer is somehow missing them.
  var TILE_MIN = -40.0;
  var TILE_MAX = 40.0;
  var TILE_PX = 256;

  // How far off-canvas a particle may drift before it is recycled.
  // Enough that a trail entering the view is already grown, small
  // enough that nothing far outside keeps pulling tiles.
  var CULL_MARGIN = 64;

  var adopted = Object.create(null);
  var rafId = null;
  var bound = false;

  /**
   * The tile-URL builder on a google.maps.ImageMapType.
   *
   * The viewer constructs the layer as
   * ``new google.maps.ImageMapType({getTileUrl: fn})``, but the Maps API
   * stores that callback under a MINIFIED name -- observed as ``sh`` --
   * so ``layer.getTileUrl`` is undefined. The minified name changes
   * between Maps releases, and ``getTile()`` returns a container DIV
   * whose <img> is populated asynchronously, so neither is dependable.
   *
   * Probe instead: call each own function with a throwaway coordinate
   * and keep the one that answers with a URL string. Version-proof, and
   * it validates itself rather than trusting a name.
   */
  function findTileUrlFn(mapType) {
    if (typeof mapType.getTileUrl === "function") {
      return mapType.getTileUrl.bind(mapType);
    }
    for (var k in mapType) {
      if (typeof mapType[k] !== "function") continue;
      try {
        var r = mapType[k]({ x: 0, y: 0 }, 0);
        if (typeof r === "string" && /^https?:\/\//.test(r)) {
          return mapType[k].bind(mapType);
        }
      } catch (e) { /* not it */ }
    }
    return null;
  }

  /**
   * Take the encoded RGB off the map, and settle the viewer's spinner.
   *
   * Two things the viewer does not expect from us.
   *
   * The u/v tiles are an ENCODING, not a picture -- left visible they
   * paint the world flat red and green. So the ImageMapType comes off
   * the overlay stack. But the viewer re-adds it from scratch every
   * time the layer is unchecked and re-checked
   * (``overlayMapTypes.setAt(...)`` in its visibility handler), and by
   * then this module has already adopted the layer and skips it -- so
   * the raster came back and stayed. Detaching has to be repeatable,
   * and cheap enough to run on every refresh tick.
   *
   * The spinner is handled separately, by :func:`reportProgress`.
   */
  function detach(L) {
    if (!L) return;
    try { L.layer && L.layer.setMap && L.layer.setMap(null); } catch (e) {}
    try {
      var arr = global.map.overlayMapTypes.getArray();
      for (var i = arr.length - 1; i >= 0; i--) {
        if (arr[i] === L.layer) global.map.overlayMapTypes.removeAt(i);
      }
    } catch (e) {}
  }

  /**
   * Report tile progress to the viewer, honestly.
   *
   * The viewer sets ``layer.loading = true`` inside its own
   * ``getTileUrl`` and clears it when the ImageMapType fires
   * ``tilesloaded``. This module calls ``getTileUrl`` directly -- that
   * is how it fetches tiles -- and has taken the map type off the map,
   * so the event never fires. Both halves are ours, so reporting is too.
   *
   * The first cut simply forced ``loading = false`` once. That stopped
   * the spinner spinning forever, but it also meant the layer NEVER
   * reported loading again: panning to fresh ground fetches a new batch
   * of tiles and the status bar showed nothing happening. So the state
   * is derived from the actual in-flight count instead of pinned.
   *
   * ``burst`` is the number of tiles requested since the queue was last
   * empty, which is what makes the percentage move rather than jump: it
   * resets on each pan, so a pan reads 0..100 over its own batch rather
   * than as a fraction of every tile ever cached.
   */
  function reportProgress(st) {
    var reg = registry();
    var L = reg && reg[st.id];
    if (!L) return;

    var inflight = st.inflight || 0;
    var burst = st.burst || 0;
    var loading = inflight > 0;
    var percent = loading
      ? Math.max(5, Math.round((100 * (burst - inflight)) / burst))
      : 100;

    if (L.loading === loading && L.percent === percent) return;
    L.loading = loading;
    L.percent = percent;

    // The viewer derives both element ids from the layerObj key.
    var eid = st.id;
    try {
      if (global.$) {
        var sp = global.$("#" + eid + "-spinner2");
        if (loading) sp.show(); else sp.hide();
      }
    } catch (e) {}

    // The white fill across the layer row. The viewer paints this from
    // a CLOSURE -- ``updateProgress`` is defined per layer and captures
    // its own ``layer`` and container id, so it is not reachable from
    // here. (The global of the same name is a different function taking
    // ``(id, val)``; calling it did nothing, which is why the bar sat
    // still after the first load.) Painting the same gradient directly
    // is the only way in, and it must match the viewer's exactly or the
    // row will look different from every other layer.
    try {
      if (global.$) {
        global.$("#" + eid + "-layer-container").css(
          "background",
          "-webkit-linear-gradient(left, #FFF, #FFF " + percent +
          "%, transparent " + percent + "%, transparent 100%)");
      }
    } catch (e) {}

    // The counter in the status bar IS a global. Ask it to recount
    // rather than adjusting it here and risking a drift.
    try {
      if (typeof global.updateGEETileLayersDownloading === "function") {
        global.updateGEETileLayersDownloading();
      }
    } catch (e) {}
  }

  /** One tile entered the queue. */
  function tileStarted(st) {
    st.inflight = (st.inflight || 0) + 1;
    // A burst is a batch of requests bracketed by an empty queue -- a
    // pan, typically. Counting from zero each time is what lets the
    // percentage climb instead of creeping toward an ever-growing total.
    st.burst = (st.inflight === 1) ? 1 : (st.burst || 0) + 1;
    reportProgress(st);
  }

  /** ...and one left it, successfully or not. Both must count, or a
   *  single 404 leaves the layer loading forever. */
  function tileFinished(st) {
    st.inflight = Math.max(0, (st.inflight || 1) - 1);
    reportProgress(st);
  }

  function registry() {
    try {
      if (typeof layerObj !== "undefined" && layerObj) return layerObj;
    } catch (e) { /* declared later */ }
    return global.layerObj || null;
  }

  // ---- Web Mercator -------------------------------------------------

  function lonToTileX(lon, z) {
    return ((lon + 180) / 360) * Math.pow(2, z);
  }

  function latToTileY(lat, z) {
    var r = (lat * Math.PI) / 180;
    return ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) *
           Math.pow(2, z);
  }

  // ---- tile cache ---------------------------------------------------

  /**
   * Decoded pixels for one tile, or null while it loads.
   *
   * Tiles are fetched once and kept. `crossOrigin` is required: without
   * it the canvas is tainted and getImageData throws a SecurityError, so
   * every decode silently yields nothing.
   */
  function getTile(st, z, x, y) {
    var key = z + "/" + x + "/" + y;
    var hit = st.tiles[key];
    if (hit !== undefined) return hit;
    st.tiles[key] = null;                      // in flight

    var url;
    try {
      url = st.getTileUrl({ x: x, y: y }, z);
    } catch (e) { st.tiles[key] = false; return null; }
    if (!url) { st.tiles[key] = false; return null; }
    tileStarted(st);

    var img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = function () {
      tileFinished(st);
      try {
        var c = document.createElement("canvas");
        c.width = TILE_PX; c.height = TILE_PX;
        var cx = c.getContext("2d");
        cx.drawImage(img, 0, 0, TILE_PX, TILE_PX);
        st.tiles[key] = cx.getImageData(0, 0, TILE_PX, TILE_PX).data;
      } catch (e) {
        st.tiles[key] = false;                 // tainted / undecodable
        if (!st.warned) {
          st.warned = true;
          console.warn("wind particles: tile pixels unreadable", e);
        }
      }
    };
    img.onerror = function () { st.tiles[key] = false; tileFinished(st); };
    img.src = url;
    return null;
  }

  /**
   * One decoded (u, v) pixel, addressed in GLOBAL pixel coordinates.
   *
   * Global rather than per-tile so that one function owns the whole
   * decode: which tile a coordinate falls in, the dateline wrap, the
   * transparent-means-no-data check, and the byte-to-m/s stretch. The
   * caller works in pixels and never has to know about tile edges.
   */
  function pixelUV(st, z, gx, gy) {
    var n = Math.pow(2, z), W = n * TILE_PX;
    gx = Math.floor(gx); gy = Math.floor(gy);
    if (gy < 0 || gy >= W) return null;
    gx = ((gx % W) + W) % W;                   // wrap the dateline
    var data = getTile(st, z, Math.floor(gx / TILE_PX), Math.floor(gy / TILE_PX));
    if (!data) return null;
    var i = ((gy % TILE_PX) * TILE_PX + (gx % TILE_PX)) * 4;
    if (data[i + 3] === 0) return null;        // transparent = no data
    // Red carries u, green carries v -- the order the encoder used.
    var lo = st.cfg.tileMin, span = st.cfg.tileMax - lo;
    return [lo + (data[i] / 255) * span, lo + (data[i + 1] / 255) * span];
  }

  /**
   * (u, v, magnitude) at a lat/lon, or null. Nearest pixel.
   *
   * No interpolation here, deliberately. ``windTiles`` applies
   * ``resample('bicubic')`` before ``visualize()``, so Earth Engine has
   * already smoothed the field into the tile -- measured on a GFS tile
   * at zoom 10, the unresampled version runs to 176 identical pixels in
   * a row where the bicubic one runs to 45, with a maximum step of 6
   * against 2.
   *
   * A client-side blend on top of that is work already paid for, done
   * worse (bilinear against bicubic) and repeated for every particle of
   * every frame rather than once per tile. Worse still, what remains
   * after the bicubic is 8-BIT QUANTIZATION -- 0.31 m/s per level --
   * and interpolating between two equal bytes returns the same byte, so
   * there is nothing left for it to recover.
   *
   * The one thing that does matter is that the tiles are fetched near
   * display resolution, which is what ``particleMaxTileZoom`` governs.
   * Capping it low forces the client to sample a coarse grid and then
   * interpolate its way back to smooth -- the long way round.
   */
  function sampleUV(st, lat, lon) {
    if (lat > 85 || lat < -85) return null;
    var z = st.tileZoom;
    var uv = pixelUV(st, z, lonToTileX(lon, z) * TILE_PX,
                     latToTileY(lat, z) * TILE_PX);
    if (!uv) return null;
    // Magnitude here rather than in the caller: every caller wants it,
    // it is one sqrt either way, and returning it keeps frame() from
    // recomputing a number already in hand.
    return [uv[0], uv[1], Math.sqrt(uv[0] * uv[0] + uv[1] * uv[1])];
  }

  function hexToRgb(h) {
    h = String(h || "#fff").replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var n = parseInt(h, 16);
    return isNaN(n) ? [255, 255, 255] : [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  // ---- overlay ------------------------------------------------------

  function makeOverlay(st) {
    var ov = new google.maps.OverlayView();

    ov.onAdd = function () {
      var c = document.createElement("canvas");
      c.style.position = "absolute";
      c.style.pointerEvents = "none";      // never eat a query click
      c.style.left = "0px";
      c.style.top = "0px";
      st.canvas = c;
      st.ctx = c.getContext("2d");
      this.getPanes().overlayLayer.appendChild(c);
    };

    ov.draw = function () {
      if (!st.canvas) return;
      var proj = this.getProjection();
      if (!proj) return;
      var div = global.map.getDiv();
      var w = div.offsetWidth, h = div.offsetHeight;

      // Anchor via CONTAINER pixels, not map bounds.
      //
      // getBounds() is undefined until the map's first idle, and the old
      // version early-returned on that -- so the whole layer rendered
      // nothing at all until an idle happened to fire. Container pixels
      // are available as soon as there is a projection.
      var originLatLng = proj.fromContainerPixelToLatLng(
        new google.maps.Point(0, 0));
      if (!originLatLng) return;
      var p = proj.fromLatLngToDivPixel(originLatLng);
      st.canvas.style.left = p.x + "px";
      st.canvas.style.top = p.y + "px";
      if (st.canvas.width !== w || st.canvas.height !== h) {
        st.canvas.width = w; st.canvas.height = h;
        st.particles = null;
      }
      st.origin = p; st.proj = proj; st.w = w; st.h = h;
      // Tiles track the map, so Earth Engine's bicubic is evaluated at
      // roughly the resolution it will be shown at and the client can
      // sample the nearest pixel and be done.
      //
      // The cap only stops the pointless extreme: past zoom 10 a tile
      // pixel is under 150 m against a 28 km forecast grid, so finer
      // tiles carry no more information. It is NOT what bounds the
      // request count -- the off-screen cull in frame() does that, and
      // it is what took a zoom-10 view from 1559 tiles to the ~35 the
      // viewport actually needs.
      st.tileZoom = Math.max(
        0, Math.min(st.cfg.maxTileZoom, global.map.getZoom() || 4));
    };

    ov.onRemove = function () {
      if (st.canvas && st.canvas.parentNode) {
        st.canvas.parentNode.removeChild(st.canvas);
      }
      st.canvas = null; st.ctx = null;
    };

    return ov;
  }

  /** Random point in the visible container, in lat/lng. No bounds needed. */
  /**
   * Precompute the wind for the whole viewport, once per view.
   *
   * This is the shape cambecc's windy.js uses, and the reason it can
   * animate thousands of particles cheaply: for each cell of a coarse
   * canvas grid, resolve the wind ONCE and store it already converted
   * to PIXELS PER FRAME. Particles then live in canvas coordinates and
   * advancing one is two array reads and two adds -- no projection, no
   * cos(lat), no zoom scaling, no tile lookup, none of it per particle
   * per frame.
   *
   * The arithmetic that used to run 240,000 times a second (4000
   * particles at 60fps) now runs about 130,000 times per VIEW CHANGE,
   * and not at all while the map sits still.
   *
   * It has to be rebuilt on pan and zoom, not merely on resize: canvas
   * pixel (0, 0) means a different place on the globe after a pan, so
   * every cached vector is wrong. Rebuilding is tied to the map's idle
   * event, so it happens once when movement stops rather than during
   * the drag.
   */
  function buildField(st) {
    if (!st.proj || !st.w || !st.h) return false;
    var cfg = st.cfg;
    var sp = cfg.fieldSpacing;
    var gw = Math.ceil(st.w / sp) + 1, gh = Math.ceil(st.h / sp) + 1;
    var zoom = global.map && global.map.getZoom();
    if (zoom === undefined || zoom === null) return false;

    // One scalar for the whole field: seconds-per-frame of advection,
    // normalised so a streak is the same length on screen at any zoom.
    // Metres-per-pixel still varies with latitude, so that part stays
    // inside the loop.
    var advance = cfg.speedFactor * Math.pow(2, cfg.zoomRef - zoom);
    var mppEquator = 156543.03392 / Math.pow(2, zoom);

    var f = new Float32Array(gw * gh * 2);
    var ok = new Uint8Array(gw * gh);
    var ox = st.origin.x, oy = st.origin.y, proj = st.proj;
    var pt = new google.maps.Point(0, 0);
    var any = false;

    for (var gy = 0; gy < gh; gy++) {
      for (var gx = 0; gx < gw; gx++) {
        pt.x = gx * sp + ox;
        pt.y = gy * sp + oy;
        var ll = proj.fromDivPixelToLatLng(pt);
        if (!ll) continue;
        var lat = ll.lat();
        var uv = sampleUV(st, lat, ll.lng());
        if (!uv) continue;

        var u = uv[0], v = uv[1], mag = uv[2];
        // Apparent-speed floor and ceiling. Applied here, once, rather
        // than per particle per frame -- and only to how far a dot
        // moves. The speed raster and the click query are untouched.
        if (mag > 1e-6) {
          var target = Math.min(Math.max(mag, cfg.minSpeed), cfg.maxSpeed);
          if (target !== mag) {
            var k = target / mag;
            u *= k; v *= k;
          }
        }

        // metres/second -> pixels/frame. Mercator shrinks ground
        // distance toward the poles, so a fixed wind covers more pixels
        // there; cos(lat) is that, and it is why this cannot be one
        // constant for the whole canvas.
        var mpp = mppEquator * Math.cos((lat * Math.PI) / 180);
        if (!(mpp > 1e-9)) continue;
        var scale = advance / mpp;
        var i = (gy * gw + gx) * 2;
        f[i] = u * scale;
        // Screen y grows downward while v is northward, hence the sign.
        f[i + 1] = -v * scale;
        ok[gy * gw + gx] = 1;
        any = true;
      }
    }

    st.field = any ? f : null;
    st.fieldOk = ok;
    st.fieldW = gw; st.fieldH = gh; st.fieldSpacing = sp;
    st.fieldKey = viewKey(st);
    return any;
  }

  /** What the field was built for. Changes on pan, zoom or resize. */
  function viewKey(st) {
    var c = global.map && global.map.getCenter();
    return [global.map && global.map.getZoom(),
            c ? c.lat().toFixed(5) : "?", c ? c.lng().toFixed(5) : "?",
            st.w, st.h].join("|");
  }

  /**
   * The wind at a canvas pixel, in pixels/frame, or null.
   *
   * Bilinear across the GRID -- not across the data. The grid is a
   * subsampling this module chose, so interpolating it back is
   * recovering our own coarseness, which is a different thing from
   * interpolating the forecast (Earth Engine already did that, in the
   * tile). Without it the flow visibly facets at the grid spacing.
   */
  function fieldAt(st, x, y) {
    var f = st.field;
    if (!f) return null;
    var sp = st.fieldSpacing, gw = st.fieldW, gh = st.fieldH;
    var fx = x / sp, fy = y / sp;
    var x0 = Math.floor(fx), y0 = Math.floor(fy);
    if (x0 < 0 || y0 < 0 || x0 + 1 >= gw || y0 + 1 >= gh) return null;
    var ok = st.fieldOk;
    var i00 = y0 * gw + x0, i10 = i00 + 1;
    var i01 = i00 + gw, i11 = i01 + 1;
    if (!ok[i00] || !ok[i10] || !ok[i01] || !ok[i11]) return null;
    var rx = 1 - (fx - x0), ry = 1 - (fy - y0);
    var wa = rx * ry, wb = (1 - rx) * ry, wc = rx * (1 - ry),
        wd = (1 - rx) * (1 - ry);
    return [
      f[i00 * 2] * wa + f[i10 * 2] * wb + f[i01 * 2] * wc + f[i11 * 2] * wd,
      f[i00 * 2 + 1] * wa + f[i10 * 2 + 1] * wb +
        f[i01 * 2 + 1] * wc + f[i11 * 2 + 1] * wd,
    ];
  }

  /**
   * Put a particle somewhere in the view, with its own lifetime.
   *
   * Canvas coordinates now, so this is two random numbers rather than
   * an inverse projection.
   *
   * Trail length is how much history is still drawn, so a particle that
   * respawned two frames ago draws a stub and a mature one draws a full
   * streak. With a single shared lifetime almost every particle sits in
   * the mature part of its life at any instant and the field reads as
   * one uniform comb. Drawing each lifetime from a range keeps short,
   * medium and long streaks on screen at once.
   */
  function respawn(st, p, randomAge) {
    var cfg = st.cfg;
    p.x = Math.random() * st.w;
    p.y = Math.random() * st.h;
    p.xs = []; p.ys = [];
    p.maxAge = cfg.minAge + Math.random() * (cfg.maxAge - cfg.minAge);
    // Stagger the initial ages too, or the whole field respawns in
    // lockstep and the map pulses once per lifetime.
    p.age = randomAge ? Math.random() * p.maxAge : 0;
    p.dead = false;
    return p;
  }

  /**
   * How many particles for this canvas.
   *
   * Proportional to canvas WIDTH, after windy.js -- a wider canvas has
   * more room to fill, and that is the whole of it. It used to compound
   * with zoom, which was really compensating for streak length growing
   * with zoom; now that length is held constant on screen, density
   * should be too, and the zoom term was doing nothing but thinning the
   * field exactly where it was already densest.
   *
   * ``particleCount``, if given, wins outright.
   */
  function countFor(cfg, width) {
    var n = cfg.count !== null ? cfg.count : Math.round(width * cfg.density);
    return Math.max(cfg.minCount, Math.min(cfg.maxCount, n));
  }

  function seed(st) {
    var n = countFor(st.cfg, st.w);
    st.count = n;
    var ps = new Array(n);
    for (var i = 0; i < n; i++) ps[i] = respawn(st, {}, true);
    st.particles = ps;
  }

  function frame(st) {
    if (!st.ctx || !st.particles || !st.field) return;
    var ctx = st.ctx, cfg = st.cfg, ps = st.particles;
    var n = cfg.trailLength;

    ctx.clearRect(0, 0, st.w, st.h);
    ctx.lineCap = cfg.lineCap;

    // --- advance, recording each new position ------------------------
    //
    // Everything expensive moved into buildField: the projection,
    // cos(lat), the zoom normalisation, the speed clamp and the tile
    // lookup all happen once per grid cell when the view settles. What
    // is left per particle per frame is one grid read and two adds.
    for (var i = 0; i < ps.length; i++) {
      var p = ps[i];
      if (p.dead) { respawn(st, p, false); continue; }

      // Off the canvas draws nothing, so recycle it into the view. The
      // margin lets a trail that is entering already be grown.
      if (p.x < -CULL_MARGIN || p.x > st.w + CULL_MARGIN ||
          p.y < -CULL_MARGIN || p.y > st.h + CULL_MARGIN) {
        p.dead = true;
        continue;
      }

      var d = fieldAt(st, p.x, p.y);
      // A gap in the grid, or its edge. Age the particle out rather
      // than freezing it in place.
      if (!d) { p.age += 1; if (p.age > p.maxAge) p.dead = true; continue; }

      p.x += d[0];
      p.y += d[1];
      p.xs.push(p.x); p.ys.push(p.y);
      if (p.xs.length > n) { p.xs.shift(); p.ys.shift(); }

      p.age += 1;
      if (p.age > p.maxAge) p.dead = true;
    }

    // --- stroke by rank: rank 0 is the oldest, faintest ---------------
    var r = cfg.rgb[0], g = cfg.rgb[1], bl = cfg.rgb[2];
    for (var rank = 1; rank < n; rank++) {
      // Ranks are drawn oldest-first so the bright head lands on top.
      // ``taper`` above 1 pushes the fade toward the tail, which is what
      // makes the shape read as a comet rather than a wedge.
      var t = rank / (n - 1);
      var alpha = cfg.opacity * Math.pow(t, cfg.taper);
      // Width ramps minSize -> maxSize across the trail, so the head
      // needs no special case: at t = 1 it already IS maxSize. Only the
      // alpha gets a discontinuity, which is what makes the tip read as
      // a highlight rather than merely the widest part.
      var width = cfg.minSize + (cfg.maxSize - cfg.minSize) * t;
      if (rank === n - 1) alpha = Math.min(1, cfg.opacity * cfg.headBoost);
      ctx.strokeStyle = "rgba(" + r + "," + g + "," + bl + "," + alpha + ")";
      ctx.lineWidth = width;
      ctx.beginPath();
      for (var j = 0; j < ps.length; j++) {
        var pp = ps[j];
        var len = pp.xs ? pp.xs.length : 0;
        if (len <= rank) continue;
        // Index from the END so a partially grown trail still draws its
        // newest segment as the head.
        var e = len - 1 - (n - 1 - rank);
        if (e < 1) continue;
        ctx.moveTo(pp.xs[e - 1], pp.ys[e - 1]);
        ctx.lineTo(pp.xs[e], pp.ys[e]);
      }
      ctx.stroke();
    }
  }

  function anyRunning() {
    for (var id in adopted) if (adopted[id].running) return true;
    return false;
  }

  /** Rebuild the field if the view moved, or if tiles only arrived
   *  after the last attempt. One string compare when nothing changed. */
  function ensureField(st) {
    if (st.field && st.fieldKey === viewKey(st)) return true;
    return buildField(st);
  }

  function tick() {
    rafId = null;
    for (var id in adopted) {
      var st = adopted[id];
      if (!st.running) continue;
      if (!ensureField(st)) continue;   // tiles not in yet; retry next frame
      if (!st.particles) seed(st);
      frame(st);
    }
    if (anyRunning()) rafId = global.requestAnimationFrame(tick);
  }

  function refreshRunState() {
    var reg = registry();
    var pageVisible = !global.document || !global.document.hidden;
    for (var id in adopted) {
      var st = adopted[id];
      var L = reg && reg[id];
      var want = pageVisible && (L ? L.visible !== false : true);
      if (want !== st.running) {
        st.running = want;
        if (!want && st.ctx) st.ctx.clearRect(0, 0, st.w, st.h);
        if (want) st.particles = null;
      }
      if (L && typeof L.opacity === "number") st.cfg.opacity = L.opacity;
      // Re-checking the layer makes the viewer rebuild and re-add the
      // encoded RGB. Undo it here rather than in scan(), which skips
      // anything already adopted. Re-adding also re-flips loading via
      // the viewer's getTileUrl, so the progress report belongs on the
      // same tick.
      if (L) { detach(L); reportProgress(st); }
    }
    if (anyRunning() && rafId === null) rafId = global.requestAnimationFrame(tick);
  }

  function bindOnce() {
    if (bound || !global.map) return;
    // Rebuild on idle -- once when movement STOPS, not during a drag.
    // A pan invalidates the whole field: canvas pixel (0, 0) means a
    // different place on the globe afterwards, so every cached vector is
    // wrong. Zoom and resize likewise.
    global.map.addListener("idle", function () {
      for (var id in adopted) {
        adopted[id].field = null;         // forces a rebuild
        adopted[id].particles = null;     // reseed into the new view
      }
      refreshRunState();
    });
    if (global.document) {
      global.document.addEventListener("visibilitychange", refreshRunState);
    }
    global.setInterval(refreshRunState, 500);
    bound = true;
  }

  /**
   * Every knob that governs how the particles look and move.
   *
   * Grouped as COUNT, SIZE, SHAPE, SPEED, LIFETIME, COLOR. Defaults are
   * the windy.com-alike look; each is overridable per layer through the
   * viz dict, and geeViz stamps all of them from Python so a hand-built
   * layer and a `Map.addWindLayer` layer behave identically.
   */
  function cfgFrom(viz) {
    var v = viz || {};

    // Widths derive from one base weight, so raising the weight scales
    // the whole taper rather than only its midpoint. Explicit min/max
    // win when given -- same pattern as minAge tracking maxAge.
    var weight = v.particleStrokeWeight !== undefined
      ? v.particleStrokeWeight
      : (v.particleLineWidth !== undefined ? v.particleLineWidth : 1.1);

    var maxAge = v.particleMaxAge || 90;

    return {
      // ---- count ---------------------------------------------------
      // Proportional to canvas WIDTH, after windy.js: a wider canvas has
      // more room to fill, and that is the whole of it. ~3000 particles
      // on a 1700 px canvas at the default density. particleCount, if
      // given, overrides it outright.
      count: v.particleCount !== undefined && v.particleCount !== null
        ? v.particleCount : null,
      density: v.particleDensity !== undefined ? v.particleDensity : 1.75,
      minCount: v.particleMinCount || 400,
      maxCount: v.particleMaxCount || 20000,
      // The zoom at which streak length is calibrated. Every other zoom
      // is scaled to match, so a streak is the same size on screen
      // however far in you are.
      zoomRef: v.particleZoomRef !== undefined ? v.particleZoomRef : 7,
      // Grid spacing of the prebuilt field, in canvas pixels. Smaller
      // resolves more detail and costs more to build -- the build is
      // (w/spacing) x (h/spacing) samples, so halving it quadruples the
      // work. 8 px on a 1700x1200 canvas is about 32,000 cells.
      fieldSpacing: Math.max(2, v.particleFieldSpacing || 8),

      // ---- size ----------------------------------------------------
      // strokeWeight is the base; minSize and maxSize are the ABSOLUTE
      // pixel widths at the tail and at the head, and the taper ramps
      // between them. A comet is thin at the tail and fat at the tip,
      // so maxSize > minSize; equal values give a constant-width ribbon.
      strokeWeight: weight,
      minSize: v.particleMinSize !== undefined
        ? v.particleMinSize : weight * 0.45,
      maxSize: v.particleMaxSize !== undefined
        ? v.particleMaxSize : weight * 1.5,

      // ---- sampling ------------------------------------------------
      // Ceiling on the zoom of the u/v tiles fetched. Not a rendering
      // knob -- it bounds how much is downloaded, and the forecast
      // grids are far coarser than any tile this fine.
      maxTileZoom: v.particleMaxTileZoom !== undefined
        ? v.particleMaxTileZoom : 10,

      // ---- shape ---------------------------------------------------
      // How many frames of history each trail draws. This, times the
      // per-frame step, IS the streak length -- an explicit number now,
      // where it used to be an emergent property of a fade constant.
      trailLength: Math.max(2, v.particleTrailLength || 26),
      // Exponent on the tail fade. 1 is a linear wedge; above 1 the
      // faint part stretches out and the shape reads as a comet.
      taper: v.particleTaper !== undefined ? v.particleTaper : 2.1,
      // The leading segment's alpha multiplier -- the bright tip.
      headBoost: v.particleHeadBoost !== undefined ? v.particleHeadBoost : 1.6,
      // "round" gives tapered tips; "butt" gives blunt ones.
      lineCap: v.particleLineCap || "round",

      // ---- speed ---------------------------------------------------
      // Seconds of advection per frame. Streak length is proportional
      // to it, so it sets both how fast the field moves and how long
      // the streaks are.
      speedFactor: v.particleSpeedFactor || 380,
      // Apparent-speed FLOOR and CEILING, m/s, applied to the advection
      // only. Length is proportional to speed, so without a floor a
      // light breeze draws a dot and a calm map reads as a broken one;
      // without a ceiling a cyclone core smears clear across the
      // screen. Direction is preserved either way, and the speed raster
      // and the click query still report the true value.
      minSpeed: v.particleMinSpeed !== undefined ? v.particleMinSpeed : 3.0,
      maxSpeed: v.particleMaxSpeed !== undefined ? v.particleMaxSpeed : 45.0,

      // ---- lifetime ------------------------------------------------
      maxAge: maxAge,
      // A quarter of the maximum by default, so the shortest streaks
      // are visibly stubs against the longest. Set them equal to get a
      // uniform comb.
      minAge: v.particleMinAge !== undefined ? v.particleMinAge : maxAge * 0.25,

      // ---- color ---------------------------------------------------
      opacity: v.particleOpacity !== undefined ? v.particleOpacity : 0.9,
      rgb: hexToRgb(v.particleColor || "#fff"),

      // Sent by geeViz.weather.addWindLayer. Reading them rather than
      // trusting a second copy is what keeps encoder and decoder in
      // lockstep: a mismatch would not throw, it would yield winds wrong
      // by a scale and offset, which still look like weather.
      tileMin: v.windTileMin !== undefined ? v.windTileMin : TILE_MIN,
      tileMax: v.windTileMax !== undefined ? v.windTileMax : TILE_MAX,
    };
  }

  function scan() {
    var reg = registry();
    if (!reg || !global.map) return;
    for (var id in reg) {
      if (adopted[id]) continue;
      var L = reg[id];
      if (!L || !L.viz || !L.viz.windParticles) continue;
      // Needs the ImageMapType the viewer built; that is where the tile
      // URL lives.
      if (!L.layer) continue;
      var getUrl = findTileUrlFn(L.layer);
      if (!getUrl) continue;                 // tiles not minted yet
      detach(L);

      var st = {
        id: id, getTileUrl: getUrl, cfg: cfgFrom(L.viz),
        tiles: Object.create(null), tileZoom: 4,
        field: null, fieldOk: null, fieldW: 0, fieldH: 0,
        fieldSpacing: 8, fieldKey: null,
        canvas: null, ctx: null, particles: null, running: false,
        inflight: 0, burst: 0,
        origin: { x: 0, y: 0 }, proj: null, w: 0, h: 0, warned: false,
      };
      st.overlay = makeOverlay(st);
      st.overlay.setMap(global.map);
      adopted[id] = st;
      // findTileUrlFn probes the viewer's own getTileUrl, which flips
      // layer.loading = true as a side effect. Settle it now: if this
      // layer never requests a tile (it is switched off, say) nothing
      // else would, and the spinner would spin on an idle layer.
      reportProgress(st);
      bindOnce();
      refreshRunState();
    }
  }

  if (typeof setInterval === "function") setInterval(scan, 600);

  /** Advance N frames synchronously. Testing seam: rAF is throttled to a
   *  standstill in a tab that is not foreground, so an automated check of
   *  the rendering cannot rely on the animation loop running at all. */
  function step(id, n) {
    var st = adopted[id];
    if (!st) return null;
    ensureField(st);
    if (!st.particles) seed(st);
    for (var i = 0; i < (n || 1); i++) frame(st);
    var alive = 0;
    for (var j = 0; j < st.particles.length; j++) if (!st.particles[j].dead) alive++;
    return { particles: st.particles.length, alive: alive,
             tilesCached: Object.keys(st.tiles).length };
  }

  global.geeVizWindParticles = {
    scan: scan,
    step: step,
    status: function (id) {
      var st = adopted[id];
      if (!st) return null;
      var ok = 0, pending = 0, bad = 0;
      for (var k in st.tiles) {
        if (st.tiles[k] === null) pending++;
        else if (st.tiles[k] === false) bad++;
        else ok++;
      }
      return { id: id, running: st.running, tileZoom: st.tileZoom,
               baseCount: st.cfg.count,
               countFor: countFor(st.cfg, st.w),
               fieldCells: st.field ? st.fieldW * st.fieldH : 0,
               particles: st.particles ? st.particles.length : 0,
               tiles: { ok: ok, pending: pending, failed: bad } };
    },
    _countFor: countFor,
    _fieldAt: fieldAt,
    _buildField: buildField,
    _viewKey: viewKey,
    _sampleUV: sampleUV,
    _lonToTileX: lonToTileX,
    _latToTileY: latToTileY,
    _hexToRgb: hexToRgb,
    _range: [TILE_MIN, TILE_MAX],
  };
})(typeof window !== "undefined" ? window : this);
