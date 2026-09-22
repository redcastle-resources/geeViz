"""A time lapse must be switchable off while it is still loading.

A lapse adds one map layer per frame, and a two-day forecast is a lot of
frames. Until the last one arrives the viewer hides the layer's toggle:

    <label id="{id}-toggle-checkbox-label" style="display:none;">

and because ``input[type="checkbox"] {display:none}`` in the stylesheet
makes the label the control -- its ``:before`` draws the circle --
hiding it does not grey the toggle out, it removes it. So the one moment
a user is most likely to change their mind about a slow layer is the one
moment they cannot, and the layer reads as locked.

The control was hidden for a reason, though, and that reason still
holds: ``timeLapseCheckbox`` starts *playing* the lapse, and playing one
whose frames do not exist yet is not an improvement on a locked toggle.
So the click is recorded and applied on load-complete instead, which is
what most of this file is about.

The third state is the one that breaks things quietly. "Never touched"
is not "chose off": the viewer's own load-complete branches turn a lapse
on from URL state, and a reconciler that conflates the two switches
those off and silently breaks every saved view that had a lapse in it.

``timelapse-toggle.js`` is standalone on purpose. ``lcms-viewer.min.js``
is built from the lcms-viewer repo and shared with LCMS, so a fix living
in there is one a rebuild can revert without anyone noticing.

Driven through node against the real source, so this exercises the
shipped file rather than a description of it.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "geeViz" / "geeView" / "src" / "js" / "timelapse-toggle.js"
INDEX = ROOT / "geeViz" / "geeView" / "index.html"
PROBE = Path(__file__).with_name("timelapse_toggle_probe.js")


def _node():
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node not available")
    return exe


@pytest.fixture(scope="module")
def result():
    out = subprocess.run([_node(), str(PROBE), str(SRC)],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ── the control exists at all ──────────────────────────────────────────


def test_the_toggle_appears_while_the_frames_are_still_loading(result):
    """The reported symptom, in one assertion."""
    assert result["hiddenBeforeScan"], (
        "the probe did not reproduce the viewer's inline display:none, so "
        "the rest of this file is testing nothing")
    assert result["shownWhileLoading"], "the toggle is still hidden mid-load"


def test_revealing_it_leaves_the_stylesheet_in_charge(result):
    """Clearing the inline ``display`` is what the viewer's own
    ``$(...).show()`` does. Hard-coding ``block`` or ``inline`` here
    would override whatever the stylesheet has for that label and show
    up as a toggle that is the right state and the wrong shape."""
    assert result["stylesheetDecides"]


# ── a click mid-load records; it does not play ─────────────────────────


def test_a_click_mid_load_does_not_start_the_lapse(result):
    """Why the control was hidden in the first place. Showing it without
    disarming it trades a locked toggle for a broken one: the lapse
    starts animating over frames that have not arrived."""
    assert result["midLoadPlayed"] == 0, (
        "timeLapseCheckbox ran on a lapse that is not ready")
    assert result["midLoadVisible"] is False


def test_the_click_is_recorded_and_drawn(result):
    """Recorded, so load-complete can honor it -- and drawn, because a
    control that does not move when clicked reads as broken whatever it
    is doing internally."""
    assert result["midLoadIntent"] is True
    assert result["midLoadBoxChecked"] is True
    assert "loading" in (result["midLoadTitle"] or "").lower(), (
        f"the tooltip should say what will happen, got "
        f"{result['midLoadTitle']!r}")


def test_clicking_back_off_mid_load_tracks(result):
    """Two clicks is off, and still nothing has played."""
    assert result["midLoadIntent2"] is False
    assert result["midLoadBoxChecked2"] is False
    assert result["midLoadPlayed2"] == 0


def test_the_layer_name_toggles_the_same_way_as_the_checkbox(result):
    """The name span is a second toggle and it never touches the
    checkbox. Deriving the new state from the checkbox instead of from
    the recorded choice reads a stale value on this path and flips the
    wrong way -- while looking right on the other one."""
    assert result["nameIntent"] is True
    assert result["nameBoxChecked"] is True, (
        "the drawn circle did not follow a name-span toggle")
    assert result["namePlayed"] == 0


# ── and is honored when the frames land ────────────────────────────────


def test_the_choice_is_applied_once_loading_finishes(result):
    """A toggle that responds and then quietly forgets is worse than one
    that never moved."""
    assert result["readyApplied"] == 1
    assert result["readyVisible"] is True


def test_it_is_applied_exactly_once(result):
    """The scan is a poll. Reconciling on every tick would toggle the
    lapse straight back off one tick later."""
    assert result["readyAppliedTwice"] == 1
    assert result["readyVisibleAfter"] is True


def test_the_tooltip_goes_back_to_the_normal_one(result):
    assert result["readyTitle"] == "Activate/deactivate time lapse"


def test_turning_it_off_mid_load_beats_the_viewers_url_state(result):
    """The reported bug end to end: a slow lapse the user decided
    against, which the viewer switches on anyway the moment it
    finishes."""
    assert result["urlStateTurnedItOn"] is True, (
        "the probe did not reproduce the viewer turning it on from URL "
        "state, so the assertion below proves nothing")
    assert result["offBeatsUrlState"] is True


# ── and a lapse nobody touched is left exactly alone ───────────────────


def test_an_untouched_lapse_keeps_the_viewers_own_behavior(result):
    """"Never touched" is a third state, distinct from "chose off". Lose
    that distinction and every saved view with a visible lapse in it
    comes back switched off."""
    assert result["untouchedVerdict"] == "untouched"
    assert result["untouchedStillVisible"] is True
    assert result["untouchedNoExtraCall"] is True


def test_a_lapse_already_loaded_when_first_seen_is_not_touched(result):
    """Nothing could have been recorded for it, so there is nothing to
    apply -- and applying anything would be acting on a choice the user
    never made."""
    assert result["alreadyReadyUntouched"] is True
    assert result["alreadyReadyNotPending"] is True


def test_once_ready_toggling_is_the_viewers_own_function_again(result):
    """The wrapper is a load-time guard, not a permanent replacement."""
    assert result["delegatesWhenReady"] is True


# ── wiring ─────────────────────────────────────────────────────────────


def test_the_file_is_loaded_by_the_viewer_page():
    """A standalone module nothing includes is dead code that tests
    green."""
    html = INDEX.read_text(encoding="utf-8")
    assert "timelapse-toggle.js" in html, (
        "timelapse-toggle.js is not referenced by index.html")


def test_it_is_cache_busted_with_the_package_version():
    """Browsers hold the old copy otherwise, and a viewer JS fix that
    does not reach anyone is not a fix. Same ``?v=`` every other asset
    on the page carries."""
    import geeViz
    html = INDEX.read_text(encoding="utf-8")
    assert f"timelapse-toggle.js?v={geeViz.__version__}" in html, (
        f"expected timelapse-toggle.js?v={geeViz.__version__} in index.html")


def test_it_stays_out_of_the_shared_viewer_bundle():
    """``lcms-viewer.min.js`` is built from the lcms-viewer repo and
    shared with LCMS. A fix that lives in there is a fix the next
    rebuild can revert silently, which is exactly how this one was
    parked the first time."""
    bundle = ROOT / "geeViz" / "geeView" / "src" / "js" / "lcms-viewer.min.js"
    if not bundle.exists():
        pytest.skip("built viewer bundle not present")
    assert "geeVizTimeLapseToggle" not in bundle.read_text(
        encoding="utf-8", errors="replace"), (
        "the toggle fix leaked into the shared viewer bundle")
