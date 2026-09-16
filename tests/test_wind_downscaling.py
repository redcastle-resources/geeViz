"""Terrain downscaling: Liston & Elder (2006), as implemented.

The adjustment is bounded by construction -- speed to [0.5, 1.5] of the
input and direction to +/-14.3 degrees -- so a wrong sign or a
transposed term does not blow up. It produces a slightly different,
entirely plausible wind field. That is what these pin.

Hits the live catalogue for the DEM; skips rather than fails offline.
"""
import math

import pytest


def _ee_ready():
    try:
        import ee
        try:
            ee.Number(1).getInfo()
            return True
        except Exception:
            # Imported HERE, not at the top: it is only needed when EE is
            # not already up, and importing it eagerly makes this probe
            # fail for an unrelated reason. test_esriLib installs a stub
            # module at sys.modules["geeViz.geeView"] at IMPORT time, and
            # pytest imports every test module during collection before
            # running any -- so the stub is live while earlier files run,
            # and `from geeViz.geeView import robustInitializer` raises
            # "cannot import name ... (unknown location)". That was read
            # as "Earth Engine not reachable" and skipped eleven passing
            # tests silently in every full run.
            from geeViz.geeView import robustInitializer
            robustInitializer()
            ee.Number(1).getInfo()
            return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _require_ee():
    if not _ee_ready():
        pytest.skip("Earth Engine not reachable")


# Colorado Rockies: real relief, and small enough to reduce quickly.
BOX = [-107.5, 38.5, -105.0, 40.5]


def _region():
    import ee
    return ee.Geometry.Rectangle(BOX)


def _wind():
    """A constant, known wind: 10 m/s from the west (u = +10, v = 0)."""
    import ee
    return ee.Image.constant([10.0, 0.0]).rename(["u", "v"]).toFloat()


def _stats(img, reducer=None, scale=500):
    import ee
    return img.reduceRegion(
        reducer=reducer or ee.Reducer.percentile([2, 50, 98]),
        geometry=_region(), scale=scale, bestEffort=True,
        maxPixels=1e9).getInfo()


def test_flat_terrain_returns_the_wind_unchanged():
    """The convention check, and the one that would otherwise hide.

    Over a perfectly flat DEM slope and curvature are both zero, so W is
    1 and the direction diversion is 0 -- the output must be the input.
    Any sign error in the u/v round trip (the wind direction is the one
    it blows FROM, so the vector points the other way) shows up here as
    a flipped or rotated vector, and NOWHERE else: over real terrain a
    flipped wind is still a plausible-looking wind field.
    """
    import ee
    import geeViz.weather as wx
    flat = ee.Image.constant(1000).setDefaultProjection("EPSG:4326", None, 30)
    out = wx.downscaleWind(_wind(), region=_region(), dem=flat, scale=500)
    d = _stats(out, ee.Reducer.mean())
    assert abs(d["u"] - 10.0) < 0.05, f"u came back {d['u']:.3f}, not 10"
    assert abs(d["v"] - 0.0) < 0.05, f"v came back {d['v']:.3f}, not 0"


def test_terrain_widens_the_distribution():
    """Ridges and windward slopes speed up, valleys and lees slow down,
    so a single coarse value becomes a spread. If the terms cancelled or
    were normalised to nothing, the output would match the input."""
    import ee
    import geeViz.weather as wx
    out = wx.downscaleWind(_wind(), region=_region(), scale=500)
    mag = out.select("u").hypot(out.select("v"))
    d = _stats(mag)
    lo, hi = d["u_p2"], d["u_p98"]
    assert hi - lo > 0.5, (
        f"a constant 10 m/s wind came out spanning only {lo:.2f}..{hi:.2f} "
        f"— the terrain terms are not reaching the result")
    # ...and it stays centred on the input rather than drifting off it.
    assert 8.0 < d["u_p50"] < 12.0, d["u_p50"]


def test_the_speed_adjustment_stays_inside_the_papers_bounds():
    """W is 1 + w_s*omega_s + w_c*omega_c with the omegas clamped to
    +/-0.5 and the weights summing to 1, which bounds the result to half
    and one-and-a-half times the input. That bound is the method's, not
    a safety net -- a downscaler free to double the wind is asserting
    something the forecast never said."""
    import ee
    import geeViz.weather as wx
    out = wx.downscaleWind(_wind(), region=_region(), scale=500)
    mag = out.select("u").hypot(out.select("v"))
    d = _stats(mag, ee.Reducer.minMax())
    assert d["u_min"] >= 10.0 * 0.5 - 0.01, f"min {d['u_min']:.3f} below 0.5x"
    assert d["u_max"] <= 10.0 * 1.5 + 0.01, f"max {d['u_max']:.3f} above 1.5x"


def test_the_direction_diversion_stays_inside_14_degrees():
    """theta_d = -0.5 * omega_s * sin(2(beta - theta)), and omega_s is
    clamped to +/-0.5, so the turn cannot exceed 0.25 rad. The paper
    quotes exactly this as +/-14.3 degrees."""
    import ee
    import geeViz.weather as wx
    out = wx.downscaleWind(_wind(), region=_region(), scale=500)
    # Angle between the input vector and the output one, straight from
    # the components.
    #
    # NOT via windImage: that bicubic-resamples u and v first, and
    # bicubic OVERSHOOTS past the range of its inputs, which nudges the
    # vector angle past the bound and reports a violation the method
    # never committed. Measured 15.9 degrees that way against a true
    # bound of 14.3.
    u, v = out.select("u"), out.select("v")
    mag = u.hypot(v)
    # cos(turn) = (a . b) / (|a| |b|), with a = (10, 0).
    cos_turn = u.multiply(10.0).divide(mag.multiply(10.0)).clamp(-1, 1)
    turn = cos_turn.acos().multiply(180.0 / math.pi)
    d = _stats(turn, ee.Reducer.max())
    got = list(d.values())[0]
    assert got <= 14.4, (
        f"the flow was turned {got:.1f} degrees; the method bounds it "
        f"at 14.3")


def test_a_multiband_dem_does_not_break_the_output():
    """NASADEM ships elevation, num and swb. Carrying all three through
    the curvature makes the final rename fail with a band-count error
    that points nowhere near the DEM."""
    import geeViz.weather as wx
    out = wx.downscaleWind(_wind(), region=_region(), scale=500)
    assert out.bandNames().getInfo() == ["u", "v"]


def test_it_is_an_image_not_an_element():
    """``copyProperties`` returns an Element, which has no bandNames --
    and the AttributeError surfaces in the caller, several lines from
    the cause."""
    import ee
    import geeViz.weather as wx
    out = wx.downscaleWind(_wind(), region=_region(), scale=500)
    assert isinstance(out, ee.Image)


def test_the_forecast_properties_survive():
    """The result should stay usable as a time-lapse frame."""
    import ee
    import geeViz.weather as wx
    src = _wind().set({"system:time_start": 1727308800000,
                       "valid_time": 1727308800000, "lead_hours": 0,
                       "wx_model": "gfs"})
    out = wx.downscaleWind(src, region=_region(), scale=500)
    got = out.toDictionary(["system:time_start", "wx_model",
                            "lead_hours"]).getInfo()
    assert got["wx_model"] == "gfs"
    assert got["system:time_start"] == 1727308800000


def test_the_normalisation_percentile_changes_the_strength():
    """Normalising by the absolute maximum -- what the paper says -- lets
    one canyon flatten the rest of the domain: measured over this box,
    the deepest is 2.1x the 98th percentile of curvature and a typical
    cell reached 8% of its adjustment budget instead of 17%.

    The default deviates for that reason, so the knob has to actually do
    something.
    """
    import ee
    import geeViz.weather as wx
    spread = {}
    for pct in (98, 100):
        out = wx.downscaleWind(_wind(), region=_region(), scale=500,
                               normalize_percentile=pct)
        mag = out.select("u").hypot(out.select("v"))
        d = _stats(mag)
        spread[pct] = d["u_p98"] - d["u_p2"]
    assert spread[98] > spread[100] * 1.05, (
        f"p98 spread {spread[98]:.3f} vs max-normalised {spread[100]:.3f} "
        f"— the percentile is not reaching the normalisation")


def test_the_weights_are_honoured():
    """Zero weights must give back the input: the terms are there to be
    turned off, and a downscaler that adjusts regardless of its weights
    is not configurable, it is just opinionated."""
    import ee
    import geeViz.weather as wx
    out = wx.downscaleWind(_wind(), region=_region(), scale=500,
                           slope_weight=0.0, curvature_weight=0.0)
    mag = out.select("u").hypot(out.select("v"))
    d = _stats(mag, ee.Reducer.minMax())
    assert abs(d["u_min"] - 10.0) < 0.05 and abs(d["u_max"] - 10.0) < 0.05, (
        f"weights of zero still changed the speed: "
        f"{d['u_min']:.3f}..{d['u_max']:.3f}")


def test_region_is_required():
    """The normalisation is defined over a domain. Defaulting it to the
    image footprint would silently reduce a global forecast at 500 m."""
    import geeViz.weather as wx
    with pytest.raises(TypeError):
        wx.downscaleWind(_wind())
