"""The u/v tile stretch must be identical in Python and JavaScript.

Earth Engine renders the wind components into the red and green channels
of ordinary PNG tiles, linearly stretched from a fixed m/s range onto
0..255; the browser inverts that stretch to recover the numbers. Both
sides must use the SAME range.

A mismatch does not raise. It yields wind that is wrong by a scale
factor and an offset -- which still looks like weather, still animates,
and still flows plausibly around terrain. There is no symptom to notice,
which is exactly why it is pinned here.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "geeViz" / "geeView" / "src" / "js" / "wind-particles.js"


def _js_const(name):
    src = JS.read_text(encoding="utf-8")
    # Strip comments first: the file explains the constants at length,
    # and this repo's tests have repeatedly matched their own prose.
    code = "\n".join(
        ln for ln in src.splitlines()
        if not ln.lstrip().startswith(("*", "//", "/*"))
    )
    m = re.search(r"\bvar\s+" + name + r"\s*=\s*(-?[0-9.]+)", code)
    assert m, f"{name} not found in {JS.name}"
    return float(m.group(1))


def test_the_client_reads_the_stretch_from_viz():
    """Python is the single source of truth for the stretch.

    Both halves existed for a while and only one was live: weather.py
    sent windTileMin/windTileMax in viz, and the JS ignored them in
    favour of its own constants. That is a mismatch waiting to happen,
    and a mismatch does not throw -- it yields winds wrong by a scale
    and an offset, which still look like weather.
    """
    src = JS.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith(("*", "//", "/*")))
    assert "windTileMin" in code and "windTileMax" in code, (
        "the client must take the stretch from viz, not only from its "
        "own constants")
    # The cfg KEYS must exist, not merely the expressions that feed them.
    # Renaming `tileMin:` to anything else leaves `windTileMin` in the
    # source and `cfg.tileMin` in sampleUV, both assertions still true,
    # while the decode silently reads undefined and yields NaN.
    for key in ("tileMin", "tileMax"):
        assert re.search(r"\b" + key + r"\s*:", code), (
            f"cfg has no {key} key — sampleUV would read undefined")
    # And the decode must USE those, not the module fallbacks. The
    # decode lives in pixelUV -- sampleUV interpolates between four of
    # its results and no longer touches the byte values itself.
    body = _strip_js_comments(_js_fn_body("pixelUV"))
    assert "cfg.tileMin" in body and "cfg.tileMax" in body, (
        "pixelUV still decodes with the hard-coded fallback")


def test_the_decoder_reads_red_then_green():
    """u out of red, v out of green — the order the encoder wrote.

    The encoder's order is pinned elsewhere; this pins the other half.
    Swapping the two here rotates every vector by 90 degrees, and a
    rotated wind field still looks like a wind field: particles still
    stream, still curl around terrain, still look plausible. Nothing
    would report it.
    """
    body = _strip_js_comments(_js_fn_body("pixelUV"))
    m = re.search(r"return\s*\[\s*lo\s*\+\s*\(data\[(i[^\]]*)\]", body)
    assert m, "could not find the decode return in pixelUV"
    assert m.group(1).strip() == "i", (
        f"u is decoded from data[{m.group(1)}]; red is data[i]")
    m2 = re.search(r"lo\s*\+\s*\(data\[i \+ 1\]", body)
    assert m2, "v must be decoded from data[i + 1] (green)"
    # sampleUV must pass them through in order, not swap them.
    samp = _strip_js_comments(_js_fn_body("sampleUV"))
    assert "return [uv[0], uv[1]," in samp, (
        "sampleUV reorders u and v, which rotates every vector 90 "
        "degrees while still looking like a wind field")


def test_the_fallback_matches_python():
    import geeViz.weather as wx
    assert _js_const("TILE_MIN") == wx.WIND_TILE_MIN_MS, (
        "the JS fallback TILE_MIN disagrees with weather.WIND_TILE_MIN_MS "
        "— only reached when viz lacks the value, but wrong there too")
    assert _js_const("TILE_MAX") == wx.WIND_TILE_MAX_MS, (
        "wind-particles.js TILE_MAX disagrees with weather.WIND_TILE_MAX_MS "
        "— decoded winds will be wrong by a scale factor, silently")


def test_the_stretch_covers_real_winds():
    """Values outside the range clamp, so the range has to be wide enough
    that clamping never happens in practice. 40 m/s is ~145 km/h."""
    import geeViz.weather as wx
    assert wx.WIND_TILE_MIN_MS <= -35 and wx.WIND_TILE_MAX_MS >= 35


def test_quantization_is_finer_than_the_forecast():
    """8 bits over the range. If this ever gets coarse enough to see, the
    range grew too wide."""
    import geeViz.weather as wx
    step = (wx.WIND_TILE_MAX_MS - wx.WIND_TILE_MIN_MS) / 255.0
    assert step < 0.5, f"{step:.3f} m/s per level is too coarse"


def test_python_encodes_into_red_and_green():
    """Order matters: u in red, v in green. Swapping them rotates every
    vector by 90 degrees, which still looks like a wind field."""
    import inspect
    import geeViz.weather as wx
    src = inspect.getsource(wx.windTiles)
    m = re.search(r'bands=\[([^\]]+)\]', src)
    assert m, "no visualize(bands=...) call"
    assert [b.strip().strip('"\'') for b in m.group(1).split(",")] == ["u", "v", "z"]


def test_default_stretch_follows_the_unit():
    """A 0..15 stretch read as km/h paints the map one flat colour."""
    import geeViz.weather as wx
    d = wx.DEFAULT_MAX_SPEED
    assert set(d) == set(wx.SPEED_UNITS)
    for unit, mult in wx.SPEED_UNITS.items():
        # Each default should be the same physical wind, give or take.
        assert abs(d[unit] / mult - d["m/s"]) < 2.0, (
            f"{unit} default {d[unit]} is not ~{d['m/s']} m/s")


# ── the stretch must always reach the client ───────────────────────────

def test_addlayer_always_stamps_the_stretch():
    """Any wind-particle layer leaves geeViz carrying the tile stretch.

    Not just the ones built by weather.addWindLayer. The browser cannot
    decode the u/v tiles without knowing the range they were encoded
    with, and if it falls back to its own copy the two can drift —
    silently, because the result is still a plausible-looking wind.
    """
    import json
    import geeViz.geeView as gv
    import geeViz.weather as wx

    Map = gv.mapper()
    # A hand-rolled particle layer that does NOT pass the stretch.
    img = gv.ee.Image.constant([1, 2, 0]).rename(["u", "v", "z"]).toFloat()
    Map.addLayer(img, {"windParticles": True}, "hand rolled", True)

    stamped = [json.loads(d["viz"]) for d in Map.idDictList if d.get("name")]
    assert stamped, "no layer was registered"
    v = stamped[0]
    assert v["windTileMin"] == wx.WIND_TILE_MIN_MS
    assert v["windTileMax"] == wx.WIND_TILE_MAX_MS


def test_an_explicit_stretch_is_not_overwritten():
    """setdefault, not assignment: a caller who deliberately encoded a
    different range must keep it, or their tiles decode wrongly."""
    import json
    import geeViz.geeView as gv

    Map = gv.mapper()
    img = gv.ee.Image.constant([1, 2, 0]).rename(["u", "v", "z"]).toFloat()
    Map.addLayer(img, {"windParticles": True,
                       "windTileMin": -25.0, "windTileMax": 25.0},
                 "custom stretch", True)
    v = json.loads([d for d in Map.idDictList if d.get("name")][0]["viz"])
    assert v["windTileMin"] == -25.0 and v["windTileMax"] == 25.0


def test_ordinary_layers_are_not_stamped():
    """The keys are meaningless on a normal layer and would be noise in
    every serialized viz dict."""
    import json
    import geeViz.geeView as gv

    Map = gv.mapper()
    img = gv.ee.Image.constant(1).rename(["b1"]).toFloat()
    Map.addLayer(img, {"min": 0, "max": 1}, "ordinary", True)
    v = json.loads([d for d in Map.idDictList if d.get("name")][0]["viz"])
    assert "windTileMin" not in v and "windTileMax" not in v


# ── particle count scales with zoom ────────────────────────────────────

def _strip_js_comments(src):
    """Drop // and /* */ comments.

    Source assertions that match their own explanatory comments pass
    vacuously — and worse, an assertion that a construct is ABSENT fails
    the moment a comment explains why it was removed, which is exactly
    what happened to the ``destination-in`` check here. String literals
    are left alone; this only has to be right for this one file.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def test_the_comment_stripper_works():
    """A stripper that silently does nothing turns every source
    assertion below into a tautology."""
    assert _strip_js_comments("a // b\nc") == "a \nc"
    assert _strip_js_comments("a /* b */ c") == "a  c"
    assert _strip_js_comments("/* x */") == ""
    assert _strip_js_comments("keep") == "keep"
    assert "destination-in" not in _strip_js_comments(
        "/* the destination-in fade */ x")


def _js_fn_body(name):
    """The whole function body, brace-matched.

    A fixed-length slice silently truncates: the 900-character window
    this used to take stopped short of ``frame()``'s stroke loop, so an
    assertion about it reported "0 occurrences" and read as a real
    regression rather than as a short window.
    """
    src = JS.read_text(encoding="utf-8")
    i = src.index("function " + name)
    start = src.index("{", i)
    depth, j = 0, start
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading " + name)


def test_each_particle_gets_its_own_lifetime():
    """Trail length is how much history the fade still shows, so a young
    particle draws a stub and a mature one draws a full streak.

    With a single shared ``cfg.maxAge`` nearly every particle sits in
    the mature part of its life at any instant and the field renders as
    one uniform comb — which is exactly how it looked next to windy.com.
    The lifetime has to be PER PARTICLE for short and long streaks to
    coexist.
    """
    body = _js_fn_body("respawn")
    assert "p.maxAge = cfg.minAge + Math.random() * (cfg.maxAge - cfg.minAge)" in body, (
        "respawn no longer draws a per-particle lifetime — every trail "
        "will mature to the same length")
    src = JS.read_text(encoding="utf-8")
    assert "if (p.age > cfg.maxAge)" not in src, (
        "the age check still compares against the SHARED maxAge, so the "
        "per-particle lifetime is computed and then ignored")
    assert src.count("p.age > p.maxAge") == 2, (
        "both age checks (no-data and normal advection) must use the "
        "particle's own lifetime")


def test_initial_ages_are_staggered():
    """Otherwise the whole field is born together, dies together, and
    the map visibly pulses once per lifetime."""
    body = _js_fn_body("respawn")
    assert "randomAge ? Math.random() * p.maxAge : 0" in body


def test_python_sends_the_lifetime_range():
    """The client defaults are a fallback, not the contract — geeViz
    stamps both ends so the viewer does not have to guess."""
    import geeViz.weather as wx
    sent = {}

    class FakeMap:
        def addLayer(self, image, viz=None, name=None, visible=True):
            sent[name] = viz or {}

    import ee
    img = ee.Image([1, 2]).rename(["u", "v"])
    wx.addWindLayer(FakeMap(), img, {}, "W", True)
    particles = [v for k, v in sent.items() if "particle" in k.lower()
                 or "particles" in (k or "")]
    assert particles, f"no particle layer was added; got {list(sent)}"
    v = particles[0]
    assert v["particleMaxAge"] == 90
    assert v["particleMinAge"] == 22.5, (
        f"particleMinAge is {v.get('particleMinAge')!r}; without it the "
        f"client falls back and the range is never actually chosen here")


def test_setting_max_age_moves_the_min_with_it():
    """``particleMinAge`` defaults to a QUARTER of whatever max is in
    effect. A user who only raises the max should get proportionally
    longer streaks, not a range that silently widens to the old
    fraction of 90."""
    import ee
    import geeViz.weather as wx
    sent = {}

    class FakeMap:
        def addLayer(self, image, viz=None, name=None, visible=True):
            sent[name] = viz or {}

    img = ee.Image([1, 2]).rename(["u", "v"])
    wx.addWindLayer(FakeMap(), img, {"particleMaxAge": 200}, "W", True)
    v = [x for k, x in sent.items() if x.get("particleMaxAge")][0]
    assert v["particleMinAge"] == 50.0, (
        f"min is {v['particleMinAge']} for a max of 200 — it did not "
        f"track the max")


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------


def _js_literal_defaults():
    """Every ``particleX`` default in ``cfgFrom`` that is a literal.

    Two forms appear: ``v.particleX || 4000`` and
    ``v.particleX !== undefined ? v.particleX : 7``. Defaults derived
    from another value (``weight * 0.45``) are deliberately skipped —
    they are checked by relationship instead.
    """
    import re as _re
    src = _strip_js_comments(_js_fn_body("cfgFrom"))
    out = {}
    pat = (r"v\.(particle[A-Za-z]+)\s*(?:\|\|\s*|"
           r"!== undefined\s*\?\s*v\.particle[A-Za-z]+\s*:\s*)"
           r"(-?[\d.]+|\"[a-z]+\")")
    for name, raw in _re.findall(pat, src):
        out[name] = raw.strip('"') if raw.startswith('"') else float(raw)
    return out


def _stamped_viz():
    import ee
    import geeViz.weather as wx
    sent = {}

    class FakeMap:
        def addLayer(self, image, viz=None, name=None, visible=True):
            sent[name] = viz or {}

    wx.addWindLayer(FakeMap(), ee.Image([1, 2]).rename(["u", "v"]), {}, "W")
    return [x for x in sent.values() if x.get("windParticles")][0]


def test_every_client_default_matches_what_python_sends():
    """Two copies of the same numbers, checked wholesale rather than by
    a hand-picked list.

    geeViz stamps all of these onto the layer, so a client fallback that
    disagreed would only show up for a hand-built layer — the hardest
    case to notice. The earlier version of this test named five keys
    explicitly and silently stopped covering the rest as the set grew.
    """
    js = _js_literal_defaults()
    assert len(js) >= 12, (
        f"only parsed {len(js)} defaults out of cfgFrom — the parser has "
        f"drifted from the source and is no longer checking anything")
    viz = _stamped_viz()
    missing, wrong = [], []
    for key, default in js.items():
        if key == "particleLineWidth":
            continue          # back-compat alias, resolved in Python
        if key not in viz:
            missing.append(key)
        elif isinstance(default, float):
            if abs(float(viz[key]) - default) > 1e-9:
                wrong.append(f"{key}: python={viz[key]} client={default}")
        elif viz[key] != default:
            wrong.append(f"{key}: python={viz[key]!r} client={default!r}")
    assert not missing, f"python never sends: {missing}"
    assert not wrong, "defaults drifted — " + "; ".join(wrong)


def test_derived_sizes_track_their_base():
    """``particleMinSize`` / ``particleMaxSize`` default to fractions of
    ``particleStrokeWeight``, so raising the weight alone rescales the
    whole taper instead of leaving a half-scaled one. Same contract as
    ``particleMinAge`` tracking ``particleMaxAge``."""
    import ee
    import geeViz.weather as wx
    sent = {}

    class FakeMap:
        def addLayer(self, image, viz=None, name=None, visible=True):
            sent[name] = viz or {}

    img = ee.Image([1, 2]).rename(["u", "v"])
    wx.addWindLayer(FakeMap(), img, {"particleStrokeWeight": 4.0}, "W")
    v = [x for x in sent.values() if x.get("windParticles")][0]
    assert v["particleMinSize"] == 4.0 * 0.45
    assert v["particleMaxSize"] == 4.0 * 1.5
    assert v["particleMinSize"] < v["particleMaxSize"], (
        "a comet is thin at the tail and fat at the tip")

    # the old name still works
    sent.clear()
    wx.addWindLayer(FakeMap(), img, {"particleLineWidth": 3.0}, "W")
    v = [x for x in sent.values() if x.get("windParticles")][0]
    assert v["particleStrokeWeight"] == 3.0, (
        "particleLineWidth is the old name for particleStrokeWeight and "
        "must keep working")

    # and an explicit size wins over the derived one
    sent.clear()
    wx.addWindLayer(FakeMap(), img,
                    {"particleStrokeWeight": 4.0, "particleMaxSize": 9.0}, "W")
    v = [x for x in sent.values() if x.get("windParticles")][0]
    assert v["particleMaxSize"] == 9.0


def test_the_size_ramp_is_used_in_frame():
    """Configured is not applied. The width must interpolate minSize to
    maxSize across the trail — the head then needs no special case,
    because at t = 1 it already IS maxSize."""
    body = _strip_js_comments(_js_fn_body("frame"))
    assert "cfg.minSize + (cfg.maxSize - cfg.minSize) * t" in body, (
        "frame() does not ramp the width between the configured sizes")
    assert "cfg.lineCap" in body, "particleLineCap is configured but unused"


def test_wind_palette_is_windys_legend():
    """Read off windy.com's own legend so a geeViz wind map and a windy
    map of the same hour are comparable at a glance. Pinned as RGB
    because that is the form the legend publishes."""
    import geeViz.geeView as gv
    import geeViz.weather as wx
    expected = [(61, 110, 163), (74, 148, 170), (74, 146, 148),
                (77, 142, 124), (76, 164, 76), (103, 164, 54),
                (162, 135, 64), (162, 109, 92), (141, 63, 92),
                (151, 75, 145), (95, 100, 160), (91, 136, 161),
                (91, 136, 161)]
    assert list(wx.WIND_PALETTE) == [gv.RGB_to_hex(list(c)) for c in expected]
    assert wx.DEFAULT_SPEED_PALETTE is wx.WIND_PALETTE, (
        "an unconfigured wind layer must paint with the windy ramp")


def test_local_hex_matches_geeviz_rgb_to_hex():
    """``weather`` converts colours locally rather than importing the
    viewer, because ``geeView`` imports ``weather`` to serve
    ``Map.addWindLayer`` — a top-level import back would make the cycle
    depend on which module the user happened to import first. Local, but
    it must agree."""
    import geeViz.geeView as gv
    import geeViz.weather as wx
    for c in [(0, 0, 0), (255, 255, 255), (61, 110, 163), (7, 8, 9)]:
        assert wx._hex(c) == gv.RGB_to_hex(list(c))


def test_precip_and_temperature_palettes_are_present():
    """Same source, so a multi-variable weather map is coherent."""
    import geeViz.weather as wx
    assert len(wx.PRECIP_PALETTE) == 9
    assert len(wx.TEMPERATURE_PALETTE) == 13
    for pal in (wx.WIND_PALETTE, wx.PRECIP_PALETTE, wx.TEMPERATURE_PALETTE):
        for c in pal:
            assert re.fullmatch(r"#[0-9a-f]{6}", c), c


# ---------------------------------------------------------------------------
# The agent can actually reach any of this.
# ---------------------------------------------------------------------------


def test_weather_is_bound_in_the_run_code_namespace():
    """A library the agent cannot import is a library that does not
    exist. ``wx`` has to be BOUND, not merely importable — the sandbox
    namespace is what ``run_code`` executes against."""
    src = (ROOT / "geeViz" / "mcp" / "server.py").read_text(encoding="utf-8")
    assert "import geeViz.weather as wx" in src
    assert '"wx": wx,' in src and '"weather": wx,' in src, (
        "both spellings, so search_codebase resolves whichever the "
        "agent tries")


def test_the_agent_instructions_cover_wind_layers():
    """Docstrings reach the agent through search_codebase, but only if
    it knows to look. The instructions are what send it there."""
    md = (ROOT / "geeViz" / "mcp" /
          "agent-instructions.md").read_text(encoding="utf-8")
    for needle in ("Map.addWindLayer", "wx.getForecastData",
                   'search_codebase(module="weather")', "WIND_PALETTE"):
        assert needle in md, f"agent instructions never mention {needle}"


def test_every_particle_param_is_documented():
    """Documented in all three places, checked against the real set.

    Driven from the viz dict ``addWindLayer`` actually stamps, so adding
    a knob without documenting it fails here rather than shipping an
    undiscoverable parameter. Naming the places explicitly because each
    reaches a different audience: the docstring is what
    ``search_codebase`` serves the agent, the instructions are what tell
    it to look, and the notebook is what a person reads.
    """
    import geeViz.weather as wx
    params = sorted(k for k in _stamped_viz() if k.startswith("particle"))
    assert len(params) >= 18, (
        f"only {len(params)} particle params found — the introspection "
        f"has drifted and this test is no longer checking much")

    doc = wx.addWindLayer.__doc__
    md = (ROOT / "geeViz" / "mcp" /
          "agent-instructions.md").read_text(encoding="utf-8")
    nb = (ROOT / "geeViz" / "examples" /
          "weather_forecast_examples.ipynb").read_text(encoding="utf-8")

    for where, text in (("addWindLayer docstring", doc),
                        ("agent-instructions.md", md),
                        ("weather_forecast_examples.ipynb", nb)):
        missing = [p for p in params if p not in text]
        assert not missing, f"{where} does not mention: {missing}"


def test_the_units_caveat_travels_with_the_speed_bounds():
    """``particleMinSpeed`` / ``particleMaxSpeed`` change APPARENT speed
    only. Anywhere they are documented has to say so, or someone will
    read a streak length as a wind speed — the raster and the click
    query are the numbers, the streaks are not.
    """
    import geeViz.weather as wx
    md = (ROOT / "geeViz" / "mcp" /
          "agent-instructions.md").read_text(encoding="utf-8")
    for where, text in (("addWindLayer docstring", wx.addWindLayer.__doc__),
                        ("agent-instructions.md", md)):
        # Collapse whitespace first: these phrases straddle a line wrap
        # in the docstring, and a docs test that fails whenever a
        # paragraph is rewrapped teaches people to delete the test.
        low = " ".join(text.lower().split())
        assert "direction is untouched" in low or "direction is preserved" in low, (
            f"{where}: the speed bounds are documented without saying "
            f"direction survives them")
        assert "true value" in low, (
            f"{where}: nothing says the raster and query still carry the "
            f"true speed")


def _streak_px(wind_ms, zoom=7, lat=29.0):
    """Screen length of one streak, from the client's own constants.

        max(min(speed, maxSpeed), minSpeed)
          * speedFactor * 2 ** (zoomRef - zoom)
          / metresPerPixel
          * trailLength

    The ``2 ** (zoomRef - zoom)`` term is what keeps this independent of
    zoom; without it the length doubled per level.
    """
    import math
    import re as _re
    src = _strip_js_comments(JS.read_text(encoding="utf-8"))

    def num(pat):
        m = _re.search(pat, src)
        assert m, f"could not find {pat!r} in the client source"
        return float(m.group(1))

    speed = num(r"speedFactor: v\.particleSpeedFactor \|\| ([\d.]+)")
    # buildField computes `advance = speedFactor * 2**(zoomRef - zoom)`
    # once per view; the exponent is what holds screen length constant.
    length = num(r"v\.particleTrailLength \|\| ([\d.]+)")
    floor = num(r"v\.particleMinSpeed !== undefined \? v\.particleMinSpeed : ([\d.]+)")
    ceil_ = num(r"v\.particleMaxSpeed !== undefined \? v\.particleMaxSpeed : ([\d.]+)")
    ref = num(r"v\.particleZoomRef !== undefined \? v\.particleZoomRef : ([\d.]+)")

    mpp = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)
    bounded = min(max(wind_ms, floor), ceil_)
    return (bounded * speed * (2 ** (ref - zoom)) / mpp) * length


def test_streak_length_is_the_same_at_every_zoom():
    """Zooming in must not stretch the streaks.

    The step is computed in DEGREES, which is zoom-invariant on the
    ground -- but what you see is ``step / metresPerPixel``, and
    metres-per-pixel halves with every zoom level. So a fixed ground
    step doubled in screen length per level: 9 px at z5 against 591 px
    at z11 for the same 4 m/s wind, a 64x blowup that turned a
    zoomed-in view into a white smear. The particle count falls only
    ~3x across that range, nowhere near enough to hide it.
    """
    lengths = {z: _streak_px(4.0, zoom=z) for z in range(4, 13)}
    lo, hi = min(lengths.values()), max(lengths.values())
    assert hi - lo < 1e-6, (
        "streak length varies with zoom: "
        + ", ".join(f"z{z}={v:.0f}px" for z, v in sorted(lengths.items())))
    # And the fast case must not run away either -- that is the smear.
    fast = {z: _streak_px(60.0, zoom=z) for z in range(4, 13)}
    assert max(fast.values()) - min(fast.values()) < 1e-6


def test_trails_are_long_enough_to_read_as_streaks():
    """Readable at the calm end, bounded at the violent end.

    Length used to be an emergent property of a canvas fade, which gave
    FIVE pixels for an ordinary 4 m/s wind -- a scatter of dots, not a
    flow field. The speed floor is what fixes the low end: without it
    length is strictly proportional to speed, so a calm map is
    indistinguishable from a broken one.
    """
    # A dead-calm cell must still draw something readable...
    assert _streak_px(0.5) > 10, (
        f"a 0.5 m/s cell draws {_streak_px(0.5):.1f}px — the minSpeed "
        f"floor is not holding the low end up")
    # ...an ordinary breeze a clear streak...
    assert 20 < _streak_px(4.0) < 60, f"4 m/s gives {_streak_px(4.0):.1f}px"
    # ...and a hurricane must stay on the screen.
    assert _streak_px(80.0) < 500, (
        f"80 m/s gives {_streak_px(80.0):.1f}px — the maxSpeed ceiling "
        f"is not bounding the violent end")


def test_the_head_is_brighter_than_the_tail():
    """The comet shape. Ranks are stroked oldest-first at
    ``opacity * t^taper``, and the newest gets ``headBoost``.

    A single multiplicative canvas fade cannot do this: one slow enough
    to leave a long trail is nearly flat across its first twenty frames
    (0.965^20 = 0.49), so the streak reads as a uniform bar. That was
    the whole reason for keeping an explicit history.
    """
    import re as _re
    src = _strip_js_comments(JS.read_text(encoding="utf-8"))
    # Scoped to frame(): refreshRunState also clears the canvas when a
    # layer is switched off, so asserting against the whole file passed
    # even with the per-frame clear deleted.
    body = _strip_js_comments(_js_fn_body("frame"))
    assert "ctx.clearRect(0, 0, st.w, st.h);" in body, (
        "frame() must clear the canvas — an accumulate-and-fade canvas "
        "cannot produce a bright head")
    assert "destination-in" not in src, (
        "the old fade is back; it and the explicit history are two "
        "different trail models and must not both run")
    taper = float(_re.search(
        r"v\.particleTaper !== undefined \? v\.particleTaper : ([\d.]+)",
        src).group(1))
    boost = float(_re.search(
        r"v\.particleHeadBoost !== undefined \? v\.particleHeadBoost : ([\d.]+)",
        src).group(1))
    assert taper > 1.0, (
        f"taper {taper} is linear or inverted — the fade must stretch "
        f"toward the tail for the shape to read as a comet")
    assert boost > 1.0, f"headBoost {boost} does not brighten the head"

    # The alpha ramp itself: tail near nothing, head at full.
    opacity, n = 0.9, 26
    tail = opacity * (1 / (n - 1)) ** taper
    mid = opacity * (0.5) ** taper
    head = min(1.0, opacity * boost)
    assert tail < 0.02, f"tail alpha {tail:.3f} is still visible"
    assert head / mid > 4, (
        f"head is only {head / mid:.1f}x the midpoint — not a comet")


def test_one_stroke_per_rank_not_per_particle():
    """Thousands of individual ``stroke()`` calls is what made the very
    first version stutter, and drawing a full trail per particle would
    reintroduce exactly that. Batching by history rank keeps it at
    ``trailLength`` strokes per frame regardless of particle count."""
    body = _strip_js_comments(_js_fn_body("frame"))
    assert body.count("ctx.stroke()") == 1, (
        "more than one stroke() in frame() — it should be one per rank, "
        "inside the rank loop")
    assert "for (var rank = 1; rank < n; rank++)" in body


def test_the_encoded_raster_is_detached_and_stays_detached():
    """Unchecking and re-checking the layer made the RGB reappear.

    The viewer rebuilds the ImageMapType and calls
    ``overlayMapTypes.setAt(...)`` on every visibility change. ``scan()``
    skips anything already adopted, so nothing took it back off and the
    encoding — flat red and green, not a picture — sat on the map.
    Detaching therefore has to run on the refresh tick, not only at
    adoption.
    """
    src = _strip_js_comments(JS.read_text(encoding="utf-8"))
    assert "function detach(L)" in src
    scan = _strip_js_comments(_js_fn_body("scan"))
    assert "detach(L)" in scan, "adoption no longer detaches the raster"
    refresh = _strip_js_comments(_js_fn_body("refreshRunState"))
    # The exact guarded call, not just the symbol: `if (false) detach(L)`
    # keeps the name in the file while doing nothing, and an assertion
    # that only looked for "detach(L)" passed on it.
    assert "if (L) { detach(L); reportProgress(st); }" in refresh, (
        "detach must RUN on the refresh tick, or re-checking the layer "
        "puts the encoded RGB back on the map for good")


def test_tile_progress_is_reported_from_the_real_queue():
    """The layer's loading state must track the tiles actually in flight.

    The viewer sets ``layer.loading = true`` inside its own
    ``getTileUrl`` and clears it when the ImageMapType fires
    ``tilesloaded``. This module calls ``getTileUrl`` directly and has
    taken the map type off the map, so that event never fires — both
    halves are ours, so reporting is too.

    The first fix simply forced ``loading = false`` once. That stopped
    the endless spinner but pinned the layer to "done" forever: panning
    to fresh ground fetches a new batch and the status bar showed
    nothing. Derived from the in-flight count, it falls off 100 on a pan
    and climbs back as the batch lands.
    """
    src = _strip_js_comments(JS.read_text(encoding="utf-8"))
    assert "function settleSpinner" not in src, (
        "the one-shot suppressor is back; it pins the layer to 'done' "
        "and a pan never reports loading again")
    assert "function reportProgress(st)" in src

    body = _strip_js_comments(_js_fn_body("reportProgress"))
    assert "var loading = inflight > 0;" in body, (
        "loading must be derived from the queue, not pinned")
    assert "L.percent = percent;" in body and ": 100;" in body, (
        "percent must reach 100 when the queue drains")
    assert "-spinner2" in body, "the spinner element is never toggled"
    assert "-layer-container" in body, (
        "the white progress fill across the layer row is never repainted")
    assert "-webkit-linear-gradient(left, #FFF, #FFF " in body, (
        "the fill must use the viewer's own gradient, or this row looks "
        "unlike every other layer")
    assert "global.updateProgress" not in body, (
        "the viewer's updateProgress is a per-layer CLOSURE; the global "
        "of that name is a different function and calling it did nothing")
    assert "if (loading) sp.show(); else sp.hide();" in body, (
        "the spinner must be shown again on a new batch, not only hidden")
    assert ('if (typeof global.updateGEETileLayersDownloading === "function")'
            in body), (
        "the status-bar counter must be recomputed by the viewer, or "
        "'Number of map layers loading' never returns to zero")


def test_both_tile_outcomes_leave_the_queue():
    """A failed tile must decrement the in-flight count too.

    Counting only successes leaves the layer loading forever the first
    time a tile 404s or is blocked — which is the exact bug class this
    replaced, reintroduced from the other side.
    """
    src = _strip_js_comments(JS.read_text(encoding="utf-8"))
    body = _strip_js_comments(_js_fn_body("getTile"))
    assert body.count("tileStarted(st)") == 1
    assert body.count("tileFinished(st)") == 2, (
        "tileFinished must run on BOTH onload and onerror; "
        f"found {body.count('tileFinished(st)')}")
    assert "img.onerror = function () { st.tiles[key] = false; tileFinished(st); };" in body
    # A URL that never becomes a request must not be counted either.
    assert "catch (e) { st.tiles[key] = false; return null; }" in body, (
        "a getTileUrl that throws must mark the tile dead, or it is "
        "retried forever and never counted")
    fin = _strip_js_comments(_js_fn_body("tileFinished"))
    assert "Math.max(0, (st.inflight || 1) - 1)" in fin, (
        "the in-flight count must not go negative")


def test_adoption_settles_a_probe_set_flag():
    """``findTileUrlFn`` calls the viewer's own ``getTileUrl`` to find
    it, which flips ``loading = true`` as a side effect. A layer that
    then never requests a tile — switched off, say — would spin
    forever."""
    scan = _strip_js_comments(_js_fn_body("scan"))
    assert "reportProgress(st);" in scan, (
        "adoption must settle the flag the URL probe set")


def test_the_tile_zoom_cap_is_applied():
    """Configured is not applied — again.

    Fetching finer tiles than the forecast can resolve buys nothing and
    costs a great deal: at map zoom 10 the viewport needed 35 tiles and
    1559 were requested. GFS is 0.25 deg (~28 km); a zoom-7 tile pixel
    is about 1 km, already 28x finer. Everything past the cap is an
    upsampled duplicate.
    """
    src = _strip_js_comments(JS.read_text(encoding="utf-8"))
    assert "Math.min(st.cfg.maxTileZoom, global.map.getZoom() || 4)" in src, (
        "the tile zoom is no longer clamped to the configured cap — a "
        "zoomed-in view will request hundreds of redundant tiles")
    assert "Math.min(10, global.map.getZoom()" not in src, (
        "the old hard-coded cap is back")


PROBE = Path(__file__).parent / "wind_sampler_probe.js"
FIELD_PROBE = Path(__file__).parent / "wind_field_probe.js"


def _probe_field():
    """Run countFor and fieldAt for real."""
    import json
    import subprocess
    exe = _node()
    if not exe:
        pytest.skip("node not available")
    r = subprocess.run([exe, str(FIELD_PROBE), str(JS)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"field probe failed: {r.stderr[:800]}"
    return json.loads(r.stdout)


def _node():
    """A real Node.js, or None.

    Probed by asking for ``process.versions.node`` rather than trusting
    ``shutil.which`` — on this machine ``which`` has previously turned up
    a WSL relay that answers the name but not the semantics, and a guard
    test that silently skips is worse than one that fails.
    """
    import shutil
    import subprocess
    exe = shutil.which("node")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-e", "process.stdout.write(process.versions.node)"],
                             capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return exe if re.fullmatch(r"\d+\.\d+\.\d+", out.stdout.strip() or "") else None


def _probe():
    import json
    import subprocess
    exe = _node()
    if not exe:
        pytest.skip("node not available")
    r = subprocess.run([exe, str(PROBE), str(JS)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"probe failed: {r.stderr[:800]}"
    return json.loads(r.stdout)


def test_the_sampler_decodes_exactly():
    """Nearest sampling must reproduce the encoder's bytes exactly.

    With no client-side blend, a sample IS a stored byte run back
    through the stretch — so a walk across a synthetic ramp should
    produce a clean staircase whose steps are exactly one byte of the
    stretch, and nothing in between. Anything else means the decode has
    drifted from the encoding.
    """
    d = _probe()
    per = d["perPixel"]
    assert d["maxStep"] <= per + 1e-9, (
        f"a step of {d['maxStep']:.5f} exceeds one byte of the stretch "
        f"({per:.5f}) — the decode does not match the encoding")
    assert d["monotonic"], "a monotonic ramp did not decode monotonically"
    # A staircase, not a ramp: far fewer distinct values than samples.
    assert d["nDistinct"] < d["nSamples"] / 2, (
        f"{d['nDistinct']} distinct values from {d['nSamples']} samples "
        f"— that is interpolated, and the client should not be "
        f"interpolating")


def test_the_sampler_returns_magnitude_and_stays_in_range():
    """The third element must be the true magnitude, and no blend may
    push a decoded value outside the stretch it was encoded with — an
    out-of-range wind is silently wrong rather than visibly broken."""
    d = _probe()
    assert d["tupleLen"] == 3, "sampleUV must return [u, v, magnitude]"
    assert d["magOk"], "the returned magnitude is not hypot(u, v)"
    assert d["decodedLo"] >= -40.0 - 1e-9, d["decodedLo"]
    assert d["decodedHi"] <= 40.0 + 1e-9, d["decodedHi"]


def test_the_tile_service_resamples_server_side():
    """``windTiles`` must keep resampling — the client stopped.

    This became LOAD-BEARING when the client-side blend was removed.
    Earth Engine's bicubic is what makes the field smooth; measured on a
    GFS tile at zoom 10, the unresampled version runs to 176 identical
    pixels in a row against 45 for the bicubic one, with a maximum step
    of 6 against 2. Drop it and the particles advect across a visibly
    blocky field, with nothing downstream left to hide it.

    Bicubic rather than bilinear because it costs nothing here — it is
    computed once per tile, server-side, and cached in the PNG.
    """
    import ee
    import geeViz.weather as wx
    img = ee.Image([1, 2]).rename(["u", "v"])

    src = (ROOT / "geeViz" / "weather.py").read_text(encoding="utf-8")
    # windImage and windTiles held identical copies of the select +
    # resample block; it lives in one helper now, so exactly one place
    # decides how the field gets smoothed.
    body = src[src.index("def _uv_image("):src.index("def windQueryImage(")]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("#"))
    assert 'viz.get("resample", "bicubic")' in code, (
        "_uv_image no longer defaults to bicubic; the client does not "
        "interpolate, so nothing else will smooth the field")
    assert "img = img.resample(rs)" in code, (
        "the resample mode is read but never applied")

    # And both renderers must go through it rather than re-rolling it.
    for fn in ("def windImage(", "def windTiles("):
        seg = src[src.index(fn):src.index(fn) + 1600]
        assert "_uv_image(image, viz)" in seg, (
            f"{fn.strip()} does not use the shared helper")
        assert "img.resample(" not in seg, (
            f"{fn.strip()} resamples on its own again — two copies is "
            f"how they drift apart")

    # And it must survive into the graph, not just the source.
    served = wx.windTiles(img).serialize()
    assert "resample" in served.lower(), (
        "the rendered tile image carries no resample step")


def test_the_client_does_not_interpolate_the_forecast():
    """``sampleUV`` reads the nearest tile pixel and stops.

    Earth Engine already smoothed the tile (``resample('bicubic')``),
    and what remains after that is 8-bit quantization — 0.31 m/s per
    level. Interpolating between two equal bytes returns the same byte,
    so a blend here recovers nothing.

    Interpolating the FIELD GRID is a different matter and is done: that
    grid is a subsampling this module chose, so smoothing it back is
    undoing our own coarseness, not second-guessing the forecast.
    """
    body = _strip_js_comments(_js_fn_body("sampleUV"))
    for corner in ("g10", "g01", "g11", "wa", "wb", "wc", "wd"):
        assert corner not in body, (
            f"sampleUV is interpolating the forecast again ({corner}); "
            f"the tile arrives bicubic-resampled and the rest is "
            f"quantization")
    assert body.count("pixelUV(") == 1, (
        "one tile read per sample; more means a blend crept back in")
    # ...but the grid read must interpolate, or the flow facets at the
    # spacing we chose.
    grid = _strip_js_comments(_js_fn_body("fieldAt"))
    assert "wa" in grid and "wd" in grid, (
        "fieldAt no longer interpolates the grid — the flow will facet "
        "at particleFieldSpacing")


def test_tiles_track_the_map_rather_than_a_low_cap():
    """A low cap forces the client to sample a coarse grid and then
    interpolate its way back to smooth — the long way round. Tiles
    should be fetched near the resolution they are shown at, so the
    server-side bicubic lands where it is needed.

    The cap only stops the pointless extreme; what actually bounds the
    request count is the off-screen cull, which took a zoom-10 view from
    1559 tiles to the ~35 the viewport needs.
    """
    import re as _re
    src = _strip_js_comments(JS.read_text(encoding="utf-8"))
    cap = float(_re.search(
        r"v\.particleMaxTileZoom !== undefined\s*\?\s*"
        r"v\.particleMaxTileZoom : ([\d.]+)", src).group(1))
    assert cap >= 10, (
        f"the tile cap is {cap:.0f}; below about 10 a zoomed-in view "
        f"samples a grid coarser than the screen and needs a client "
        f"blend to look right")
    # A 28 km forecast grid has nothing to say below ~150 m/pixel.
    assert cap <= 12, (
        f"a cap of {cap:.0f} fetches tiles finer than 150 m against a "
        f"28 km forecast grid — pure upsampling, at 4x the tiles per "
        f"level")


# ---------------------------------------------------------------------------
# The field is built once per view, not sampled per particle per frame.
# ---------------------------------------------------------------------------


def test_the_hot_path_does_no_geography():
    """``frame`` must not project, trigonometry, or touch a tile.

    That is the whole point of the prebuilt field. At 3000 particles and
    60fps this loop runs 180,000 times a second; buildField runs its
    equivalent ~32,000 times per VIEW CHANGE and not at all while the
    map sits still.
    """
    body = _strip_js_comments(_js_fn_body("frame"))
    for banned in ("fromLatLngToDivPixel", "fromDivPixelToLatLng",
                   "Math.cos", "Math.sqrt", "sampleUV(", "getTile(",
                   "p.lat", "p.lon", "zoomScale"):
        assert banned not in body, (
            f"frame() still does {banned} per particle — it belongs in "
            f"buildField, once per cell per view")
    assert "fieldAt(st, p.x, p.y)" in body, (
        "frame() must read the prebuilt grid")
    assert "p.x += d[0];" in body and "p.y += d[1];" in body, (
        "the field already carries pixels per frame; advancing is an add")


def test_buildfield_does_the_work_frame_used_to():
    """Everything that left the hot path has to have landed here."""
    body = _strip_js_comments(_js_fn_body("buildField"))
    for needed in ("fromDivPixelToLatLng", "Math.cos", "sampleUV(",
                   "cfg.minSpeed", "cfg.maxSpeed", "cfg.zoomRef"):
        assert needed in body, f"buildField never does {needed}"
    assert "Math.pow(2, cfg.zoomRef - zoom)" in body, (
        "the zoom normalisation is gone; streak length will double per "
        "zoom level again")
    assert "f[i + 1] = -v * scale;" in body, (
        "screen y grows downward while v is northward — without the "
        "sign flip the whole field is mirrored north/south")


def test_the_field_is_rebuilt_when_the_view_moves():
    """A pan invalidates every cached vector: canvas pixel (0, 0) means
    a different place on the globe afterwards. Rebuilding is keyed to
    the view, and tied to idle so it happens once when movement stops
    rather than during the drag."""
    src = _strip_js_comments(JS.read_text(encoding="utf-8"))
    key = _strip_js_comments(_js_fn_body("viewKey"))
    for part in ("getZoom()", "lat()", "lng()", "st.w", "st.h"):
        assert part in key, (
            f"viewKey ignores {part}; the field will go stale without "
            f"anything noticing")
    ensure = _strip_js_comments(_js_fn_body("ensureField"))
    assert "st.fieldKey === viewKey(st)" in ensure
    assert 'addListener("idle"' in src
    idle = src[src.index('addListener("idle"'):][:400]
    assert "field = null" in idle, "idle does not invalidate the field"


def test_particle_count_comes_from_canvas_width():
    """After windy.js: a wider canvas has more room to fill.

    It used to compound with zoom, which was really compensating for
    streak length growing with zoom — fixed at the source now, so the
    zoom term only thinned the field where it was already densest.
    """
    body = _strip_js_comments(_js_fn_body("countFor"))
    assert "width * cfg.density" in body, (
        "the count no longer derives from canvas width")
    assert "cfg.zoomFactor" not in body and "zoomRef" not in body, (
        "count must not depend on zoom any more")
    assert "cfg.count !== null" in body, (
        "an explicit particleCount must still win outright")


def test_python_does_not_pin_the_count():
    """Stamping a default would defeat the width derivation entirely —
    the client would see a number and never measure the canvas. This is
    the one particle key deliberately absent by default."""
    viz = _stamped_viz()
    assert "particleCount" not in viz, (
        "weather.py sends a particleCount, so the canvas width is never "
        "consulted")
    assert viz["particleDensity"] == 1.75
    # ...but an explicit request still travels.
    import ee
    import geeViz.weather as wx
    sent = {}

    class FakeMap:
        def addLayer(self, image, viz=None, name=None, visible=True):
            sent[name] = viz or {}

    wx.addWindLayer(FakeMap(), ee.Image([1, 2]).rename(["u", "v"]),
                    {"particleCount": 900}, "W")
    v = [x for x in sent.values() if x.get("windParticles")][0]
    assert v["particleCount"] == 900


def test_the_count_and_grid_maths_run():
    """Numbers, executed rather than read."""
    d = _probe_field()
    assert d["w1700"] == 2975, (
        f"a 1700px canvas gives {d['w1700']} particles; expected ~3000")
    assert d["clampLo"] == 400 and d["clampHi"] == 20000
    assert d["explicit"] == 900
    # The grid read must ramp linearly across a cell.
    assert d["ramp"] == [1.0, 1.25, 1.5, 1.75, 2.0], d["ramp"]
    assert d["outside"] is None, "fieldAt must reject an out-of-grid sample"
    # BOTH corners: a check that only looks at the near one still rejects
    # a missing near corner, so testing that alone cannot tell a full
    # check from a partial one.
    assert d["missingNear"] is None, (
        "a missing NEAR corner must reject the sample")
    assert d["missingCorner"] is None, (
        "a missing FAR corner must reject the sample too — blending a "
        "zero in drags the vector toward calm at every data edge")
