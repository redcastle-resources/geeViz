"""``testLayers`` / ``exportLayerJson`` / ``previewMap`` on a wind layer.

``addWindLayer`` adds TWO layers through the ordinary ``Map.addLayer``
path, so all three tools work on it with no special casing:

* **speed** -- a normal single-band raster. Exports and previews like
  any other layer, and is the one to reach for when you want the
  numbers.
* **particles** -- the u/v components encoded as RGB (red = u,
  green = v, blue constant). The animated canvas is a browser-side
  OverlayView and is not a layer at all; this tile layer is what feeds
  it, and it is what the tools see.

That second one is the part worth pinning. Previewing it gives the
ENCODING rather than a picture of particles, which is the simple and
honest thing for it to do -- but it means a reader seeing pastel
red/green noise needs to know that is correct, and it means the blue
channel carrying no information is a contract, not an accident.
"""
import datetime
import json
import os
import tempfile

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
PAST_A = (NOW - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
PAST_B = (NOW - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


@pytest.fixture
def wind_map():
    """A cleared Map carrying exactly one wind layer (so, two layers).

    Function-scoped ON PURPOSE. ``gv.Map`` is a module-level singleton,
    so a module-scoped fixture hands every test the same object and the
    broken-layer test below clears it out from under the others.
    """
    import geeViz.geeView as gv
    import geeViz.weather as wx
    ee = gv.ee
    Map = gv.Map
    Map.clearMap()
    img = ee.Image(wx.getForecastData(PAST_A, PAST_B, "gfs").first())
    Map.addWindLayer(img, {"units": "km/hr"}, "Wind")
    return Map


def _names(Map):
    return [d.get("name") for d in Map.idDictList]


def test_a_wind_layer_is_two_ordinary_layers(wind_map):
    """Not a special case anywhere. If either half stopped going
    through Map.addLayer, it would drop out of all three tools at once
    and none of them would say so."""
    assert _names(wind_map) == ["Wind speed", "Wind particles"]
    for d in wind_map.idDictList:
        assert d.get("_ee_obj") is not None, (
            f"{d.get('name')} has no _ee_obj — testLayers, "
            f"exportLayerJson and previewMap all key off it")
        assert d.get("function") == "addSerializedLayer"


def test_testlayers_passes_on_a_wind_layer(wind_map):
    r = wind_map.testLayers()
    by = {L["name"]: L for L in r["layers"]}
    for n in ("Wind speed", "Wind particles"):
        assert by[n]["status"] == "ok", (n, by[n].get("error"))
    assert r["pass"] is True, r


def test_testlayers_catches_a_BROKEN_wind_layer():
    """Otherwise the test above proves only that the tool returns True.

    ``addWindLayer`` takes the first TWO bands by position, so a
    one-band image is a real and easy mistake -- and the failure shows
    up at tile time, which is exactly what testLayers exists to find
    without launching a browser.
    """
    import geeViz.geeView as gv
    ee = gv.ee
    Map = gv.Map
    Map.clearMap()
    Map.addWindLayer(ee.Image(1).rename("only_one"), {}, "Broken wind")
    r = Map.testLayers()
    assert r["pass"] is False
    for L in r["layers"]:
        assert L["status"] == "error", L
        assert "band" in (L["error"] or "").lower(), L["error"]
    Map.clearMap()


def test_exportlayerjson_includes_both_halves(wind_map):
    """The speed raster is the exportable half — it carries the numbers.
    The particle tiles export too, as the encoding they are."""
    with tempfile.TemporaryDirectory() as d:
        res = wind_map.exportLayerJson(filename="wind.json", output_dir=d)
        assert res["layer_count"] == 2, res
        assert res["layer_names"] == ["Wind speed", "Wind particles"], res
        assert not res["skipped"], res["skipped"]
        blob = json.load(open(os.path.join(d, "wind.json")))
        assert blob["layer_count"] == 2
        # layers is keyed BY NAME, each entry carrying the serialized ee
        # object and the viz it was added with.
        assert set(blob["layers"]) == {"Wind speed", "Wind particles"}
        for name, entry in blob["layers"].items():
            assert entry["serialized"], f"{name} exported with no ee object"
            assert isinstance(entry["viz"], dict), name
        # The speed half is the one carrying numbers, so its viz must
        # still say which band and what stretch -- that is what makes
        # the export reproducible rather than merely present.
        speed_viz = blob["layers"]["Wind speed"]["viz"]
        assert speed_viz.get("bands") == "speed", speed_viz
        assert "min" in speed_viz and "max" in speed_viz, speed_viz


def test_previewmap_renders_both_halves(wind_map):
    out = wind_map.previewMap(grid_size=2, zoom=3)
    assert set(out["layers"]) == {"Wind speed", "Wind particles"}
    for name, png in out["layers"].items():
        assert png[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG"
        assert len(png) > 5000, f"{name} rendered {len(png)} bytes — blank?"


def test_the_particle_preview_is_the_uv_encoding(wind_map):
    """Red carries u, green carries v, blue carries nothing.

    Asserted on the rendered pixels, because this is the one preview
    that does NOT look like its layer name and someone will eventually
    'fix' it. The blue channel being flat is the tell: it exists only
    because ``visualize`` wants three bands.
    """
    PIL = pytest.importorskip("PIL.Image")
    import io as _io
    out = wind_map.previewMap(grid_size=2, zoom=3)
    im = PIL.open(_io.BytesIO(out["layers"]["Wind particles"])).convert("RGB")
    px = list(im.getdata())

    def _spread(i):
        v = [p[i] for p in px]
        return max(v) - min(v)

    r, g, b = _spread(0), _spread(1), _spread(2)
    # Compared, not thresholded absolutely: blue is a CONSTANT band in
    # the data, but the preview is a resampled, compressed PNG, so it
    # arrives as a narrow smear around the encoded zero (~127) rather
    # than a single value. Measured here: r 95, g 117, b 26.
    assert r > 40, f"red (u) spans only {r} — that is not a wind field"
    assert g > 40, f"green (v) spans only {g} — that is not a wind field"
    assert b < min(r, g) / 2, (
        f"blue spans {b} against r={r} g={g}; it is the constant filler "
        f"band that exists only because visualize wants three, so "
        f"something real is now encoded there")

    # And the constant sits where the encoding puts zero.
    import geeViz.weather as wx
    mid = [p[2] for p in px]
    zero = (0 - wx.WIND_TILE_MIN_MS) / (
        wx.WIND_TILE_MAX_MS - wx.WIND_TILE_MIN_MS) * 255
    assert abs(sum(mid) / len(mid) - zero) < 20, (
        f"blue averages {sum(mid)/len(mid):.0f}, not the {zero:.0f} that "
        f"0 maps to under the WIND_TILE stretch")
