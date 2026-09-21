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
    def __init__(self, images, tag="src"):
        self.images = list(images)
        self.tag = tag

    def map(self, fn):
        out = _FakeCollection([fn(i) for i in self.images])
        # windImage frames are the speed collection; that is the one the
        # query must be retargeted to.
        out.tag = self.images and fn(self.images[0]).name.split(":")[0] or "?"
        return out

    def serialize(self):
        """viz travels as JSON, so the query target goes over serialized."""
        return "SERIALIZED:" + self.tag


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


def test_it_adds_exactly_one_lapse(lapse):
    """One layer, not two.

    Each frame carries the speed field AND the particles, because
    windTiles already holds both: u in red, v in green, and speed is
    sqrt(u^2 + v^2). A second Earth Engine layer under the particles
    would double the tiles per frame for data already on the wire.
    """
    Map, _, _, wx = lapse
    assert len(Map.calls) == 1, (
        f"expected one time lapse, got {[c['name'] for c in Map.calls]}")
    assert Map.calls[0]["name"] == "GFS wind"
    assert Map.calls[0]["visible"] is True


def test_the_frames_are_the_uv_encoding(lapse):
    """It is the u/v frames that go on the map — the client reads them
    numerically and paints both halves. The speed collection is returned
    for querying and re-use, not drawn."""
    _, speed_ic, tiles_ic, _wx = lapse
    Map = lapse[0]
    assert Map.calls[0]["collection"] is tiles_ic
    assert [i.name for i in tiles_ic.images] == ["tiles:h0", "tiles:h1",
                                                 "tiles:h2"]


def test_the_layer_carries_the_tile_encoding(lapse):
    """The client decodes u/v with the bounds in viz. Without them it
    falls back to its own constants, and a mismatch there yields wind
    wrong by a scale and an offset — which still looks like weather."""
    Map, _, _, wx = lapse
    viz = Map.calls[0]["viz"]
    assert viz["windParticles"] is True
    assert viz["windTileMin"] == wx.WIND_TILE_MIN_MS
    assert viz["windTileMax"] == wx.WIND_TILE_MAX_MS


def test_the_client_is_told_to_draw_the_speed_field(lapse):
    """windSpeedRaster is what makes it the merged layer rather than a
    bare particle layer, and the ramp has to travel with it."""
    Map, _, _, wx = lapse
    viz = Map.calls[0]["viz"]
    assert viz["windSpeedRaster"] is True
    assert viz["windSpeedPalette"], "no palette for the client to color with"
    assert viz["windRampMinMs"] == 0, (
        "the ramp must use the UNCLAMPED stretch; windMinSpeedMs carries "
        "a 1 m/s advection floor that would shift every color")
    assert viz["windRampMaxMs"] > 0


def test_no_rendering_keys_leak_onto_the_merged_layer(lapse):
    """The one that would break the map silently.

    ``bands``, ``min``, ``max`` and ``palette`` are forwarded to
    ``getMapId``. The image they would be applied to is already
    ``visualize``d — a finished 8-bit RGB — so re-stretching it there
    would corrupt the very u/v bytes the client decodes, and the wind
    would come out wrong rather than absent.
    """
    Map, _, _, wx = lapse
    viz = Map.calls[0]["viz"]
    for key in ("bands", "min", "max", "palette", "gain", "bias", "gamma"):
        assert key not in viz, (
            f"{key!r} reached the merged layer; it goes to getMapId and "
            f"will re-stretch an already-visualized RGB")


def test_the_query_still_reads_real_weather(lapse):
    """The inspector must report speed and direction, not bytes.

    The viewer takes ``viz.queryItem`` in place of the item it draws, so
    the layer on screen can be the u/v encoding while clicks are
    answered from the speed/direction collection.
    """
    Map, speed_ic, _tiles, _wx = lapse
    viz = Map.calls[0]["viz"]
    assert viz["canQuery"] is True
    assert viz["windQueryItem"] == "SERIALIZED:speed", (
        "the query is not pointed at the speed collection — clicking the "
        "wind layer would report the u/v encoding as if it were weather")
    # Serialized, not the object: viz travels to the browser as JSON, and
    # an ee object here raises "not JSON serializable" at Map.view().
    assert isinstance(viz["windQueryItem"], str)
    assert "queryItem" not in viz, (
        "a raw ee object under `queryItem` would break json.dumps(viz)")


def test_the_legend_is_one_entry(lapse):
    """One layer, one key.

    The separate speed layer used to bring its own color bar, and for a
    while the grouped layer carried two entries — a ramp and a comet —
    which is two rows describing one thing. ``_particle_swatch`` already
    draws the comet OVER the ramp, which is exactly what the map shows,
    so the grouped layer needs nothing else.
    """
    Map, _, _, wx = lapse
    legend = Map.calls[0]["viz"]["classLegendDict"]
    assert len(legend) == 1, (
        f"the grouped layer should have one legend entry, got "
        f"{list(legend)}")
    label, swatch = next(iter(legend.items()))
    assert "kt" in label and "0-60" in label, (
        f"the entry is not labelled with its stretch and unit: {label!r}")
    assert swatch.count("linear-gradient") >= 2, (
        "the swatch is not the comet over the ramp — one of the two "
        "halves of the layer has nothing in the key")
    # Counting gradients is not enough, and this is how the legend
    # shipped BLANK: speed_viz["palette"] is a comma STRING, iterating
    # it yields single characters, _rgb_of reads each as an invalid hex
    # and answers white -- so the swatch was a white box that still
    # contained two perfectly good linear-gradients. Assert on COLOR.
    import re
    stops = re.findall(r"rgba\((\d+),(\d+),(\d+),", swatch)
    assert stops, f"the swatch has no rgba stops at all: {swatch[:120]}"
    assert any(s != ("255", "255", "255") for s in stops), (
        "every stop in the swatch is white — the palette was iterated "
        "as a string and each character read as an invalid hex")
    assert "width:" in swatch, (
        "the entry stands in for a color bar, so it needs a bar's width "
        "rather than a chip's")


def test_both_entry_points_build_one_viz(lapse):
    """``addWindLayer`` and ``addWindTimeLapse`` share ``_wind_vizzes``.

    Two copies of the particle dict would not throw when they diverged.
    Pinning it here is what makes the sharing a contract rather than a
    coincidence of the moment.
    """
    Map, _, _, wx = lapse
    _speed_viz, particle_viz = wx._wind_vizzes({"units": "kt", "min": 0,
                                                "max": 60})
    viz = Map.calls[0]["viz"]
    # classLegendDict is deliberately extended with the ramp, and
    # canQuery deliberately flipped; everything else must match.
    for key, value in particle_viz.items():
        if key in ("classLegendDict", "canQuery"):
            continue
        assert viz[key] == value, key


# ---------------------------------------------------------------------------
# groupWindLayers: the plain layer works the same way
# ---------------------------------------------------------------------------


def _plain(monkeypatch, **kw):
    """Run addWindLayer against fakes and hand back the Map's calls."""
    import geeViz.weather as wx

    monkeypatch.setattr(wx.ee, "Image", lambda x: x)
    monkeypatch.setattr(wx.ee, "ImageCollection", lambda x: x)
    monkeypatch.setattr(wx, "windImage",
                        lambda img, viz: _FakeCollection([], "speed"))
    monkeypatch.setattr(wx, "windTiles",
                        lambda img, viz: _FakeCollection([], "tiles"))

    class _M:
        def __init__(self):
            self.calls = []

        def addLayer(self, item, viz, name, visible):
            self.calls.append({"item": item, "viz": viz, "name": name,
                               "visible": visible})

    Map = _M()
    wx.addWindLayer(Map, _FakeImage("img"), {"units": "kt", "min": 0,
                                             "max": 60}, "W", **kw)
    return Map, wx


def test_a_plain_wind_layer_is_grouped_by_default(monkeypatch):
    """groupWindLayers defaults to True, so a single-frame wind layer
    gets the same one-layer treatment the lapse does: one entry, one
    tile set, two independent opacity controls."""
    Map, wx = _plain(monkeypatch)
    assert len(Map.calls) == 1, (
        f"expected one layer, got {[c['name'] for c in Map.calls]}")
    assert Map.calls[0]["name"] == "W"
    viz = Map.calls[0]["viz"]
    assert viz["windSpeedRaster"] is True
    assert viz["windParticles"] is True
    assert viz["canQuery"] is True
    assert viz["windQueryItem"] == "SERIALIZED:speed", (
        "the query is not pointed at the speed image")
    assert len(viz["classLegendDict"]) == 1


def test_grouping_can_be_turned_off(monkeypatch):
    """The two-layer arrangement is still reachable. It is the one thing
    grouping gives up: there, the speed raster is rendered by Earth
    Engine rather than by the client."""
    Map, wx = _plain(monkeypatch, groupWindLayers=False)
    assert [c["name"] for c in Map.calls] == ["W speed", "W particles"]
    assert "windSpeedRaster" not in Map.calls[1]["viz"]


def test_an_ungrouped_lapse_is_still_two_lapses(monkeypatch):
    """Same escape hatch on the time lapse."""
    import geeViz.weather as wx

    monkeypatch.setattr(wx.ee, "Image", lambda x: x)
    monkeypatch.setattr(wx.ee, "ImageCollection", lambda x: x)
    monkeypatch.setattr(wx, "windImage",
                        lambda img, viz: _FakeImage("speed:" + img.name))
    monkeypatch.setattr(wx, "windTiles",
                        lambda img, viz: _FakeImage("tiles:" + img.name))
    Map = _FakeMap()
    src = _FakeCollection([_FakeImage("h0", {"system:time_start": TIMES[0]})])
    wx.addWindTimeLapse(Map, src, {}, "W", groupWindLayers=False)
    assert [c["name"] for c in Map.calls] == ["W speed", "W particles"]


def test_both_grouped_paths_build_one_viz(monkeypatch):
    """addWindLayer and addWindTimeLapse share ``_merged_viz``.

    Two copies of the merged dict would not throw when they diverged --
    they would yield a layer whose query, legend or ramp quietly
    disagreed with the other entry point's.
    """
    import inspect

    import geeViz.weather as wx
    for fn in (wx.addWindLayer, wx.addWindTimeLapse):
        assert "_merged_viz(" in inspect.getsource(fn), fn.__name__
