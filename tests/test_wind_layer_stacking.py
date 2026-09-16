"""The particle layer must not disturb any other layer's overlay slot.

``map.overlayMapTypes`` is positional and the whole viewer leans on
that: a layer owns the fixed index in ``layer.layerId``, shows itself
with ``setAt(layerId, layer)`` and hides itself with
``setAt(layerId, null)``. ``updateMapLayerOrder`` reassigns the ids and
re-sets every layer at its new slot.

``removeAt`` breaks that contract for everyone else in the array. The
particle module used it to take its encoded u/v raster off the map, and
the damage is one slot per detach: with the particle layer at index 1,
detaching shifted the layer above it down to 1 while its ``layerId``
stayed 2, so unchecking and re-checking that layer left TWO copies of
its tiles on the map -- one at the slot its checkbox addresses and an
orphan at the shifted slot, which nothing could then turn off.

Run through node against the real source, so this tests the shipped
file rather than a description of it.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "geeViz" / "geeView" / "src" / "js" / "wind-particles.js"
PROBE = Path(__file__).with_name("wind_stack_probe.js")


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


def test_detach_leaves_the_array_length_alone(result):
    """Length is the tell. Every layerId above the particle layer is
    wrong the moment the array gets shorter."""
    assert result["length"] == 3, (
        f"overlayMapTypes went from 3 slots to {result['length']} — every "
        f"layerId above the particle layer now addresses the wrong tiles")
    assert result["afterDetach"] == ["SPEED_TILES", None, "TERRAIN_TILES"], (
        f"detach moved another layer: {result['afterDetach']}")


def test_a_neighbour_survives_being_toggled_off_and_on(result):
    """The reported symptom, replayed with the viewer's own turnOff and
    turnOn. With removeAt this produced TERRAIN_TILES twice — a ghost
    the checkbox could no longer reach."""
    got = result["terrainRoundTrip"]
    assert got.count("TERRAIN_TILES") == 1, (
        f"a layer ended up on the map twice after one off/on cycle: {got}")
    assert got == ["SPEED_TILES", None, "TERRAIN_TILES"], got


def test_reordering_still_lands_every_layer_on_its_own_slot(result):
    """updateMapLayerOrder reassigns layerId then re-sets each layer.
    That only works if the array still means what those ids say."""
    ids, arr = result["layerIds"], result["afterReorder"]
    assert arr[ids["terrain"]] == "TERRAIN_TILES", (ids, arr)
    assert arr[ids["speed"]] == "SPEED_TILES", (ids, arr)
    assert arr[ids["particles"]] is None, (
        "the encoded u/v raster is back on the map — left visible it "
        "paints the world flat red and green")


def test_the_source_uses_the_viewer_s_own_call(result):
    """Guard the guard, on the shipped file.

    The probe only exercises detach. A future edit could reintroduce a
    removeAt somewhere else in the module and still pass everything
    above, so the file itself is checked for the call that is never
    correct on a layer slot.
    """
    code = "\n".join(
        ln for ln in SRC.read_text(encoding="utf-8").splitlines()
        if not ln.strip().startswith(("//", "*", "/*")))
    assert "removeAt" not in code, (
        "wind-particles.js calls overlayMapTypes.removeAt — that shifts "
        "every higher slot and corrupts other layers' layerId")
    assert "setAt(L.layerId, null)" in code, (
        "detach no longer hides the encoded raster the way the viewer does")
