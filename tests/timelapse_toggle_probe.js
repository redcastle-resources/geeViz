// Drives the real timelapse-toggle.js against the viewer's data shapes
// and prints one JSON line. Read by test_timelapse_toggle.py.
//
// What source text cannot tell you, and what this is for:
//
// 1. A click mid-load must NOT start the lapse. The viewer hid the
//    control precisely because timeLapseCheckbox -> playTimeLapse on a
//    lapse whose frames do not exist yet is the failure being avoided.
//    Showing the control without disarming it trades a locked toggle
//    for a broken one.
//
// 2. The choice must survive to load-complete. A toggle that responds
//    and then quietly forgets is worse than one that never moved.
//
// 3. A lapse nobody touched must come out EXACTLY as before. The
//    viewer's own load-complete branches turn a lapse on from URL
//    state; a reconciler that cannot tell "chose off" from "never
//    touched" turns those off and silently breaks saved views.
"use strict";

const fs = require("fs");
const vm = require("vm");

const SRC = process.argv[2];

// ---- the two DOM nodes per lapse the module actually touches --------
// Attribute-level fidelity matters in one specific way: the label
// starts with an INLINE display:none (that is how the viewer hides it),
// and clearing it must leave the stylesheet in charge rather than
// hard-coding a display value.
function makeEl(id) {
  return {
    id: id,
    checked: false,
    style: { display: "" },
    attrs: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
  };
}

const DOM = Object.create(null);

function addLapseDom(id) {
  const label = makeEl(id + "-toggle-checkbox-label");
  label.style.display = "none";          // as the viewer renders it
  DOM[label.id] = label;
  DOM[id + "-toggle-checkbox"] = makeEl(id + "-toggle-checkbox");
}

// ---- the viewer's globals -------------------------------------------
let played = [];          // ids the REAL timeLapseCheckbox ran for

const sandbox = {
  console,
  setInterval() { return 0; },          // the probe drives scan() itself
  clearInterval() {},
  document: {
    getElementById(id) { return DOM[id] || null; },
  },
  timeLapseObj: Object.create(null),
  urlParams: { layerProps: Object.create(null) },
  // The real one plays/stops the lapse. Standing in for it lets the
  // probe see whether it was called, which is the whole question.
  timeLapseCheckbox(id) {
    const t = sandbox.timeLapseObj[id];
    played.push(id);
    t.visible = !t.visible;
    sandbox.urlParams.layerProps[id].visible = t.visible;
    const cb = DOM[id + "-toggle-checkbox"];
    if (cb) cb.checked = t.visible;
  },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, { filename: SRC });

const M = sandbox.geeVizTimeLapseToggle;
const out = {};

function addLapse(id, opts) {
  opts = opts || {};
  addLapseDom(id);
  sandbox.timeLapseObj[id] = {
    isReady: false,
    visible: false,
    nFrames: 9,
  };
  sandbox.urlParams.layerProps[id] = { visible: !!opts.urlVisible };
}

// Click the way the browser does: the label toggles the checkbox, THEN
// the inline onchange fires. Going straight to timeLapseCheckbox would
// skip the half that makes the recorded-vs-drawn state disagree.
function clickLabel(id) {
  const cb = DOM[id + "-toggle-checkbox"];
  cb.checked = !cb.checked;
  sandbox.timeLapseCheckbox(id);
}

// The layer name is clickable too, and that path never touches the
// checkbox -- it calls timeLapseCheckbox straight.
function clickName(id) {
  sandbox.timeLapseCheckbox(id);
}

out.wrapped = M._wrap();
out.scanMs = M._scanMs;

// ---- 1. the control appears while the frames are still loading ------
{
  const id = "loading-lapse";
  addLapse(id);
  const label = DOM[id + "-toggle-checkbox-label"];
  out.hiddenBeforeScan = label.style.display === "none";
  M._scan();
  out.shownWhileLoading = label.style.display === "";
  out.stylesheetDecides = label.style.display === "";
}

// ---- 2. a click mid-load records, and does NOT play -----------------
{
  const id = "click-while-loading";
  addLapse(id);
  M._scan();
  played = [];
  clickLabel(id);

  const t = sandbox.timeLapseObj[id];
  out.midLoadPlayed = played.length;                 // must be 0
  out.midLoadIntent = t[M._intentKey];               // true
  out.midLoadVisible = t.visible;                    // still false
  out.midLoadBoxChecked = DOM[id + "-toggle-checkbox"].checked;
  out.midLoadTitle = DOM[id + "-toggle-checkbox-label"].getAttribute("title");

  // ...and again, back to off. The drawn circle has to follow.
  clickLabel(id);
  out.midLoadIntent2 = t[M._intentKey];              // false
  out.midLoadBoxChecked2 = DOM[id + "-toggle-checkbox"].checked;
  out.midLoadPlayed2 = played.length;                // still 0
}

// ---- 3. the name-span path agrees with the checkbox path ------------
// It never touches the checkbox, so a wrapper that derived intent from
// the checkbox would read a stale value here and flip the wrong way.
{
  const id = "name-span";
  addLapse(id);
  M._scan();
  played = [];
  clickName(id);
  const t = sandbox.timeLapseObj[id];
  out.nameIntent = t[M._intentKey];                  // true
  out.nameBoxChecked = DOM[id + "-toggle-checkbox"].checked;   // follows
  out.namePlayed = played.length;                    // 0
}

// ---- 4. the choice is applied once the frames finish ----------------
{
  const id = "honored-on-ready";
  addLapse(id);
  M._scan();
  clickLabel(id);                        // "turn it on when you can"
  played = [];
  sandbox.timeLapseObj[id].isReady = true;
  M._scan();
  const t = sandbox.timeLapseObj[id];
  out.readyApplied = played.length;                  // 1
  out.readyVisible = t.visible;                      // true
  out.readyTitle = DOM[id + "-toggle-checkbox-label"].getAttribute("title");

  // Reconciling twice would toggle it straight back off.
  M._scan();
  out.readyAppliedTwice = played.length;             // still 1
  out.readyVisibleAfter = t.visible;                 // still true
}

// ---- 5. turning it OFF mid-load beats the viewer's URL state --------
// This is the reported bug: a slow lapse the user decided against, that
// the viewer switches on anyway the moment it finishes.
{
  const id = "off-beats-urlstate";
  addLapse(id, { urlVisible: true });
  M._scan();
  clickLabel(id);                        // on
  clickLabel(id);                        // off again -- decided against
  played = [];
  // Load completes: the viewer's own branch turns it on from URL state.
  sandbox.timeLapseObj[id].isReady = true;
  sandbox.timeLapseCheckbox(id);
  out.urlStateTurnedItOn = sandbox.timeLapseObj[id].visible;   // true
  M._scan();
  out.offBeatsUrlState = sandbox.timeLapseObj[id].visible === false;
}

// ---- 6. an untouched lapse is left exactly alone --------------------
{
  const id = "untouched";
  addLapse(id, { urlVisible: true });
  M._scan();
  played = [];
  sandbox.timeLapseObj[id].isReady = true;
  sandbox.timeLapseCheckbox(id);         // the viewer's URL-state branch
  const wasVisible = sandbox.timeLapseObj[id].visible;
  M._scan();
  out.untouchedStillVisible = wasVisible &&
                              sandbox.timeLapseObj[id].visible === true;
  out.untouchedNoExtraCall = played.length === 1;
  out.untouchedVerdict = M._reconcile(id, sandbox.timeLapseObj[id]);
}

// ---- 7. a lapse already loaded when we first see it is not touched --
{
  const id = "already-ready";
  addLapse(id);
  sandbox.timeLapseObj[id].isReady = true;
  sandbox.timeLapseObj[id].visible = true;
  played = [];
  M._scan();
  out.alreadyReadyUntouched = played.length === 0 &&
                              sandbox.timeLapseObj[id].visible === true;
  out.alreadyReadyNotPending = !(id in M._pending);
}

// ---- 8. once ready, toggling is the viewer's own function again -----
{
  const id = "delegates-when-ready";
  addLapse(id);
  sandbox.timeLapseObj[id].isReady = true;
  played = [];
  clickLabel(id);
  out.delegatesWhenReady = played.length === 1 &&
                           sandbox.timeLapseObj[id].visible === true;
}

console.log(JSON.stringify(out, null, 1));
