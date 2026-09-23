"""Dragging a wind layer up the list must move all of it.

A grouped wind layer is TWO canvases -- the colored speed field and the
trails over it -- and only one of them was following the layer list.
``applyStacking(st)`` on the refresh tick restacked ``st.canvas``; the
speed raster was stacked once, in ``onAdd``, and never again. So a drop
split the layer in half: the trails moved to the layer's new depth and
the field stayed at the depth it was created at.

Measured against the module before and after the fix, dragging a wind
layer from position 0 to 3:

                       before            after
    on drop            0 / 0             3 / 3
    after the tick     3 / 0   <--       3 / 3
    encoded RGB        still on map      detached

The second column of that table is the other half.
``updateMapLayerOrder`` -- what the sortable list calls on drop --
re-adds every VISIBLE layer with
``overlayMapTypes.setAt(layerId, layer.layer)``, and for a wind layer
that puts back the encoded u/v RGB this module takes off the map, since
as far as the viewer knows it is an ordinary geeImage that someone
removed behind its back. The refresh tick repairs it, but on a 500 ms
interval, so every drop flashed the raw magenta-green encoding over the
map and left the trails at their old depth for up to half a second.

So ``updateMapLayerOrder`` is wrapped: run the viewer's own function,
then re-detach and restack in the same turn. Nothing is duplicated --
the tick does exactly this, just later, and both operations are
idempotent, which is pinned below.

Patched from this file rather than in ``lcms-viewer.min.js``, for the
same reason as everything else here: that bundle is built from another
repo and a fix inside it is one the next rebuild can revert silently.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "geeViz" / "geeView" / "src" / "js" / "wind-particles.js"
PROBE = Path(__file__).with_name("wind_reorder_probe.js")


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


# ── the reported bug ───────────────────────────────────────────────────


def test_a_drop_moves_both_canvases(result):
    """The whole of it. Before the fix this read particles 3, raster 0 --
    one layer rendering at two different depths."""
    assert result["zAfterDrop"] == {"particle": "3", "speed": "3"}, (
        f"the two halves ended up at different depths: "
        f"{result['zAfterDrop']}")


def test_applystacking_with_no_canvas_named_does_both(result):
    """The underlying defect, isolated from the drag path: the refresh
    tick calls ``applyStacking(st)`` and that has to mean both."""
    assert result["bothRestacked"] == {"particle": "3", "speed": "3"}


def test_the_refresh_tick_agrees_rather_than_correcting(result):
    """If the drop left it wrong and the tick fixed it, the test above
    would still pass while the user saw half a second of the old depth.
    The tick must find nothing to do."""
    assert result["zAfterTick"] == {"particle": "3", "speed": "3"}
    assert result["repairedSynchronously"] is True, (
        "the drop did not repair; the 500 ms tick did")


# ── the wrapper ────────────────────────────────────────────────────────


def test_the_viewers_reorder_still_runs(result):
    """Wrapped, not replaced. Losing the original loses the reorder."""
    assert result["reorderPatched"] is True, (
        "updateMapLayerOrder was never wrapped")
    assert result["origWasCalled"] is True, (
        "the viewer's own reorder did not run, or ran more than once")


def test_the_re_added_encoding_is_taken_back_off(result):
    """``updateMapLayerOrder`` re-adds the raw u/v RGB for every visible
    wind layer. Left on the map it is a magenta-green wash over the
    basemap, which is what the 500 ms gap used to show."""
    assert result["slotAfterDrop"] is True, (
        "the encoded u/v layer is still on the map after the drop")


def test_patching_twice_does_not_double_wrap(result):
    """``scan`` calls the patcher on every tick. A wrapper that wraps
    itself calls the original once per layer of wrapping, and the stack
    grows for as long as the page is open."""
    assert result["patchIsIdempotent"] is True


def test_a_failed_repair_does_not_break_the_reorder(result):
    """The drop has already been applied by the time the repair runs,
    and the refresh tick will catch up regardless -- so an exception
    here must not propagate into the viewer's own handler and leave the
    layer list in a half-sorted state."""
    assert result["reorderSurvivesRepairFailure"] is True


# ── and the pane work it builds on still holds ─────────────────────────


def test_the_canvases_are_still_in_the_tile_layers_pane(result):
    """A z-index is only worth maintaining if it orders against the tile
    layers, which is true only in ``mapPane``."""
    assert result["particlePane"] == "mapPane"
    assert result["speedPane"] == "mapPane"
