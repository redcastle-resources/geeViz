"""Charting a forecast collection through the chart library.

``getForecastData`` returns an ImageCollection stamped with
``system:time_start`` = the VALID time, which is exactly what
``summarize_and_chart`` keys a line chart on. So a forecast time series
is one call, and hand-rolling one with matplotlib is never the answer.

Sub-daily data is where that path had a hole in it, and both halves of
the hole were quiet:

* ``date_format`` defaults to ``"YYYY"``, which collapses a 31-step
  hourly forecast into ONE row. Not an error -- a wrong chart.
* the obvious fix, ``"YYYY-MM-dd HH:mm"``, CRASHED: the formatted label
  is used as a band name and Earth Engine rejects ``:`` and spaces, so
  it died on ``Image.rename: Invalid band name`` -- which reads as a
  data problem rather than a formatting one.
"""
import datetime
import re

import pytest


def _ee_ready():
    try:
        import ee
        try:
            ee.Number(1).getInfo()
            return True
        except Exception:
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
A = NOW.strftime("%Y-%m-%dT%H:%MZ")
B = (NOW + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%MZ")
GFS_SCALE = 27830


def _series():
    import ee
    import geeViz.weather as wx
    ic = wx.getForecastData(A, B, "gfs", variable="temperature_2m")
    pt = ee.Geometry.Point([-111.89, 40.77]).buffer(20000)
    return ic, pt


def _chart(date_format):
    import ee
    import geeViz.outputLib.charts as cl
    ic, geom = _series()
    return cl.summarize_and_chart(
        ic, geometry=geom, band_names=["temperature_2m"],
        reducer=ee.Reducer.mean(), scale=GFS_SCALE, date_format=date_format)


def test_a_sub_daily_format_no_longer_dies_on_band_naming():
    """The formatted label becomes a band name, and EE rejects ':' and
    ' ' in one. Sanitizing happens where the label is MADE, so the
    labels and the band names stay the same string and the
    ``label----band`` lookup still resolves."""
    r = _chart("YYYY-MM-dd HH:mm")
    df = r["df"]
    assert len(df) > 20, (
        f"a day of hourly GFS gave {len(df)} rows; the steps are being "
        f"collapsed rather than charted")
    label = str(df.index[0])
    assert ":" not in label and " " not in label, (
        f"label {label!r} still carries a character EE rejects in a band "
        f"name; it would crash again the moment it is used as one")
    # Within a day of now, not exactly today: the window spans the
    # current moment, so getForecastData seams analyses before it onto
    # the forecast after it and the first frame can sit just behind.
    day = datetime.datetime.strptime(label[:10], "%Y-%m-%d").replace(
        tzinfo=datetime.timezone.utc)
    assert abs((day - NOW).total_seconds()) < 36 * 3600, label


def test_formats_that_already_worked_are_untouched():
    """The sanitize must be a no-op on a legal format, or it silently
    rewrites everyone else's axis labels."""
    got = {f: str(_chart(f)["df"].index[0])
           for f in ("YYYY", "YYYY-MM-dd", "YYYYMMdd_HHmm")}
    assert got["YYYY"] == NOW.strftime("%Y")
    # Shapes, not exact dates -- the window straddles now (see above).
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", got["YYYY-MM-dd"]), got
    assert re.fullmatch(r"\d{8}_\d{4}", got["YYYYMMdd_HHmm"]), got
    assert "_" not in got["YYYY-MM-dd"], (
        "a hyphenated date was rewritten; only ':' and ' ' should be")


def test_the_default_format_collapses_a_forecast_and_that_is_why_you_pass_one():
    """Documented as a test because it is silent.

    ``YYYY`` is a sensible default for the annual Landsat work this
    library was built for and catastrophic for a forecast: every step of
    a multi-day series lands on one label and the chart is a single
    point. Nothing raises.
    """
    ic, _ = _series()
    n = ic.size().getInfo()
    assert n > 20, f"only {n} forecast steps; this test needs a real series"
    assert len(_chart("YYYY")["df"]) == 1, (
        "the YYYY default no longer collapses a sub-daily series -- good, "
        "but the guidance that says to pass an explicit format is now stale")
    assert len(_chart("YYYY-MM-dd HH:mm")["df"]) > 20


def test_the_collection_is_chartable_without_any_reshaping():
    """The point of the whole thing: what getForecastData returns goes
    straight in. A time stamp on the INIT time, or a band named for the
    product rather than the variable, would both break this."""
    import ee
    import geeViz.outputLib.charts as cl
    ic, geom = _series()
    first = ee.Image(ic.first())
    assert first.bandNames().getInfo() == ["temperature_2m"]
    stamps = ic.aggregate_array("system:time_start").distinct().size().getInfo()
    assert stamps == ic.size().getInfo(), (
        "images share a system:time_start -- that is the INIT time, not the "
        "valid time, and every chart of this collapses to one x value")
    r = cl.summarize_and_chart(
        ic, geometry=geom, band_names=["temperature_2m"],
        reducer=ee.Reducer.mean(), scale=GFS_SCALE,
        date_format="YYYY-MM-dd HH:mm", title="t")
    assert r.get("chart") is not None
    vals = r["df"]["temperature_2m"].tolist()
    assert all(-60 < v < 60 for v in vals if v is not None), (
        f"charted values are not Celsius: {vals[:4]}")
