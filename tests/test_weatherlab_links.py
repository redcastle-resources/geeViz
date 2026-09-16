"""WeatherLab deep links: a LINK, never an embed.

DeepMind's WeatherLab serves ``X-Frame-Options: SAMEORIGIN`` and
redirects unauthenticated requests to Google sign-in, so it cannot be
put in an ``<iframe>`` from a geeViz map or any other origin -- the
frame renders blank with a console refusal and nothing throws on the
Python side. Measured 2026-09-11:

    HTTP/1.1 302 Found
    Location: https://accounts.google.com/ServiceLogin?...
    X-Frame-Options: SAMEORIGIN

So the contract is a URL that opens in a tab. These tests pin the URL
construction against two links captured from the live app, because the
parameter set is not documented anywhere -- it is read off shared links,
and a silently wrong parameter produces a page that loads fine and shows
the wrong thing.
"""
import urllib.parse

import pytest

# Two links captured from the running app. The only ground truth there
# is for this parameter set.
EXAMPLE_BASIC = (
    "https://deepmind.google.com/science/weatherlab"
    "?cyclones_enabled=true&cyclone_models=observed,wn2_blended"
    "&cyclone_legend_elements=1,2,3&weather_enabled=true"
    "&weather_model=weathernext3"
    "&weather_layers=total_precipitation_1hr_mean"
    "&init_time=1789106400000&valid_time=1789106400000"
    "&zoom=2.7465143211384637&center=6.94352,-100.00000"
)
EXAMPLE_CYCLONE = (
    "https://deepmind.google.com/science/weatherlab"
    "?cyclones_enabled=true&cyclone_models=observed,wn2_blended"
    "&cyclone_legend_elements=1,2,3&weather_enabled=true"
    "&weather_model=weathernext3"
    "&weather_layers=total_precipitation_1hr_mean&cyclone=NORBERT"
    "&init_time=1789106400000&valid_time=1789106400000"
    "&zoom=4.704640309242194&center=13.39841,-121.12316&panel=charts"
)


def _params(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


def test_it_reproduces_a_captured_link():
    """Parameter for parameter, against a link from the live app."""
    import geeViz.weather as wx
    got = wx.weatherLabURL(
        cyclones=True, cyclone_models=["observed", "wn2_blended"],
        legend_elements=[1, 2, 3], weather=True, model="weathernext3",
        variable="precipitation", init_time=1789106400000,
        valid_time=1789106400000, zoom=2.7465143211384637,
        center=(-100.0, 6.94352))
    assert _params(got) == _params(EXAMPLE_BASIC), (
        f"\n  got      {sorted(_params(got).items())}"
        f"\n  expected {sorted(_params(EXAMPLE_BASIC).items())}")


def test_it_reproduces_the_named_cyclone_link():
    """Adds ``cyclone`` and the charts panel."""
    import geeViz.weather as wx
    got = wx.weatherLabURL(
        cyclone="NORBERT", cyclone_models=["observed", "wn2_blended"],
        legend_elements=[1, 2, 3], variable="precipitation",
        init_time=1789106400000, valid_time=1789106400000,
        zoom=4.704640309242194, center=(-121.12316, 13.39841),
        panel="charts")
    assert _params(got) == _params(EXAMPLE_CYCLONE)


def test_the_centre_is_not_flipped():
    """WeatherLab writes ``lat,lon``; Earth Engine and geeViz use
    ``(lon, lat)``.

    This is the one error here with no symptom: a flipped pair is a
    perfectly valid coordinate somewhere else on Earth, so the page
    loads, the layers draw, and the scene is simply the wrong place.
    Norbert sat off western Mexico at 13.4N 121.1W -- transposed, that
    is 121.1N, which is not a latitude at all, and the nearer failure
    mode is a pair like 30,-90 becoming -90,30.
    """
    import geeViz.weather as wx
    url = wx.weatherLabURL(center=(-121.12316, 13.39841))
    assert _params(url)["center"] == ["13.39841,-121.12316"]

    # An explicitly ambiguous pair, to catch a transposition that the
    # example above could not.
    url = wx.weatherLabURL(center=(-90.0, 30.0))      # New Orleans-ish
    assert _params(url)["center"] == ["30.00000,-90.00000"], (
        "lon and lat are transposed; the link will open in the wrong "
        "place without any error")


def test_a_weatherlab_centre_string_round_trips():
    """Pasting the app's own ``lat,lon`` back in must not flip it."""
    import geeViz.weather as wx
    url = wx.weatherLabURL(center="13.39841,-121.12316")
    assert _params(url)["center"] == ["13.39841,-121.12316"]


def test_a_variable_maps_to_the_weathernext_band_name():
    """WeatherLab names its layers exactly as WeatherNext names its
    bands, so VARIABLES is already the translation table."""
    import geeViz.weather as wx
    url = wx.weatherLabURL(variable="precipitation")
    assert _params(url)["weather_layers"] == ["total_precipitation_1hr_mean"]
    assert (_params(url)["weather_layers"][0]
            == wx.VARIABLES["precipitation"]["weathernext"][0]), (
        "the mapping has drifted from VARIABLES; the whole point is that "
        "there is one vocabulary, not two")
    # Several layers, and raw names passed straight through.
    url = wx.weatherLabURL(variable=["temperature_2m", "some_future_layer"])
    assert _params(url)["weather_layers"] == [
        "temperature_2m_mean,some_future_layer"]


def test_a_variable_weathernext_does_not_publish_is_refused():
    """Better than a link that loads and shows an empty layer."""
    import geeViz.weather as wx
    with pytest.raises(ValueError, match="not published by WeatherNext"):
        wx.weatherLabURL(variable="relative_humidity_2m")


def test_times_take_the_same_forms_as_getforecastdata():
    """So a window used for a geeViz layer can be reused verbatim."""
    import datetime
    import geeViz.weather as wx
    want = "1789236000000"
    for t in ("2026-09-12T18:00Z", "2026-09-12T18:00",
              datetime.datetime(2026, 9, 12, 18, tzinfo=datetime.timezone.utc),
              1789236000000):
        assert _params(wx.weatherLabURL(valid_time=t))["valid_time"] == [want], t


def test_the_layer_groups_default_from_what_was_asked_for():
    """Asking for a variable turns weather on; asking for a cyclone
    turns cyclones on. Neither should need saying twice."""
    import geeViz.weather as wx
    p = _params(wx.weatherLabURL(variable="precipitation"))
    assert p["weather_enabled"] == ["true"] and p["cyclones_enabled"] == ["false"]
    p = _params(wx.weatherLabURL(cyclone="NORBERT"))
    assert p["cyclones_enabled"] == ["true"] and p["weather_enabled"] == ["false"]
    # ...and an explicit flag still wins.
    p = _params(wx.weatherLabURL(variable="precipitation", weather=False))
    assert p["weather_enabled"] == ["false"]


def test_unknown_parameters_can_be_passed_through():
    """WeatherLab is not a documented API. Its parameter set was read
    off shared links, so there must be a way to send one this function
    has never heard of without waiting for a release."""
    import geeViz.weather as wx
    p = _params(wx.weatherLabURL(extra={"future_param": "x"}))
    assert p["future_param"] == ["x"]


def test_the_docstring_says_it_cannot_be_embedded():
    """The obvious next request is "now put it in an iframe", and the
    answer is a header on Google's side, not something to work around.
    Stating it in the docstring is what stops the attempt."""
    import geeViz.weather as wx
    doc = " ".join(wx.weatherLabURL.__doc__.split())
    assert "X-Frame-Options" in doc
    assert "iframe" in doc.lower()
    assert "sign-in" in doc.lower() or "signed-in" in doc.lower()
