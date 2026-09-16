"""Terrain downscaling for temperature, dewpoint and precipitation.

The companions to ``downscaleWind``, from the same paper. Each is a
redistribution WITHIN a forecast cell, driven by how far a fine pixel
sits above that cell's own mean elevation -- so every test here works
from an explicitly computed ``dz`` rather than from map appearance.

The reference elevation is the thing most likely to be got wrong and
least likely to look wrong: measuring from sea level instead of the
cell mean gives every mountain a large, smooth, entirely plausible cold
bias.

Named ``test_weather_*`` deliberately, and not for tidiness. pytest
IMPORTS every test module during collection before running any of them,
and ``test_esriLib`` installs a stub at
``sys.modules["geeViz.geeView"]`` at import time -- so that stub is live
for the whole run of every file collected ahead of it alphabetically.
An EE-dependent file sorting before ``test_esriLib`` cannot reach
``robustInitializer``, reads that as "Earth Engine not reachable", and
SKIPS its entire contents while passing perfectly on its own. This file
sat at ``test_downscale_variables`` and did exactly that: eleven green
tests, silently not run, in every full suite.

Every other weather test file already sorts after ``test_esriLib`` by
accident. That is the real reason they work, and it is worth knowing
before adding another one.
"""
import datetime

import pytest


def _ee_ready():
    try:
        import ee
        try:
            ee.Number(1).getInfo()
            return True
        except Exception:
            # Imported HERE rather than at the top: it is only needed
            # when EE is not already up. Eagerly importing it makes the
            # probe fail for a reason that has nothing to do with EE --
            # see the module docstring on the test_esriLib stub.
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


NOW = datetime.datetime.now(datetime.timezone.utc)
PAST_A = (NOW - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
PAST_B = (NOW - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

ROCKIES = [-107.5, 38.5, -105.0, 40.5]
# A valley floor and a summit ~1500 m above it, close enough together to
# fall in neighbouring GFS cells.
VALLEY = [-106.90, 39.06]
SUMMIT = [-106.29, 39.25]


def _fc(variable):
    import ee
    import geeViz.weather as wx
    return ee.Image(wx.getForecastData(PAST_A, PAST_B, "gfs",
                                       variable=variable).first())


def _at(img, lonlat, scale=500):
    import ee
    d = img.reduceRegion(ee.Reducer.first(),
                         ee.Geometry.Point(lonlat), scale).getInfo()
    vals = [v for v in d.values() if v is not None]
    assert vals, f"nothing sampled at {lonlat}"
    return vals[0]


def _dz(img, lonlat):
    """How far the point sits above its own forecast cell's mean."""
    import geeViz.weather as wx
    dz, _ = wx._elevation_delta(img, None, 500)
    return _at(dz, lonlat)


def _unit_precip():
    """A precipitation field of exactly 1 everywhere, on the GFS grid.

    So the downscaled value IS the multiplier, readable at any pixel.
    Tying a test of the formula to whether it happened to rain in
    Colorado today means it quietly stops testing on dry days.
    """
    import ee
    real = _fc("precipitation")
    return (ee.Image.constant(1.0).rename("precipitation")
              .setDefaultProjection(real.projection()))


def _ramp_dem(wavelength_deg=0.4, amplitude_m=6000):
    """Elevation that swings hard WITHIN each forecast cell.

    Deliberately not a linear ramp. ``dz`` is measured against the cell
    mean, and that reference is interpolated the same way the forecast
    is -- so a smooth ramp reproduces itself, dz collapses to zero, and
    there is nothing to redistribute. Only relief SHORTER than the cell
    survives the subtraction, which is exactly the signal the method
    exists to recover.
    """
    import ee
    import math
    return (ee.Image.pixelLonLat().select("latitude")
            .multiply(2 * math.pi / wavelength_deg).sin()
            .multiply(amplitude_m).rename("elevation")
            .setDefaultProjection("EPSG:4326", None, 500))


def _above_and_below(img):
    """The probe points, sorted by MEASURED offset from the cell mean.

    Which of two nearby mountain points sits above its own forecast
    cell's mean is not something to assume -- the cell means differ, and
    the higher summit here is in fact 200 m BELOW its cell's mean while
    the valley is above its own. Measuring costs one round trip and
    removes a whole class of test that fails for the wrong reason.
    """
    pts = sorted(((_dz(img, p), p) for p in (VALLEY, SUMMIT)))
    (dz_lo, below), (dz_hi, above) = pts
    assert dz_lo < -100 and dz_hi > 100, (
        f"probe points no longer straddle their cell means: {pts}")
    return (above, dz_hi), (below, dz_lo)


def test_the_correction_is_the_lapse_rate_times_the_elevation_offset():
    """The whole model, checked at two points with opposite offsets.

    Asserted against a dz computed from the same helper the function
    uses, so this measures the FORMULA rather than re-deriving a DEM.
    """
    import geeViz.weather as wx
    t = _fc("temperature_2m")
    ds = wx.downscaleTemperature(t, scale=500)
    # Compared against the SAME function with a zero rate, not against
    # the coarse image: the downscaled output is computed at 500 m while
    # the coarse one is bicubic-resampled from 28 km, so differencing
    # the two carries an interpolation offset of a few hundredths that
    # has nothing to do with the lapse rate.
    flat = wx.downscaleTemperature(t, scale=500, lapse_rate=0.0)
    (above, dz_a), (below, dz_b) = _above_and_below(t)
    for pt, dz in ((above, dz_a), (below, dz_b)):
        got = _at(ds, pt) - _at(flat, pt)
        want = wx.DEFAULT_LAPSE_RATE * dz
        assert abs(got - want) < 0.15, (
            f"at {pt}: dz={dz:.0f} m so the correction should be "
            f"{want:+.2f} C, got {got:+.2f} C")
    assert (_at(ds, above) - _at(flat, above)) < 0 < (
        _at(ds, below) - _at(flat, below)), (
        "above the cell mean must cool and below must warm")


def test_a_custom_lapse_rate_is_used():
    """MicroMet varies the rate by month; the default is the annual
    mean. A rate that were silently ignored would still look right."""
    import geeViz.weather as wx
    t = _fc("temperature_2m")
    (pt, dz), _ = _above_and_below(t)
    # Both sides go through the identical projection path, so the only
    # difference between them IS the rate.
    zero = _at(wx.downscaleTemperature(t, scale=500, lapse_rate=0.0), pt)
    steep = _at(wx.downscaleTemperature(t, scale=500, lapse_rate=-0.010), pt)
    assert abs((steep - zero) - (-0.010 * dz)) < 0.15, (steep, zero, dz)
    # A rate that were ignored would leave these identical.
    assert abs(steep - zero) > 0.5, (
        f"lapse_rate made no difference at dz={dz:.0f} m")


def test_flat_terrain_changes_nothing():
    """dz is zero everywhere, so the correction must be too. Catches a
    reference elevation of sea level, which would shift the whole field
    by 1500 * lapse."""
    import ee
    import geeViz.weather as wx
    t = _fc("temperature_2m")
    flat = (ee.Image.constant(1500).rename("elevation")
              .setDefaultProjection("EPSG:4326", None, 500))
    ds = wx.downscaleTemperature(t, dem=flat, scale=500)
    for pt in (VALLEY, SUMMIT):
        assert abs(_at(ds, pt) - _at(t, pt)) < 0.02, (
            f"flat terrain shifted {pt} by "
            f"{_at(ds, pt) - _at(t, pt):+.3f} C")


def test_the_reference_is_the_cell_mean_not_sea_level():
    """Stated directly, because it is the failure that looks like data.

    Over a mountain domain the cell-mean elevation is thousands of
    metres, so a sea-level reference would make every correction
    negative and large. The mean of dz over a region is near zero by
    construction; the mean of (z - 0) is not.
    """
    import ee
    import geeViz.weather as wx
    t = _fc("temperature_2m")
    dz, dem = wx._elevation_delta(t, None, 500)
    reg = ee.Geometry.Rectangle(ROCKIES)
    m_dz = dz.reduceRegion(ee.Reducer.mean(), reg, 1000,
                           bestEffort=True).getInfo()
    m_z = dem.reduceRegion(ee.Reducer.mean(), reg, 1000,
                           bestEffort=True).getInfo()
    mean_dz = list(m_dz.values())[0]
    mean_z = list(m_z.values())[0]
    assert mean_z > 1500, f"test domain is not mountainous: {mean_z:.0f} m"
    assert abs(mean_dz) < 120, (
        f"mean dz over the domain is {mean_dz:.0f} m, not ~0 — the "
        f"reference is not the forecast cell mean")


def test_the_reference_elevation_does_not_print_the_forecast_grid():
    """The checkerboard.

    ``_cell_mean_elevation`` ends in ``reproject(forecast projection)``,
    which is piecewise CONSTANT per cell -- measured over Utah, the step
    between adjacent 500 m pixels was 0.002 m almost everywhere and 986 m
    at a cell edge. But the forecast it corrects is resampled BICUBIC and
    crosses those edges smoothly, so subtracting one from the other
    stamped the forecast grid onto the output: an ~8 C jump between
    neighbouring pixels, visible as a checkerboard of 28 km squares that
    reads as terrain nobody can find on a map.

    Two independent ways to catch it, because a smoothness threshold
    alone would also flag a genuine cliff:

    * the reference must actually VARY between adjacent fine pixels --
      a piecewise-constant field has a median step of essentially zero;
    * ``dz`` must be no rougher than the DEM it came from, since the
      thing subtracted from it is supposed to be smooth at this scale.
    """
    import ee
    import geeViz.weather as wx
    reg = ee.Geometry.Rectangle(ROCKIES)
    t = _fc("temperature_2m")

    def _steps(img):
        k = ee.Kernel.fixed(3, 1, [[-1, 0, 1]], 1, 0, False)
        d = img.convolve(k).abs().reduceRegion(
            ee.Reducer.percentile([50]).combine(ee.Reducer.max(), None, True),
            reg, 500, bestEffort=True, maxPixels=1e9).getInfo()
        g = {kk.rsplit("_", 1)[1]: v for kk, v in d.items()}
        return g["p50"], g["max"]

    dz, dem = wx._elevation_delta(t, None, 500)
    coarse = wx._cell_mean_elevation(dem, t, 1000)

    med, _ = _steps(coarse)
    assert med > 1.0, (
        f"the cell-mean elevation changes by {med:.4f} m between adjacent "
        f"500 m pixels -- it is piecewise constant on the forecast grid, "
        f"which prints that grid onto every downscaled field")

    _, dz_max = _steps(dz)
    _, dem_max = _steps(dem)
    assert dz_max <= dem_max * 1.3, (
        f"dz jumps {dz_max:.0f} m between adjacent pixels where the DEM "
        f"itself only jumps {dem_max:.0f} m -- the extra discontinuity is "
        f"the forecast grid, not terrain")


def test_the_output_is_computed_at_the_requested_scale():
    """Inheriting the forecast's 28 km projection makes every terrain
    term compute at 28 km and upsample: real in the arithmetic,
    invisible on the map."""
    import geeViz.weather as wx
    t = _fc("temperature_2m")
    assert abs(t.projection().nominalScale().getInfo() - 27800) < 500
    for s in (250, 500, 1000):
        got = (wx.downscaleTemperature(t, scale=s)
                 .projection().nominalScale().getInfo())
        assert abs(got - s) < 1, (s, got)


def test_band_name_and_forecast_identity_survive():
    """A downscaled image that lost system:time_start silently drops out
    of every chart and time lapse it is put in."""
    import geeViz.weather as wx
    t = _fc("temperature_2m")
    ds = wx.downscaleTemperature(t, scale=500)
    assert ds.bandNames().getInfo() == ["temperature_2m"]
    for prop in ("system:time_start", "valid_time", "wx_model"):
        assert ds.get(prop).getInfo() == t.get(prop).getInfo(), prop


def test_dewpoint_uses_a_shallower_rate_so_humidity_rises_with_height():
    """The reason dewpoint is a separate function rather than the same
    one. Downscaling temperature alone manufactures a mountain drier
    than the forecast said."""
    import geeViz.weather as wx
    assert wx.DEFAULT_DEWPOINT_LAPSE_RATE > wx.DEFAULT_LAPSE_RATE, (
        "dewpoint must fall more slowly with height than temperature")
    t, td = _fc("temperature_2m"), _fc("dewpoint_2m")
    (pt, dz), _ = _above_and_below(t)
    # Zero-rate versions as the baseline, so the comparison is between
    # two images computed the same way.
    t0 = wx.downscaleTemperature(t, scale=500, lapse_rate=0.0)
    td0 = wx.downscaleDewpoint(td, scale=500, lapse_rate=0.0)
    t_ds = wx.downscaleTemperature(t, scale=500)
    td_ds = wx.downscaleDewpoint(td, scale=500)
    # Dewpoint depression = T - Td. Smaller means moister.
    before = _at(t0, pt) - _at(td0, pt)
    after = _at(t_ds, pt) - _at(td_ds, pt)
    assert after < before, (
        f"{dz:.0f} m above the cell mean the air should get MOISTER: "
        f"depression went {before:.2f} -> {after:.2f} C")


def test_precipitation_is_enhanced_uphill_and_reduced_downhill():
    import geeViz.weather as wx
    p = _fc("precipitation")
    ds = wx.downscalePrecipitation(p, scale=500)
    base0 = wx.downscalePrecipitation(p, scale=500, chi=0.0)
    (above, dz_a), (below, dz_b) = _above_and_below(p)
    if _at(base0, above) <= 0 and _at(base0, below) <= 0:
        pytest.skip("both probe cells are dry; nothing to redistribute")
    if _at(base0, above) > 0:
        assert _at(ds, above) > _at(base0, above), (
            f"{dz_a:.0f} m above the cell mean should be WETTER")
    if _at(base0, below) > 0:
        assert _at(ds, below) < _at(base0, below), (
            f"{dz_b:.0f} m below the cell mean should be DRIER")


def test_precipitation_never_goes_negative_or_unbounded():
    """The formula has a POLE at chi*dz = 1 -- about 3300 m of relief at
    the default -- past which it changes sign and returns negative rain.
    Checked against a synthetic DEM with relief far beyond it, because
    real terrain may not reach the pole in any one cell and the bug
    would sit there waiting for somewhere that does.
    """
    import ee
    import geeViz.weather as wx
    reg = ee.Geometry.Rectangle(ROCKIES)
    # Unit field, so every output value is the multiplier itself.
    ds = wx.downscalePrecipitation(_unit_precip(), dem=_ramp_dem(), scale=500)
    stats = ds.reduceRegion(ee.Reducer.minMax(), reg, 2000,
                            bestEffort=True, maxPixels=1e9).getInfo()
    lo = min(v for v in stats.values() if v is not None)
    hi = max(v for v in stats.values() if v is not None)
    assert lo >= 0, f"negative precipitation ({lo}) past the pole"
    assert hi <= 5.0 + 1e-6, (
        f"multiplier reached {hi}, past the default max_ratio of 5")
    assert lo >= 1 / 5.0 - 1e-6, (
        f"multiplier fell to {lo}, below 1/max_ratio")


def test_the_multiplier_rises_with_dz_even_past_the_pole():
    """Bounded and positive is not enough -- it must point the right way.

    Past ``chi*dz = 1`` the raw formula goes NEGATIVE, and the outer
    ratio clamp then pins that to its FLOOR. Without the inner clamp on
    ``chi*dz``, the ground furthest above its cell mean comes back with
    the SMALLEST multiplier instead of the largest: still positive,
    still inside max_ratio, and exactly inverted.

    Reaching the pole takes a deliberately vicious DEM. ``dz`` is relief
    WITHIN one forecast cell -- subtracting the cell mean removes any
    broad ramp -- so a linear slope across the domain, however steep,
    never gets there. It takes a short wavelength against the 0.25 deg
    cell, and about 3300 m of swing inside it. Real terrain does not
    quite reach that, which is why the guard is easy to drop and hard to
    notice.
    """
    import ee
    import geeViz.weather as wx
    # ~0.4 deg wavelength against a 0.25 deg cell, +/-6000 m amplitude:
    # chi*dz reaches past the pole at 1.
    dem = _ramp_dem()
    ds = wx.downscalePrecipitation(_unit_precip(), dem=dem, scale=500)
    dz, _ = wx._elevation_delta(_unit_precip(), dem, 500)

    pts = [[-106.5, 38.6 + 0.07 * i] for i in range(16)]
    pairs = sorted((_at(dz, p), _at(ds, p)) for p in pts)
    zs = [a for a, _ in pairs]
    ms = [b for _, b in pairs]
    assert max(zs) * wx.DEFAULT_PRECIP_CHI > 1.0, (
        f"this DEM never reaches the pole (max chi*dz = "
        f"{max(zs) * wx.DEFAULT_PRECIP_CHI:.2f}), so the test cannot see "
        f"the sign flip it exists to catch")
    assert all(b >= a - 1e-6 for a, b in zip(ms, ms[1:])), (
        f"multiplier falls as dz rises. "
        f"dz={[round(z) for z in zs]} "
        f"mul={[round(m, 2) for m in ms]}")
    assert ms[-1] > ms[0], (ms[0], ms[-1])


def test_the_ratio_clamp_is_reachable_and_symmetric():
    """max_ratio is a parameter, so it has to actually bind.

    On a unit field, because the output value then IS the multiplier.
    Measured against a real GFS field this passed or failed on whether
    it happened to be raining over the Rockies -- and on a dry day both
    caps returned the same number and the test proved nothing.
    """
    import ee
    import geeViz.weather as wx
    reg = ee.Geometry.Rectangle(ROCKIES)

    def _max(cap):
        img = wx.downscalePrecipitation(_unit_precip(), dem=_ramp_dem(),
                                        scale=500, max_ratio=cap)
        return max(v for v in img.reduceRegion(
            ee.Reducer.max(), reg, 2000, bestEffort=True).getInfo().values()
            if v is not None)

    tight, wide = _max(1.5), _max(4.0)
    assert tight < wide, (
        f"max_ratio does not bind: 1.5 and 4.0 both gave {tight:.3f}")
    # Each cap is reached, not merely respected -- a clamp that never
    # engages is untested by a bound check.
    assert abs(tight - 1.5) < 0.01, tight
    assert abs(wide - 4.0) < 0.01, wide
