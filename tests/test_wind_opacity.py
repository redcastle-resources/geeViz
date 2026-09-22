"""``opacity`` on a wind layer must dim the whole wind layer.

A grouped wind layer draws TWO things out of one set of tiles -- the
colored speed field and the flowing trails -- so a single ``opacity``
has two things to reach, and they are set in different places. The
raster rides the viewer's own opacity slider, which is seeded from
``viz["opacity"]``. The particles ride a second slider the viewer has
never heard of, whose starting value nothing was setting.

Both halves were broken, in different ways:

* ``_wind_vizzes`` never put ``opacity`` in either dict, so a caller's
  value was dropped before it left Python and the viewer defaulted both
  components to 1.
* ``particleDim`` in wind-particles.js was hard-coded to 1, so even once
  ``opacity`` did arrive it would have dimmed the speed field and left
  the flow at full.

Either one alone produces "I set opacity and nothing happened", which is
why the fix is pinned from both ends here.

The contract:

===================  ==============================================
``opacity``          master -- where BOTH dimmers start
``windSpeedOpacity`` the speed raster alone, overriding ``opacity``
``particleOpacity``  alpha at the trail HEAD -- a look, not a dimmer
===================  ==============================================

``particleOpacity`` keeping its meaning matters. It is documented as the
head alpha and shapes the comet together with ``particleTaper`` and
``particleHeadBoost``; folding the layer opacity into it would compound
the two and change every existing wind map's appearance.

The JS half runs through node against the real source and reads the
alpha that lands on each canvas element, because that is the only place
the answer actually shows up.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "geeViz" / "geeView" / "src" / "js" / "wind-particles.js"
PROBE = Path(__file__).with_name("wind_opacity_probe.js")


def _node():
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node not available")
    return exe


@pytest.fixture(scope="module")
def painted():
    out = subprocess.run([_node(), str(PROBE), str(SRC)],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def weather():
    return pytest.importorskip("geeViz.weather")


class _Q:
    """Stands in for the speed collection ``_merged_viz`` serializes."""
    def serialize(self):
        return "{}"


def _vizzes(weather, viz):
    speed, particle = weather._wind_vizzes(dict(viz))[:2]
    merged = weather._merged_viz(dict(viz), speed, particle, _Q())
    return speed, particle, merged


# ── Python: the value has to leave Python at all ───────────────────────


def test_opacity_reaches_both_layers(weather):
    """The half that was dropped on the floor."""
    speed, particle, _ = _vizzes(weather, {"opacity": 0.8})
    assert speed["opacity"] == 0.8, "the speed raster never got it"
    assert particle["opacity"] == 0.8, "the particles never got it"


def test_the_default_is_fully_opaque(weather):
    speed, particle, merged = _vizzes(weather, {})
    assert speed["opacity"] == 1
    assert particle["opacity"] == 1
    assert merged["windParticleDim"] == 1


def test_wind_speed_opacity_moves_the_raster_alone(weather):
    """The counterpart to ``particleOpacity``: one knob per thing drawn."""
    speed, particle, merged = _vizzes(
        weather, {"opacity": 0.8, "windSpeedOpacity": 0.3})
    assert speed["opacity"] == 0.3
    assert particle["opacity"] == 0.8, (
        "windSpeedOpacity leaked onto the particles")
    assert merged["opacity"] == 0.3
    assert merged["windParticleDim"] == 0.8


def test_wind_speed_opacity_alone_leaves_the_particles_opaque(weather):
    speed, particle, _ = _vizzes(weather, {"windSpeedOpacity": 0.25})
    assert speed["opacity"] == 0.25
    assert particle["opacity"] == 1


def test_the_grouped_layer_carries_both_numbers(weather):
    """Grouped there is ONE layer and two sliders, so the viz has to name
    them separately -- ``opacity`` is spoken for by the viewer."""
    _, _, merged = _vizzes(weather, {"opacity": 0.6})
    assert merged["opacity"] == 0.6
    assert merged["windParticleDim"] == 0.6


@pytest.mark.parametrize("bad", [80, 100, 1.5, -0.1])
def test_an_out_of_range_opacity_is_refused(weather, bad):
    """0-100 is the other convention people arrive with, and silently
    clamping ``opacity=80`` to 1 looks exactly like the bug this change
    fixes: a value that was set and did nothing."""
    with pytest.raises(ValueError):
        weather._wind_vizzes({"opacity": bad})


def test_the_percentage_mistake_says_so(weather):
    with pytest.raises(ValueError, match="fraction"):
        weather._wind_vizzes({"opacity": 80})


def test_a_non_number_is_refused(weather):
    with pytest.raises(ValueError):
        weather._wind_vizzes({"opacity": "opaque"})


def test_particle_opacity_is_not_touched(weather):
    """It is the head alpha, not a dimmer. Folding the layer opacity into
    it would compound the two and restyle every existing wind map."""
    _, particle, _ = _vizzes(weather, {"opacity": 0.5})
    assert particle["particleOpacity"] == 0.9, (
        "the layer opacity was folded into the trail's head alpha")
    _, particle, _ = _vizzes(weather, {"opacity": 0.5,
                                       "particleOpacity": 0.4})
    assert particle["particleOpacity"] == 0.4


# ── JS: and has to land on the pixels ──────────────────────────────────


def test_both_canvases_are_dimmed(painted):
    """The reported bug, measured where it shows: the alpha on each
    canvas element."""
    g = painted["grouped08"]
    assert g["adopted"]
    assert g["speedCanvasAlpha"] == 0.8, "the speed field was not dimmed"
    assert g["particleCanvasAlpha"] == 0.8, (
        "the flow stayed at full -- this is the half that was hard-coded")


def test_the_default_paints_at_full(painted):
    d = painted["groupedDefault"]
    assert d["speedCanvasAlpha"] == 1
    assert d["particleCanvasAlpha"] == 1


def test_the_two_canvases_can_differ(painted):
    """What ``windSpeedOpacity`` buys, at the far end."""
    s = painted["split"]
    assert s["speedCanvasAlpha"] == 0.3
    assert s["particleCanvasAlpha"] == 0.8


def test_a_hand_built_viz_falls_back_to_opacity(painted):
    """Setting ``windParticles`` directly, without going through
    ``addWindLayer``, means no ``windParticleDim``. Reading 1 there is
    the original bug wearing a different hat."""
    f = painted["fallback"]
    assert f["particleCanvasAlpha"] == 0.4
    assert f["speedCanvasAlpha"] == 0.4


@pytest.mark.parametrize("case,expected", [("clampHigh", 1), ("clampLow", 0)])
def test_the_client_clamps_too(painted, case, expected):
    """Python refuses out-of-range, but the client is reached by
    hand-built vizzes and by URL state that never passed through it. A
    canvas alpha outside [0, 1] is undefined behavior, not a bright
    layer."""
    assert painted[case]["particleCanvasAlpha"] == expected


def test_ungrouped_particles_are_not_dimmed_twice(painted):
    """Ungrouped, the particles are their own layer with their own
    opacity slider. Scaling that by ``particleDim`` as well would render
    0.8 as 0.64 -- the same value applied twice."""
    u = painted["ungrouped"]
    assert u["speedRaster"] is False
    assert u["particleCanvasAlpha"] == 0.8


def test_the_sliders_stay_independent(painted):
    """The starting value is all ``opacity`` sets. Both controls have to
    keep working afterwards, and each must move only its own canvas."""
    a = painted["afterParticleDrag"]
    assert a["particle"] == 0.25
    assert a["speedUnchanged"] == 0.8, "the particle slider moved the raster"
    b = painted["afterSpeedDrag"]
    assert b["speed"] == 0.5
    assert b["particleUnchanged"] == 0.25, (
        "the raster slider moved the particles")


def test_the_trail_stroke_alpha_is_left_alone(painted):
    """``cfg.opacity`` is the SHAPE of the trail's fade. The dimmers ride
    on the canvas element precisely so the configured look survives
    them."""
    assert painted["strokeIsIndependent"] == 0.9
