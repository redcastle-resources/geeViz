"""``normalize_units`` and ``resample``, the two knobs on the output.

Both arrived by way of ``getVariable``, which is gone. It had
``to_celsius`` and ``resample``; ``getForecastData`` declared
``to_celsius`` and read it nowhere -- the conversion ran
unconditionally, so passing ``to_celsius=False`` did nothing at all and
the signature was a lie. ``resample`` did not exist there, so collapsing
the two functions would have silently dropped the smoothing every
non-wind layer in the notebook relied on. The flag is now
``normalize_units`` and covers every unit, not only Kelvin.

Both are asserted from the OUTSIDE, on returned pixels, rather than on
the source -- a test that greps for ``if normalize_units`` passes just
as happily when the branch guards the wrong statement.
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


NOW = datetime.datetime.now(datetime.timezone.utc)


def _day(n):
    return (NOW + datetime.timedelta(days=n)).strftime("%Y-%m-%d")


DENVER = [-104.99, 39.74]


def _at_denver(ic, band):
    import ee
    img = ee.Image(ic.first())
    return img.select(band).reduceRegion(
        ee.Reducer.first(), ee.Geometry.Point(DENVER), 10000).getInfo()[band]


def test_normalize_units_false_leaves_the_product_alone():
    """The parameter existed and did nothing. A 2 m temperature near 300
    is Kelvin and near 27 is Celsius, so one reading separates them with
    no ambiguity at any point on Earth where a forecast exists."""
    import geeViz.weather as wx
    kw = dict(variable="temperature_2m")
    k = _at_denver(wx.getForecastData(_day(-2), _day(-1), "weathernext",
                                      normalize_units=False, **kw),
                   "temperature_2m")
    c = _at_denver(wx.getForecastData(_day(-2), _day(-1), "weathernext",
                                      normalize_units=True, **kw),
                   "temperature_2m")
    assert k > 200, f"normalize_units=False still converted: got {k:.1f}"
    assert -60 < c < 60, f"normalize_units=True did not convert: got {c:.1f}"
    assert abs((k - c) - 273.15) < 0.01, (k, c)


def test_normalize_units_does_not_touch_an_already_canonical_product():
    """The conversion is driven by the source unit in VARIABLES, not by
    the variable name -- GFS already publishes Celsius, so flipping the
    flag must be a no-op there, or the guard is converting whatever it
    is handed."""
    import geeViz.weather as wx
    kw = dict(variable="temperature_2m")
    on = _at_denver(wx.getForecastData(_day(-2), _day(-1), "gfs",
                                       normalize_units=True, **kw), "temperature_2m")
    off = _at_denver(wx.getForecastData(_day(-2), _day(-1), "gfs",
                                        normalize_units=False, **kw), "temperature_2m")
    assert on == off, (on, off)
    assert -60 < on < 60


def test_resample_is_applied_and_is_defeatable():
    """These products are 11-28 km. Past zoom 8 one cell is several
    screenfuls, so an unresampled layer is visibly blocky -- which is
    what ``getVariable`` used to prevent and what a plain request would
    have lost.

    Asserted by SAMPLING BETWEEN cell centres: nearest-neighbour repeats
    one cell's value across the whole cell, so two points inside the same
    cell are bit-identical, while an interpolated image varies smoothly
    between them.
    """
    import ee
    import geeViz.weather as wx

    # Two points ~2 km apart -- well inside one 27.8 km GFS cell.
    p1 = ee.Geometry.Point([-104.99, 39.74])
    p2 = ee.Geometry.Point([-104.97, 39.75])

    def _pair(resample):
        ic = wx.getForecastData(_day(-2), _day(-1), "gfs",
                                variable="temperature_2m", resample=resample)
        img = ee.Image(ic.first())
        return [img.reduceRegion(ee.Reducer.first(), p, 1000)
                   .getInfo()["temperature_2m"] for p in (p1, p2)]

    near = _pair(None)
    bicu = _pair("bicubic")
    assert near[0] == near[1], (
        f"resample=None varied within one cell ({near}) — the two probe "
        f"points are no longer inside a single GFS cell, so this test "
        f"cannot tell nearest from bicubic")
    assert bicu[0] != bicu[1], (
        f"resample='bicubic' gave identical values within one cell "
        f"({bicu}) — the resample is not reaching the image")


def test_bicubic_is_the_default():
    """A caller who says nothing gets the smooth layer, which is what
    ``getVariable`` did. Checked on behaviour, not on the signature."""
    import ee
    import geeViz.weather as wx
    import inspect
    assert (inspect.signature(wx.getForecastData)
            .parameters["resample"].default == "bicubic")
    p1 = ee.Geometry.Point([-104.99, 39.74])
    p2 = ee.Geometry.Point([-104.97, 39.75])
    img = ee.Image(wx.getForecastData(_day(-2), _day(-1), "gfs",
                                      variable="temperature_2m").first())
    vals = [img.reduceRegion(ee.Reducer.first(), p, 1000)
               .getInfo()["temperature_2m"] for p in (p1, p2)]
    assert vals[0] != vals[1], vals


def test_getvariable_is_gone_and_not_merely_hidden():
    """The collapse the user authorised. A stale ``__all__`` entry makes
    ``from geeViz.weather import *`` raise AttributeError at import."""
    import geeViz.weather as wx
    assert not hasattr(wx, "getVariable")
    assert "getVariable" not in wx.__all__
    for name in wx.__all__:
        assert hasattr(wx, name), f"__all__ names {name!r}, which does not exist"
