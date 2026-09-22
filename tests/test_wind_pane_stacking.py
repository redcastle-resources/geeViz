"""The wind canvases must live in the pane the tile layers live in.

``map.overlayMapTypes`` -- every geeViz raster layer, and the satellite
**Labels** overlay -- render as containers inside the ``mapPane`` pane,
stacked with small z-indexes matching their array index. The
``OverlayView`` panes sit above all of that. Measured in a browser:

    mapPane      100   <- every tile layer, and the labels overlay
    overlayLayer 101   <- where the wind canvases used to go
    overlayShadow 102, markerLayer 103, ... and up

The labels overlay is the case that made this visible.
``addLabelOverlay`` parks it at ``Object.keys(layerObj).length`` -- one
past the last layer -- specifically so it is always the top overlay and
place names stay readable over the data. With the canvases in
``overlayLayer`` that was unachievable: a canvas in a higher pane is
above every tile layer whatever z-index it carries, because z-index only
orders siblings *within one stacking context*, and these were never
siblings.

Which also made ``applyStacking`` a no-op in practice. It carefully
tracks ``layerId`` through reorders so the particles sit at their
layer's place in the stack -- and all that number could actually do was
order the two wind canvases against each other.

The second half of this file is the second opacity slider's track. The
viewer repaints its own track's alpha as you drag it
(``setRangeSliderThumbOpacity``), so a copy that does not is visibly the
odd one out -- and on a wind layer the two sit one directly above the
other, which is the worst possible place to differ.

Driven through node against the real source: which pane an element was
appended to is a fact about behavior, and nothing in the source text
says it.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "geeViz" / "geeView" / "src" / "js" / "wind-particles.js"
PROBE = Path(__file__).with_name("wind_pane_probe.js")


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


# ── the pane ───────────────────────────────────────────────────────────


def test_both_canvases_go_in_the_tile_layers_pane(result):
    """The fix, in one assertion. ``overlayLayer`` is above every tile
    layer; ``mapPane`` is where they are."""
    assert result["adopted"]
    assert result["particlePane"] == "mapPane", (
        f"the particle canvas went to {result['particlePane']!r} -- nothing "
        f"in a pane above mapPane can be drawn under a tile layer")
    assert result["speedPane"] == "mapPane"


def test_no_other_pane_is_touched(result):
    """A canvas left behind in overlayLayer is one that still floats
    above the labels."""
    assert result["panesUsed"] == ["mapPane"], (
        f"panes used: {result['panesUsed']}")


def test_the_raster_is_appended_under_the_trails(result):
    """The two share one z-index, so DOM order decides, and the trails
    are painted over the field rather than under it."""
    assert result["speedBeforeParticles"] is True


# ── the z-index that now means something ───────────────────────────────


def test_the_canvas_carries_its_layers_stack_position(result):
    assert result["particleZ"] == "0"
    assert result["speedZ"] == "0", (
        "the two canvases must share a z-index; DOM order separates them")


def test_reordering_the_layer_moves_the_canvas(result):
    """``updateMapLayerOrder`` reassigns every ``layerId``. A z-index
    written once at adoption keeps the order the list had when the layer
    was created."""
    assert result["zAfterReorder"] == "3", (
        "dragging the layer did not move its canvas in the stack")


# ── the slider track ───────────────────────────────────────────────────


def test_the_track_color_is_taken_from_the_host(result):
    """Follows the tenant theme rather than a hard-coded color."""
    assert result["rgbOfTrack"]["fromRgba"] == "55,46,44"
    assert result["rgbOfTrack"]["fromRgb"] == "1,2,3"
    assert result["rgbOfTrack"]["fromSpaces"] == "10,20,30"


@pytest.mark.parametrize("case", ["fromEmpty", "fromNamed"])
def test_an_unreadable_host_color_falls_back_rather_than_blanking(
        result, case):
    """No background parses to no background, which renders as jQuery
    UI's default grey directly beneath a painted twin."""
    assert result["rgbOfTrack"][case] == "55,46,44"


def test_the_slider_is_built_at_the_particles_opacity(result):
    assert result["sliderBuilt"] is True
    assert result["sliderStartsAtParticleDim"] == 0.8


def test_the_track_starts_at_the_particles_alpha_not_the_hosts(result):
    """The host is the SPEED raster's control and the probe paints it at
    0.3, the way ``windSpeedOpacity`` would. Copying its alpha as well
    as its color would show the particle slider at the raster's
    opacity."""
    assert result["trackAtCreate"] == "rgba(55,46,44,0.8)", (
        f"got {result['trackAtCreate']!r} -- the host's alpha leaked in")


def test_the_track_follows_the_handle(result):
    """The reported bug: the viewer fades its own track on drag and this
    one stayed put."""
    assert result["trackAfterDrag"] == "rgba(55,46,44,0.25)"
    assert result["dimAfterDrag"] == 0.25, (
        "the drag stopped reaching the particles")
    assert result["trackAtFull"] == "rgba(55,46,44,1)"
