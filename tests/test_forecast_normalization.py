"""Three things are the same whichever model produced the image.

``getForecastData`` exists so that two models can be subtracted. That
needs all three of:

* ``system:time_start`` meaning the **valid** time,
* the band named for the variable, not for the product,
* the value in one unit, whatever the product publishes.

Every assertion here is on returned PIXELS and image properties. The
units table is a set of claims about other people's data; asserting that
the table says "K" proves only that someone typed "K".
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


PAST_A, PAST_B = _day(-2), _day(-1)

# A wet place, a dry place and a warm place, so nothing is all-zero and
# nothing is all-masked.
PTS = {"Seattle": [-122.33, 47.61], "Denver": [-104.99, 39.74],
       "Miami": [-80.19, 25.76]}
CONUS = [-125, 25, -67, 49]

# What a physically possible value looks like ONCE CONVERTED. This is the
# real test: an unconverted Kelvin temperature lands at 300 and an
# unconverted Pascal pressure at 101000, and neither is inside its range.
SANE = {
    "C": (-70, 60),
    "%": (0, 100),
    "g/kg": (0, 40),
    "mm/hr": (0, 150),
    "mm": (0, 1000),
    "hPa": (850, 1100),
    "m/s": (-120, 120),
}


# Spelled out rather than derived from the table, because a parametrize
# list is built at COLLECTION time -- and importing geeViz.weather pulls
# in getImagesLib, which constructs an ee.ImageCollection at import and
# so needs an initialized client. There is not one yet at collection.
#
# test_the_pair_list_matches_the_table keeps this honest, and is the
# reason a stale copy cannot quietly shrink the coverage here.
PAIRS = [
    ("dewpoint_2m", "euro"),
    ("dewpoint_2m", "gfs"),
    ("dewpoint_2m", "weathernext"),
    ("dewpoint_2m", "weathernext_stations"),
    ("mean_sea_level_pressure", "euro"),
    ("mean_sea_level_pressure", "weathernext"),
    ("precipitation", "gfs"),
    ("precipitation", "weathernext"),
    ("precipitation_accumulated", "euro"),
    ("relative_humidity_2m", "gfs"),
    ("sea_surface_temperature", "weathernext"),
    ("specific_humidity_2m", "gfs"),
    ("temperature_2m", "euro"),
    ("temperature_2m", "gfs"),
    ("temperature_2m", "weathernext"),
    ("temperature_2m", "weathernext_stations"),
    ("total_cloud_cover", "gfs"),
    ("total_cloud_cover", "weathernext"),
    ("wind_speed_10m", "weathernext"),
]


def test_the_pair_list_matches_the_table():
    """If PAIRS drifted from VARIABLES, every parametrized test above
    would still pass -- while quietly not covering the variable someone
    just added. That is the same silent-shrink failure the module is
    about, one level up."""
    import geeViz.weather as wx
    live = sorted((v, m) for v in wx.VARIABLES for m in wx.MODELS
                  if wx.publishes(v, m))
    assert live == sorted(PAIRS), (
        "VARIABLES changed; update PAIRS.\n  added: "
        f"{sorted(set(live) - set(PAIRS))}\n  gone:  "
        f"{sorted(set(PAIRS) - set(live))}")
    assert len({m for _, m in live}) == len(wx.MODELS), (
        "some model contributes no variable at all")


@pytest.mark.parametrize("variable,model", PAIRS)
def test_values_are_physically_possible_in_the_canonical_unit(variable, model):
    import ee
    import geeViz.weather as wx
    unit = wx.CANONICAL_UNITS[variable]
    lo, hi = SANE[unit]
    img = ee.Image(wx.getForecastData(PAST_A, PAST_B, model,
                                      variable=variable).first())
    got = {}
    for name, p in PTS.items():
        v = img.reduceRegion(ee.Reducer.first(),
                             ee.Geometry.Point(p), 20000).getInfo()[variable]
        if v is not None:                   # SST is masked over land
            got[name] = v
    ext = img.reduceRegion(ee.Reducer.minMax(), ee.Geometry.Rectangle(CONUS),
                           50000, bestEffort=True).getInfo()
    got.update({k: v for k, v in ext.items() if v is not None})
    assert got, f"{variable}/{model} returned nothing anywhere"
    for where, v in got.items():
        assert lo <= v <= hi, (
            f"{model} {variable} = {v:.4g} at {where}, outside {lo}..{hi} "
            f"for {unit!r} — the conversion from "
            f"{wx.VARIABLES[variable][model][1]!r} is wrong or missing")


@pytest.mark.parametrize("variable,model", PAIRS)
def test_the_image_says_what_unit_it_is_in(variable, model):
    """``wx_units`` travels with the image, so a reader need not know the
    table -- and a chart can label itself."""
    import ee
    import geeViz.weather as wx
    img = ee.Image(wx.getForecastData(PAST_A, PAST_B, model,
                                      variable=variable).first())
    assert img.get("wx_units").getInfo() == {
        variable: wx.CANONICAL_UNITS[variable]}


def test_the_models_actually_agree_once_converted():
    """The point of the exercise, stated as a number.

    Four products, three spellings of the band, two of them in Kelvin.
    Converted, they must agree to within forecast disagreement -- a few
    degrees. Unconverted, two of them sit 273 apart, which is not a
    forecast difference and would not be read as a unit bug on a chart.
    """
    import ee
    import geeViz.weather as wx
    pt = ee.Geometry.Point(PTS["Denver"])
    got = {}
    for m in ("gfs", "euro", "weathernext", "weathernext_stations"):
        img = ee.Image(wx.getForecastData(PAST_A, PAST_B, m,
                                          variable="temperature_2m").first())
        got[m] = img.reduceRegion(ee.Reducer.first(), pt,
                                  10000).getInfo()["temperature_2m"]
    spread = max(got.values()) - min(got.values())
    assert spread < 6, (
        f"four models disagree by {spread:.1f} C at one point and hour; "
        f"that is a unit problem, not a forecast difference: {got}")


def test_wind_components_are_metres_per_second():
    """``downscaleWind`` and the particle tiles both hard-code m/s
    thresholds, so this is not a labelling nicety. A km/h field would
    render as a permanent gale and downscale against the wrong bounds.
    """
    import ee
    import geeViz.weather as wx
    reg = ee.Geometry.Rectangle(CONUS)
    for m in ("gfs", "euro", "weathernext"):
        img = ee.Image(wx.getForecastData(PAST_A, PAST_B, m).first())
        assert img.bandNames().getInfo() == ["u", "v"]
        assert img.get("wx_units").getInfo() == {"u": "m/s", "v": "m/s"}
        p99 = img.select(0).hypot(img.select(1)).reduceRegion(
            ee.Reducer.percentile([99]), reg, 50000,
            bestEffort=True).getInfo()["u"]
        # A p99 10 m wind over CONUS is ~10 m/s. In km/h it would be ~36,
        # in knots ~20 -- so this separates all three.
        assert 2 < p99 < 25, f"{m} p99 speed {p99:.1f} is not m/s"


def test_bounded_variables_are_clamped_after_resampling():
    """``resample`` runs before selection and bicubic OVERSHOOTS at a
    saturated edge. Measured on one GFS image over CONUS before the
    clamp: cloud cover -10.3 to 111.4 percent, and precipitation to
    -1.09 mm/hr. Negative rain breaks masks and area sums quietly, and
    it looks like data.

    Bicubic is also what makes this test meaningful: with
    ``resample=None`` there is no overshoot to clamp, so the assertion
    would pass against a clamp that does nothing.
    """
    import ee
    import geeViz.weather as wx
    reg = ee.Geometry.Rectangle(CONUS)
    for variable, model in (("total_cloud_cover", "gfs"),
                            ("precipitation", "gfs"),
                            ("relative_humidity_2m", "gfs")):
        lo, hi = wx.PHYSICAL_RANGES[variable]
        img = ee.Image(wx.getForecastData(PAST_A, PAST_B, model,
                                          variable=variable,
                                          resample="bicubic").first())
        d = img.reduceRegion(ee.Reducer.minMax(), reg, 20000,
                             bestEffort=True).getInfo()
        g = {k.rsplit("_", 1)[1]: v for k, v in d.items()}
        assert g["min"] >= lo - 1e-9, (variable, model, g)
        if hi is not None:
            assert g["max"] <= hi + 1e-9, (variable, model, g)


def test_an_unhandled_unit_raises_instead_of_passing_through():
    """The safety property of the conversion table.

    A variable added with a unit nobody wrote a conversion for must fail
    at the call. The alternative is a map of plausible, finite, wrong
    numbers -- which is the failure mode this whole module exists to
    prevent, and the one nobody notices.
    """
    import geeViz.weather as wx
    with pytest.raises(ValueError, match="no conversion from"):
        wx._conversion("furlongs/fortnight", "m/s")
    # And the real path uses it, rather than having its own copy.
    saved = dict(wx.VARIABLES["temperature_2m"])
    try:
        wx.VARIABLES["temperature_2m"]["gfs"] = ("temperature_2m_above_ground",
                                                 "degrees Rankine")
        with pytest.raises(ValueError, match="no conversion from"):
            wx.getForecastData(PAST_A, PAST_B, "gfs",
                               variable="temperature_2m")
    finally:
        wx.VARIABLES["temperature_2m"] = saved


def test_ecmwf_precipitation_is_refused_with_the_reason():
    """It used to return an all-zero image, silently.

    ECMWF's ``total_precipitation_sfc`` is a running total since the run
    started -- measured across one run, the CONUS mean climbs 0 ->
    0.0003 -> 0.0007 -> 0.0038 m at leads 0/3/6/24, and it is
    IDENTICALLY ZERO at lead 0. A past window returns shortest-lead
    analyses, so asking ECMWF for precipitation handed back a confident,
    perfectly dry forecast everywhere.
    """
    import ee
    import geeViz.weather as wx
    assert not wx.publishes("precipitation", "euro")
    with pytest.raises(ValueError, match="running total since initialization"):
        wx.getForecastData(PAST_A, PAST_B, "euro", variable="precipitation")

    # The band is still reachable as what it actually is.
    assert wx.publishes("precipitation_accumulated", "euro")
    img = ee.Image(wx.getForecastData(_day(1), _day(3), "euro",
                                      variable="precipitation_accumulated"
                                      ).sort("lead_hours", False).first())
    assert img.bandNames().getInfo() == ["precipitation_accumulated"]
    mx = img.reduceRegion(ee.Reducer.max(), ee.Geometry.Rectangle(CONUS),
                          50000, bestEffort=True).getInfo()[
        "precipitation_accumulated"]
    # mm, not metres: a multi-day accumulation maximum over CONUS is tens
    # of mm. In metres it would be 0.0x and read as "no rain".
    assert 0.5 < mx < 1000, f"accumulated precipitation max {mx} is not mm"


def test_raw_passthrough_is_not_normalized_and_says_so():
    """``variable=None`` has no table entry, so nothing knows what the
    bands are in. It must not claim a unit it cannot know."""
    import ee
    import geeViz.weather as wx
    img = ee.Image(wx.getForecastData(PAST_A, PAST_B, "weathernext",
                                      variable=None).first())
    assert img.get("wx_units").getInfo() in ({}, None)
    v = img.select(["temperature_2m_mean"]).reduceRegion(
        ee.Reducer.first(), ee.Geometry.Point(PTS["Denver"]),
        20000).getInfo()["temperature_2m_mean"]
    assert v > 200, f"raw WeatherNext temperature should still be Kelvin, got {v}"


def test_every_variable_has_a_canonical_unit_and_a_conversion():
    """A variable added to VARIABLES without a CANONICAL_UNITS entry
    raises KeyError deep inside _resolve_bands; catch it here, by name,
    instead."""
    import geeViz.weather as wx
    missing = [v for v in wx.VARIABLES if v not in wx.CANONICAL_UNITS]
    assert not missing, f"no CANONICAL_UNITS entry for {missing}"
    for variable, entry in wx.VARIABLES.items():
        for model in wx.MODELS:
            band = entry.get(model)
            if not isinstance(band, tuple):
                continue
            # Raises if the pair is absent -- which is the assertion.
            wx._conversion(band[1], wx.CANONICAL_UNITS[variable])
