"""``addWindTimeLapse`` must hand the viewer frames it can tell apart.

Two ways a wind lapse collapses into a single still frame, neither of
which raises:

* **The stamp.** ``windImage`` and ``windTiles`` both build a NEW image
  -- speed/direction, or the u/v RGB encoding -- and a new image carries
  no ``system:time_start``. The viewer builds its frame list from the
  distinct dates present, so an unstamped collection formats every frame
  to the same label and nine hours of forecast arrive as one.

* **The format.** ``addTimeLapse`` labels frames ``"YYYY"`` by default,
  which is right for land cover and wrong for weather: a two-day
  forecast is nine frames all labelled 2026.

Earth Engine is stubbed out rather than called. The stamp is
plumbing -- which property is carried from which image -- and that is
exactly what a fake can answer without a network round trip.
"""
import pytest

# geeViz.weather is imported INSIDE each test, the way every other
# weather test in this directory does it. Importing it at module scope
# pulls in getImagesLib, which builds an ee.ImageCollection at import
# time -- so collection fails outright when Earth Engine has not been
# initialized, and takes the whole suite down with it.


class _FakeImage:
    """Just enough ``ee.Image`` to carry properties around."""

    def __init__(self, name, props=None):
        self.name = name
        self.props = dict(props or {})

    def get(self, key):
        return self.props.get(key)

    def set(self, key, value):
        out = _FakeImage(self.name, self.props)
        out.props[key] = value
        return out


class _FakeCollection:
    def __init__(self, images):
        self.images = list(images)

    def map(self, fn):
        return _FakeCollection([fn(i) for i in self.images])


class _FakeMap:
    def __init__(self):
        self.calls = []

    def addTimeLapse(self, collection, viz, name, visible):
        self.calls.append({"collection": collection, "viz": viz,
                           "name": name, "visible": visible})


#: Three forecast hours, six hours apart, in the shape getForecastData
#: returns: the time is a property on the SOURCE image and nowhere else.
TIMES = [1789700000000, 1789721600000, 1789743200000]


@pytest.fixture
def lapse(monkeypatch):
    """Run ``addWindTimeLapse`` with Earth Engine replaced by fakes.

    ``ee.Image`` and ``ee.ImageCollection`` become identity so the
    module's own wrapping does not reject the fakes, and the two image
    builders become markers -- so what is left being tested is the code
    under test and not Earth Engine.
    """
    import geeViz.weather as wx

    monkeypatch.setattr(wx.ee, "Image", lambda x: x)
    monkeypatch.setattr(wx.ee, "ImageCollection", lambda x: x)
    monkeypatch.setattr(wx, "windImage",
                        lambda img, viz: _FakeImage("speed:" + img.name))
    monkeypatch.setattr(wx, "windTiles",
                        lambda img, viz: _FakeImage("tiles:" + img.name))

    Map = _FakeMap()
    src = _FakeCollection([
        _FakeImage("h%d" % i, {"system:time_start": t})
        for i, t in enumerate(TIMES)
    ])
    speed_ic, tiles_ic = wx.addWindTimeLapse(
        Map, src, {"units": "kt", "min": 0, "max": 60}, "GFS wind")
    return Map, speed_ic, tiles_ic, wx


def test_every_frame_keeps_its_own_time(lapse):
    """The collapse guard, on both halves of the pair.

    Drop the re-stamp and both of these become ``[None, None, None]``:
    the viewer sees no distinct dates, and the slider has one stop.
    """
    _, speed_ic, tiles_ic, _wx = lapse
    for label, ic in (("speed", speed_ic), ("tiles", tiles_ic)):
        got = [img.get("system:time_start") for img in ic.images]
        assert got == TIMES, (
            f"the {label} frames lost their times: {got} — the lapse "
            f"collapses to one frame")


def test_the_builders_actually_ran(lapse):
    """Guards the guard.

    A ``map`` that returned the source images untouched would satisfy
    the timestamps test perfectly while encoding nothing.
    """
    _, speed_ic, tiles_ic, _wx = lapse
    assert [i.name for i in speed_ic.images] == ["speed:h0", "speed:h1",
                                                 "speed:h2"]
    assert [i.name for i in tiles_ic.images] == ["tiles:h0", "tiles:h1",
                                                 "tiles:h2"]


def test_the_slider_is_hourly_not_annual(lapse):
    """``addTimeLapse``'s ``"YYYY"`` default would label every frame of a
    two-day forecast 2026."""
    Map, _, _, wx = lapse
    for call in Map.calls:
        assert call["viz"]["dateFormat"] == "YYYYMMdd HH", call["name"]
        assert call["viz"]["advanceInterval"] == "hour", call["name"]


def test_an_explicit_format_wins(monkeypatch):
    import geeViz.weather as wx

    monkeypatch.setattr(wx.ee, "Image", lambda x: x)
    monkeypatch.setattr(wx.ee, "ImageCollection", lambda x: x)
    monkeypatch.setattr(wx, "windImage", lambda img, viz: _FakeImage("s"))
    monkeypatch.setattr(wx, "windTiles", lambda img, viz: _FakeImage("t"))

    Map = _FakeMap()
    src = _FakeCollection([_FakeImage("h0", {"system:time_start": TIMES[0]})])
    wx.addWindTimeLapse(Map, src, {}, "W",
                        dateFormat="YYYY-MM-dd", advanceInterval="day")
    for call in Map.calls:
        assert call["viz"]["dateFormat"] == "YYYY-MM-dd"
        assert call["viz"]["advanceInterval"] == "day"


def test_both_layers_are_added_as_time_lapses(lapse):
    """A speed raster to read and a particle field to watch — the same
    pair ``addWindLayer`` gives, each one animated."""
    Map, _, _, wx = lapse
    assert [c["name"] for c in Map.calls] == ["GFS wind speed",
                                             "GFS wind particles"]
    assert all(c["visible"] for c in Map.calls)


def test_the_particle_frames_carry_the_tile_encoding(lapse):
    """The client decodes u/v with the bounds in viz. If the frames went
    out without them it would fall back to its own constants, and a
    mismatch there yields wind wrong by a scale and an offset — which
    still looks like weather."""
    Map, _, _, wx = lapse
    particles = Map.calls[1]["viz"]
    assert particles["windParticles"] is True
    assert particles["windTileMin"] == wx.WIND_TILE_MIN_MS
    assert particles["windTileMax"] == wx.WIND_TILE_MAX_MS
    assert particles["canQuery"] is False, (
        "the particle frames answer clicks with encoded RGB; the speed "
        "raster is the queryable half")


def test_both_entry_points_build_one_viz(lapse):
    """``addWindLayer`` and ``addWindTimeLapse`` share ``_wind_vizzes``.

    Two copies of the particle dict would not throw when they diverged.
    Pinning it here is what makes the sharing a contract rather than a
    coincidence of the moment.
    """
    Map, _, _, wx = lapse
    speed_viz, particle_viz = wx._wind_vizzes({"units": "kt", "min": 0,
                                               "max": 60})
    for key, value in particle_viz.items():
        assert Map.calls[1]["viz"][key] == value, key
    for key, value in speed_viz.items():
        assert Map.calls[0]["viz"][key] == value, key
