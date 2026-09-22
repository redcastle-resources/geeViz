/**
 * Let a time lapse be switched off while it is still loading.
 *
 * A time lapse adds one map layer per frame, and a two-day forecast is
 * a lot of frames. Until the last of them arrives the viewer hides the
 * layer's toggle outright:
 *
 *     <label id="${id}-toggle-checkbox-label" style="display:none;">
 *
 * and `input[type="checkbox"] {display:none}` in the stylesheet means
 * the label IS the control -- its `:before` draws the circle. Hiding it
 * does not grey the toggle out, it removes it. So the one moment a user
 * is most likely to change their mind about a slow layer is the one
 * moment they cannot, and the layer reads as locked.
 *
 * The toggle is shown from the start instead, and a click during
 * loading is recorded rather than acted on. When the frames finish, the
 * recorded choice is applied.
 *
 * ---------------------------------------------------------------------
 * WHY NOT THE VIEWER'S OWN HOOK
 * ---------------------------------------------------------------------
 * `2templates.js` already reads a `userChosenVisible` flag on
 * load-complete and clicks the label if it is true -- but nothing has
 * ever written it, and writing it now would not work: that branch
 * clicks BEFORE it sets `isReady`, so the click would arrive back here
 * while the lapse still looks unloaded and be recorded as another
 * change of mind instead of being performed.
 *
 * It is also only one of the two load-complete paths. The other
 * (`geeAltService`) reads `urlParams.layerProps[id].visible` and calls
 * `timeLapseCheckbox` directly. Which one runs depends on the tile
 * service format. Reconciling here, off `isReady`, behaves the same on
 * both and leaves the existing URL-state behavior untouched -- an
 * untouched toggle records no intent, so nothing about a lapse the user
 * never clicked changes at all.
 *
 * ---------------------------------------------------------------------
 * SEPARATE FILE, DELIBERATELY
 * ---------------------------------------------------------------------
 * Same reasoning as wind-particles.js next door: `lcms-viewer.min.js`
 * is built from the lcms-viewer repo and shared with LCMS, so a fix
 * living in there is a fix a rebuild can silently revert. This attaches
 * from outside and survives the build.
 */
(function (global) {
  "use strict";

  // The viewer builds its layer list from GEE callbacks, so there is no
  // event to hang this on. Polling is what wind-particles.js does for
  // the same reason. 300ms is comfortably below the delay a click feels
  // laggy at, and the body does nothing when no lapse is loading.
  var SCAN_MS = 300;

  // Our own property, NOT the viewer's dormant `userChosenVisible` --
  // see the note above. `undefined` means "never touched", which is a
  // third state and has to stay distinguishable from "chose off".
  var INTENT = "geeVizWantVisible";

  var TITLE_QUEUED = "Turn on when the frames finish loading";
  var TITLE_SKIP = "Stay off when the frames finish loading";
  var TITLE_READY = "Activate/deactivate time lapse";

  /**
   * The viewer's time lapse table.
   *
   * `timeLapseObj` is assigned without a declaration keyword, so unlike
   * `layerObj` and `queryObj` it really is a window property. Read it
   * lexically first anyway: that is the form that keeps working if the
   * viewer ever tightens the declaration, and the fallback costs
   * nothing.
   */
  function lapses() {
    try {
      if (typeof timeLapseObj !== "undefined" && timeLapseObj) {
        return timeLapseObj;
      }
    } catch (e) { /* declared later */ }
    return global.timeLapseObj || null;
  }

  function byId(id) {
    var d = global.document;
    return d && d.getElementById ? d.getElementById(id) : null;
  }

  /** Ids we have seen mid-load, so the choice is applied exactly once. */
  var pending = Object.create(null);

  /**
   * Reveal the toggle.
   *
   * Only the inline `display:none` is cleared -- the stylesheet decides
   * what the label actually is, which is what the viewer's own
   * `$(...).show()` does when it finally unhides it.
   */
  function showToggle(id) {
    var el = byId(id + "-toggle-checkbox-label");
    if (el && el.style && el.style.display === "none") el.style.display = "";
    return !!el;
  }

  /**
   * Put the drawn circle where the recorded choice is.
   *
   * Assigning `.checked` does not fire `change`, so this cannot loop
   * back through the wrapper below.
   */
  function syncBox(id, want) {
    var cb = byId(id + "-toggle-checkbox");
    if (cb) cb.checked = !!want;
    var el = byId(id + "-toggle-checkbox-label");
    if (el && el.setAttribute) {
      el.setAttribute("title", want ? TITLE_QUEUED : TITLE_SKIP);
    }
  }

  var wrapped = false;

  /**
   * Make `timeLapseCheckbox` safe to call on a half-loaded lapse.
   *
   * Both ways of toggling reach it: the checkbox's inline `onchange`
   * and the click handler on the layer's name span. It is a top-level
   * function declaration, so the global binding and the window property
   * are the same slot and replacing it catches both call sites.
   *
   * Running the real thing here would start playing a lapse most of
   * whose frames do not exist yet, which is why the control was hidden
   * in the first place. Record instead.
   */
  function wrap() {
    if (wrapped) return true;
    var orig = global.timeLapseCheckbox;
    if (typeof orig !== "function") return false;

    global.timeLapseCheckbox = function (id) {
      var T = lapses();
      var t = T && T[id];
      if (t && t.isReady !== true) {
        // Derived from the RECORDED choice, not from the checkbox: the
        // name-span path never touches the checkbox, so reading it
        // there would flip against a stale value. syncBox then puts the
        // circle back in agreement either way.
        var want = t[INTENT] !== true;
        t[INTENT] = want;
        pending[id] = true;
        syncBox(id, want);
        return;
      }
      return orig.apply(this, arguments);
    };
    global.timeLapseCheckbox._geeVizOriginal = orig;
    wrapped = true;
    return true;
  }

  /**
   * Apply a choice made during loading, now that loading is done.
   *
   * The viewer's own load-complete branch may already have turned the
   * lapse on from URL state; it runs the moment `isReady` flips and we
   * get here at most one tick later, so `t.visible` is current by then
   * and a lapse already in the wanted state is left alone.
   */
  function reconcile(id, t) {
    var want = t[INTENT];
    var el = byId(id + "-toggle-checkbox-label");
    if (el && el.setAttribute) el.setAttribute("title", TITLE_READY);
    if (want === undefined) return "untouched";
    if (!!t.visible === !!want) {
      syncBox(id, !!t.visible);
      return "already";
    }
    var fn = global.timeLapseCheckbox &&
             global.timeLapseCheckbox._geeVizOriginal;
    if (typeof fn !== "function") return "no-original";
    fn(id);
    return "applied";
  }

  function scan() {
    wrap();
    var T = lapses();
    if (!T) return;
    for (var id in T) {
      var t = T[id];
      if (!t) continue;
      if (t.isReady !== true) {
        showToggle(id);
        pending[id] = pending[id] || false;
        continue;
      }
      // A lapse that was already loaded the first time we saw it was
      // never togglable-while-loading and has nothing to reconcile.
      if (!(id in pending)) continue;
      delete pending[id];
      reconcile(id, t);
    }
  }

  if (typeof setInterval === "function") setInterval(scan, SCAN_MS);

  global.geeVizTimeLapseToggle = {
    // Testing seams. What matters here is BEHAVIOR against the viewer's
    // actual data shapes -- that a click mid-load does not start a
    // lapse, that it is still honored afterwards, and that a lapse
    // nobody touched is left exactly as it was. Source text cannot show
    // any of that.
    _scan: scan,
    _wrap: wrap,
    _reconcile: reconcile,
    _showToggle: showToggle,
    _syncBox: syncBox,
    _pending: pending,
    _intentKey: INTENT,
    _scanMs: SCAN_MS,
  };
})(typeof window !== "undefined" ? window : this);
