"""Forecast wind from ECMWF, GFS and WeatherNext, on one interface.

The three models answer the same question with three different data
models, and the differences are not cosmetic — they change which image
is the right one to show for a given instant:

======================  ========================  ======================
model                   run (init) time            valid time
======================  ========================  ======================
``euro``  ECMWF IFS     ``creation_time`` (ms)     ``forecast_time``
``gfs``   NOAA GFS0P25  ``creation_time`` (ms)     ``forecast_time``
``weathernext``  WN3    ``start_time`` (ISO)       ``end_time`` (ISO)
======================  ========================  ======================

Two consequences worth knowing before using this module.

**The property TYPES differ, and Earth Engine filters do not coerce.**
Comparing an ISO string property against a number returns an empty
collection rather than raising, so getting it wrong reads as "no data
for that window" instead of as a bug. Each model therefore declares
``iso_times``, and ``test_declared_time_types_match_the_live_data``
checks every declaration against the live collection — so a provider
that changes representation fails a test rather than quietly returning
nothing.

**WeatherNext's ``system:time_start`` is the INIT time**, one value for
every image in a run. Anything selecting on it picks a run rather than
a moment, and a time lapse built on it collapses to a single frame.
:func:`getForecastData` restamps it to the valid time on output.

**Band names differ per model** and are looked up here rather than
guessed:

* euro         ``u_component_of_wind_10m_sfc`` / ``v_...``
* gfs          ``u_component_of_wind_10m_above_ground`` / ``v_...``
* weathernext  ``u_component_of_wind_10m_mean`` / ``v_...``

That last one carries a trap. WeatherNext also publishes
``wind_speed_10m_mean``, and it is NOT the magnitude of
(``u_mean``, ``v_mean``). It is the ensemble mean of speeds, while u and
v are means of components, where opposing members cancel — Jensen's
inequality makes mean-of-speeds the larger of the two. Measured at
Denver on the 2026-09-09T10:00Z step: ``|(u_mean, v_mean)|`` = 0.9875
m/s against ``wind_speed_10m_mean`` = 1.3119, a 33% gap. So a vector
built from the components paired with the published mean speed is
internally inconsistent. This module derives speed from the components
only, which keeps the arrow's direction and its length describing the
same wind.
"""

import datetime
import json
import math

import ee

from geeViz.fireLib.wind import wind_speed_direction
from geeViz.getImagesLib import fillEmptyCollections

__all__ = [
    "MODELS",
    "getForecastData",
    "windQueryImage",
    "windBands",
    "windImage",
    "windTiles",
    "addWindLayer",
    "VARIABLES",
    "getVariable",
    "SPEED_UNITS",
    "DIRECTION_UNITS",
    "WIND_PALETTE",
    "PRECIP_PALETTE",
    "TEMPERATURE_PALETTE",
    "DEFAULT_SPEED_PALETTE",
    "DEFAULT_MAX_SPEED",
]


#: One entry per supported model. ``run_prop`` of ``None`` means the
#: collection carries no init time, so "the most recent run" is not a
#: question it can answer.
MODELS = {
    "euro": {
        "collection": "ECMWF/NRT_FORECAST/IFS/OPER",
        "u_band": "u_component_of_wind_10m_sfc",
        "v_band": "v_component_of_wind_10m_sfc",
        "run_prop": "creation_time",
        "valid_prop": "forecast_time",
        "lead_prop": "forecast_hours",
        "iso_times": False,               # epoch millis
        "native_scale_m": 44528,          # ~0.4 deg
        "label": "ECMWF IFS (near-real-time)",
    },
    "gfs": {
        "collection": "NOAA/GFS0P25",
        "u_band": "u_component_of_wind_10m_above_ground",
        "v_band": "v_component_of_wind_10m_above_ground",
        "run_prop": "creation_time",
        "valid_prop": "forecast_time",
        "lead_prop": "forecast_hours",
        "iso_times": False,               # epoch millis
        "native_scale_m": 27830,          # 0.25 deg
        "label": "NOAA GFS 0.25 deg",
    },
    "weathernext": {
        "collection": ("projects/gcp-public-data-weathernext/assets/"
                       "weathernext_3_0_0_0p1deg"),
        "u_band": "u_component_of_wind_10m_mean",
        "v_band": "v_component_of_wind_10m_mean",
        # start_time is the INITIALIZATION; end_time is the valid time.
        "run_prop": "start_time",
        "valid_prop": "end_time",
        "lead_prop": "forecast_hour",
        "iso_times": True,                # ISO 8601 strings
        "native_scale_m": 11132,          # 0.1 deg
        "label": "WeatherNext 3 (0.1 deg, ensemble mean)",
    },
    "weathernext_stations": {
        "collection": ("projects/gcp-public-data-weathernext/assets/"
                       "weathernext_3_0_0_0p05deg"),
        # The 0.05 deg product is station-head 2 m temperature and
        # dewpoint only -- no wind. Registered so getVariable can reach
        # it; getForecastData (which is about wind) will report the
        # missing bands rather than failing obscurely.
        "u_band": None,
        "v_band": None,
        "run_prop": "start_time",
        "valid_prop": "end_time",
        "lead_prop": "forecast_hour",
        "iso_times": True,                # ISO 8601 strings
        "native_scale_m": 5566,           # 0.05 deg
        "label": "WeatherNext 3 stations (0.05 deg)",
    },
}

#: Earth Engine aborts ``sample()`` once it accumulates more than ~5000
#: elements ("Collection query aborted after accumulating over 5000
#: elements"), and it does so DURING accumulation — so a trailing
#: ``.limit()`` cannot save you, and the error surfaces at ``getInfo()``
#: rather than near the call that caused it. Every point budget here is
#: clamped below that ceiling.
MAX_SAMPLE_POINTS = 4500

#: Multiplier from metres/second.
SPEED_UNITS = {
    "m/s": 1.0,
    "km/hr": 3.6,
    "mi/hr": 2.236936292054402,
}

#: Multiplier from degrees.
DIRECTION_UNITS = {
    "degrees": 1.0,
    "radians": math.pi / 180.0,
}


def _ms(d):
    """Epoch milliseconds from anything date-like, without a round trip.

    The past/future/spanning branch in :func:`getForecastData` is a
    CLIENT-side decision, so this value has to exist in Python. Parsing
    it here rather than asking Earth Engine keeps the whole function at
    zero round trips before it builds its graph -- ``ee.Date(s).millis()
    .getInfo()`` was a fifth of a second each, three times per call, for
    arithmetic ``datetime`` does for free.

    ``ee.Date`` is the one input form that still costs a fetch, because
    its value genuinely lives on the server. Pass a string, a
    ``datetime`` or epoch millis to avoid it.
    """
    if isinstance(d, (int, float)):
        return int(d)
    if isinstance(d, ee.Date):
        return int(d.millis().getInfo())     # the only unavoidable fetch
    if isinstance(d, datetime.datetime):
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return int(d.timestamp() * 1000)
    if isinstance(d, datetime.date):
        d = datetime.datetime(d.year, d.month, d.day,
                              tzinfo=datetime.timezone.utc)
        return int(d.timestamp() * 1000)
    return int(_parse_iso(str(d)).timestamp() * 1000)


def _parse_iso(text):
    """``YYYY-MM-DD`` or any ISO 8601 instant, as an aware datetime.

    ``fromisoformat`` before 3.11 rejects a trailing ``Z``, which is the
    form every one of these collections publishes, so it is translated
    rather than relied upon.
    """
    t = text.strip().replace("/", "-")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        out = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise ValueError(
            f"cannot read {text!r} as a date — use 'YYYY-MM-DD', an ISO "
            f"8601 instant, a datetime, or epoch milliseconds")
    if out.tzinfo is None:
        out = out.replace(tzinfo=datetime.timezone.utc)
    return out


def _fmt_time(ms, iso):
    """A window bound in whatever type the collection's property uses.

    Earth Engine filters do not coerce: comparing an ISO string property
    against a number returns an EMPTY collection rather than raising, so
    a bound of the wrong type reads as "no data for that window" instead
    of as a bug.
    """
    if not iso:
        return ms
    return datetime.datetime.fromtimestamp(
        ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _model(model):
    key = (model or "").strip().lower()
    if key not in MODELS:
        raise ValueError(
            f"unknown model {model!r} — choose one of "
            f"{sorted(MODELS)}")
    return key, MODELS[key]


def _min_lead(collection, lead_p):
    """The shortest lead present in ``collection``, as an ``ee.Number``.

    Server-side and un-cached, by design. "Analysis" means lead 0 for
    GFS and ECMWF, but WeatherNext's ``forecast_hour`` runs 1..360 and
    never reaches 0 -- so hard-coding 0 hands back an empty collection
    for it, which reads as "no data" rather than as a wrong constant.

    Reduced over the ALREADY-WINDOWED collection rather than over the
    whole archive: the window bounds the scan, so there is nothing to
    cache and nothing expensive to avoid. The value stays an
    ``ee.Number`` and goes straight into ``ee.Filter.eq``, which accepts
    computed values -- one graph, no round trip.

    ``reduceColumns`` returns null for an empty collection rather than
    raising, so the ``If`` gives an empty window a harmless 0 instead of
    a filter against null.
    """
    lead = collection.reduceColumns(ee.Reducer.min(), [lead_p]).get("min")
    return ee.Number(ee.Algorithms.If(lead, lead, 0))


def getForecastData(startDate, endDate, model="gfs", now=None,
                    lookback_days=4, stat="mean"):
    """Wind images for ``[startDate, endDate]``, per model, one interface.

    Every model marks run and valid time differently -- GFS and ECMWF use
    ``creation_time`` / ``forecast_time`` in epoch millis, WeatherNext
    uses ``start_time`` / ``end_time`` as ISO 8601 strings. Reconciling
    that is what this function is for.

    What it returns depends on where the window sits relative to now,
    because "the forecast for last Tuesday" and "the forecast for next
    Tuesday" are different questions:

    * **Entirely past** -- the SHORTEST-LEAD image from every run
      initialized inside the window. That is each model's best estimate
      of what the atmosphere actually did, stitched across runs: a fresh
      analysis every cycle rather than one old run projecting forward.
    * **Entirely future** -- one run, the most recent, filtered to the
      window. Mixing runs inside a forward window makes the field jump
      where two runs disagree.
    * **Spanning now** -- both, split at the most recent run's
      initialization: shortest-lead analyses up to that moment
      (exclusive), then that run's forecast from there on.

    "Shortest lead" rather than literally lead 0 because WeatherNext's
    ``forecast_hour`` starts at 1; GFS and ECMWF start at 0. The value is
    read from the collection, not hard-coded.

    Args:
        startDate, endDate: ``str``, ``datetime``, ``ee.Date`` or epoch ms.
        model: ``"euro"``, ``"gfs"`` or ``"weathernext"``.
        now: Override the clock. Testing seam.
        lookback_days: How far back to hunt for a run. Bounds the scan --
            an unbounded search for the newest run walks every image ever
            published and times out.
        stat: WeatherNext only -- ``"mean"`` (default) or a percentile
            (``"p10"`` ... ``"p90"``).

    Returns:
        ``ee.ImageCollection`` of two-band (``u``, ``v``) images carrying
        ``valid_time`` (ms), ``lead_hours``, ``wx_model`` and a
        ``system:time_start`` set to the VALID time.
    """
    key, spec = _model(model)
    if not spec.get("u_band"):
        raise ValueError(
            f"{key!r} publishes no wind components — it is a "
            f"{spec['label']}. Use 'gfs', 'euro' or 'weathernext'.")

    t0, t1 = _ms(startDate), _ms(endDate)
    if t1 < t0:
        raise ValueError(f"endDate precedes startDate ({startDate} .. {endDate})")
    tn = _ms(now) if now is not None else int(
        datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)

    ic = ee.ImageCollection(spec["collection"])
    u_b, v_b = spec["u_band"], spec["v_band"]
    if key.startswith("weathernext") and stat != "mean":
        u_b = u_b.replace("_mean", f"_{stat}")
        v_b = v_b.replace("_mean", f"_{stat}")
    valid_p, lead_p, run_p = spec["valid_prop"], spec["lead_prop"], spec["run_prop"]
    # Both time properties of a given product share one representation,
    # so one flag covers the run bound and the valid bound alike.
    iso = run_iso = spec["iso_times"]

    def _v(ms):
        return _fmt_time(ms, iso)

    def _r(ms):
        return _fmt_time(ms, run_iso)

    def _norm(img):
        # Restamp system:time_start to the VALID time. WeatherNext
        # otherwise carries the init time there -- one value for a whole
        # run -- and any time lapse collapses to a single frame.
        vt = ee.Date(img.get(valid_p)).millis()
        return (img.select([u_b, v_b], ["u", "v"])
                   .set({"valid_time": vt,
                         "lead_hours": img.get(lead_p),
                         "wx_model": key,
                         "system:time_start": vt}))

    def _analyses(lo_ms, hi_ms):
        """Shortest-lead image from every run initialized in the window.

        Everything published in the window is pulled first, then reduced
        to its own minimum lead. The window is the bound, so the reduce
        is cheap and the answer describes the data actually in hand
        rather than a constant read off some other slice of the archive.
        """
        win = ic.filter(ee.Filter.And(ee.Filter.gte(run_p, _r(lo_ms)),
                                      ee.Filter.lte(run_p, _r(hi_ms))))
        return win.filter(ee.Filter.eq(lead_p, _min_lead(win, lead_p)))

    def _from_run(run_val, lo_ms, hi_ms):
        return (ic.filter(ee.Filter.eq(run_p, run_val))
                  .filter(ee.Filter.And(ee.Filter.gte(valid_p, _v(lo_ms)),
                                        ee.Filter.lte(valid_p, _v(hi_ms)))))

    def _out(coll):
        """Normalize, order, and never hand back an empty collection.

        An empty result is not merely unhelpful — it is a crash waiting
        a few lines later, where ``addWindLayer`` reads band names off
        ``.first()`` and gets ``Image.bandNames: Parameter 'image' is
        required``. ``fillEmptyCollections`` substitutes one fully
        masked u/v image instead, which renders as nothing and queries
        as nothing, and carries ``lead_hours = -1`` so a caller can tell
        "no data" from "calm".
        """
        dummy = (ee.Image([0, 0]).rename(["u", "v"]).float()
                   .set({"valid_time": t0, "lead_hours": -1,
                         "wx_model": key, "system:time_start": t0}))
        return fillEmptyCollections(
            coll.map(_norm).sort("valid_time"), dummy)

    look_ms = int(lookback_days * 86400 * 1000)

    def _latest_run_at_or_before(ref_ms):
        def _win(span):
            return ic.filter(ee.Filter.And(
                ee.Filter.gt(run_p, _r(ref_ms - span)),
                ee.Filter.lte(run_p, _r(ref_ms))))
        near, wide = _win(look_ms), _win(look_ms * 10)
        return ee.Algorithms.If(near.size().gt(0),
                                near.aggregate_max(run_p),
                                wide.aggregate_max(run_p))

    # ---- entirely past: analyses only ---------------------------------
    if t1 <= tn:
        return _out(_analyses(t0, t1))

    def _newest_run_reaching(end_ms):
        """Newest run that actually has an image valid near ``end_ms``.

        Not simply the newest run. WeatherNext interleaves 6-hourly inits
        reaching 360 h with interim hourly inits that stop at 48 h, so
        the most recent initialization is frequently one that cannot
        cover a forward window at all: asking for two days out returned
        twelve images at leads 37..48 and stopped a day and a half short.

        Choosing among the runs that reach the far end keeps the "one
        run" property while actually spanning what was asked for. It is
        a no-op where every run has the same horizon, i.e. GFS and ECMWF.
        """
        # At or PAST the end, not merely near it. A window ending
        # 09-13 was previously served by an hourly init whose 48-hour
        # reach stopped at 09-12 11:00 — that image fell inside a
        # "within 24 hours of the end" band, so the run looked like it
        # covered the request and the result silently stopped a day
        # short. Requiring an image at or beyond the end makes coverage
        # a fact rather than an approximation.
        span = 24 * 3600 * 1000
        reaching = ic.filter(ee.Filter.And(
            ee.Filter.gte(valid_p, _v(end_ms)),
            ee.Filter.lte(valid_p, _v(end_ms + span))))
        return ee.Algorithms.If(reaching.size().gt(0),
                                reaching.aggregate_max(run_p),
                                _latest_run_at_or_before(tn))

    latest_run = _newest_run_reaching(t1)

    # ---- entirely future: one run ------------------------------------
    if t0 >= tn:
        return _out(_from_run(latest_run, t0, t1))

    # ---- spanning: analyses up to the run, then the run --------------
    #
    # The seam is the most recent initialization, not "now". Before it,
    # a fresh analysis exists for every cycle and is the better record;
    # from it onward, that single run is the forecast. Splitting at now
    # instead would ask the latest run for hours it did not produce, or
    # discard analyses newer than the split.
    run_ms = ee.Date(latest_run).millis()
    # The seam, expressed in whatever type the valid-time property uses.
    # ``iso`` is known here, so this is a plain branch rather than an
    # ee.Algorithms.If — one less node, and it reads as what it is.
    seam = (ee.Date(run_ms).format("YYYY-MM-dd'T'HH:mm:ss'Z'")
            if iso else run_ms)
    before = _analyses(t0, t1).filter(ee.Filter.lt(valid_p, seam))
    after = ic.filter(ee.Filter.eq(run_p, latest_run)).filter(
        ee.Filter.And(ee.Filter.gte(valid_p, seam),
                      ee.Filter.lte(valid_p, _v(t1))))
    return _out(before.merge(after))


def _uv_image(image, viz):
    """The u/v pair, selected and resampled, ready to render.

    Both callers need exactly this and had identical copies of it. The
    resampling is the part worth keeping in one place: the CLIENT does
    no interpolation of its own, so whatever smoothing the field gets,
    it gets here. Dropping it makes the particles advect across a
    visibly blocky field -- measured on a GFS tile at zoom 10, the
    unresampled version runs to 176 identical pixels in a row against 45
    for the bicubic one.

    Bicubic rather than bilinear because it costs nothing at this point:
    it is evaluated once per tile, server-side, and cached in the PNG.
    """
    viz = viz or {}
    u_b, v_b = _uv(viz)
    img = ee.Image(image).select([u_b, v_b], ["u", "v"])
    rs = viz.get("resample", "bicubic")
    if rs:
        img = img.resample(rs)
    return img


def windQueryImage(image, *, speed_units="m/s", direction_units="degrees",
                   direction_convention="from", resample="bicubic"):
    """The queryable image behind a wind vector layer.

    This is the half of the layer that carries NUMBERS. geeViz lets a
    layer's rendering and its query source be different objects, and
    wind is the case that needs it: what you want to see is an arrow
    field, and what you want to click is a direction and a speed.

    Args:
        image: ``ee.Image`` with ``u`` / ``v`` bands (as returned by
            :func:`getForecastData`).
        speed_units: one of :data:`SPEED_UNITS` — ``m/s``, ``km/hr``,
            ``mi/hr``.
        direction_units: ``degrees`` or ``radians``.
        direction_convention: ``"from"`` (meteorological — 270 is a
            westerly, the convention every barb chart uses) or ``"to"``
            (the way the air is moving, which is what a spread model
            wants).

    Returns:
        ``ee.Image`` with bands ``direction`` and ``speed``, plus
        ``direction_from`` / ``direction_to`` kept alongside so a query
        can show both without a second request.
    """
    if speed_units not in SPEED_UNITS:
        raise ValueError(f"speed_units must be one of {sorted(SPEED_UNITS)}")
    if direction_units not in DIRECTION_UNITS:
        raise ValueError(
            f"direction_units must be one of {sorted(DIRECTION_UNITS)}")
    if direction_convention not in ("from", "to"):
        raise ValueError('direction_convention must be "from" or "to"')

    # Reuses fireLib's implementation rather than restating the maths.
    # That function carries the bearing = 90 - math_angle reflection,
    # which is the part everyone gets wrong (and which is invisible on
    # the diagonals, so a test that only checks SW passes anyway).
    # Bicubic before any derived maths. Forecast grids are coarse (0.1 to
    # 0.4 deg) and nearest-neighbour renders them as visible blocks at
    # map zooms; resample() makes the interpolation happen when Earth
    # Engine reprojects for display. It affects DISPLAY and derived
    # sampling only -- the underlying values are untouched.
    if resample:
        image = image.resample(resample)
    sd = wind_speed_direction(image, "u", "v")

    speed = sd.select("speed").multiply(SPEED_UNITS[speed_units]).rename("speed")
    chosen = sd.select(f"direction_{direction_convention}")
    direction = chosen.multiply(DIRECTION_UNITS[direction_units]) \
                      .rename("direction")

    return (direction.addBands(speed)
            .addBands(sd.select("direction_from"))
            .addBands(sd.select("direction_to"))
            .set({
                "speed_units": speed_units,
                "direction_units": direction_units,
                "direction_convention": direction_convention,
            }))


#: The u/v stretch baked into the particle tiles, in m/s.
#:
#: HARD-CODED on purpose, and identical in ``wind-particles.js``. The
#: tiles are 8-bit PNGs: u is encoded in red, v in green, each linearly
#: mapped from this range onto 0..255. The client can only invert that
#: if it knows the exact range, and a range that travelled as data could
#: drift out of sync with the encoder -- silently, because wrong-but-
#: plausible winds look like weather rather than like a bug.
#:
#: +/-40 m/s (about 145 km/h) covers everything short of a major
#: cyclone's core, at a quantization of 80/255 = 0.31 m/s per step. That
#: is far finer than any forecast's real precision, and advection is
#: insensitive to it. Values beyond the range clamp rather than wrap.
WIND_TILE_MIN_MS = -40.0
WIND_TILE_MAX_MS = 40.0

#: Sensible full-scale wind for the speed raster, per unit. A stretch
#: that does not follow the unit is the fastest way to a map that is
#: entirely dark blue (0..15 read as km/h) or entirely red (0..54 read
#: as m/s).
DEFAULT_MAX_SPEED = {"m/s": 15.0, "km/hr": 54.0, "mi/hr": 34.0}

def _hex(rgb):
    """``(r, g, b)`` 0-255 to ``#rrggbb``.

    Same result as ``geeViz.geeView.RGB_to_hex``, done locally so this
    module does not import the viewer -- ``geeView`` imports THIS module
    to serve ``Map.addWindLayer``, and a top-level import back would
    make the cycle depend on which one the user happens to import first.
    """
    return "#%02x%02x%02x" % tuple(int(round(c)) for c in rgb)


#: Wind speed, read off windy.com's own legend so a geeViz wind map and
#: a windy map of the same hour are comparable at a glance.
#:
#: Calibrated against windy's scale, whose labelled stops are 0, 3, 5,
#: 10, 15, 20 and 30 m/s -- so the palette is designed for a 0..30 m/s
#: stretch. :data:`DEFAULT_MAX_SPEED` is deliberately tighter than that
#: (15 m/s), which spends more of the ramp on the speeds most maps
#: actually contain; pass ``viz["max"]`` to widen it back out.
WIND_PALETTE = tuple(_hex(c) for c in [
    (61, 110, 163), (74, 148, 170), (74, 146, 148), (77, 142, 124),
    (76, 164, 76), (103, 164, 54), (162, 135, 64), (162, 109, 92),
    (141, 63, 92), (151, 75, 145), (95, 100, 160), (91, 136, 161),
    (91, 136, 161)])

#: Precipitation, same source. Blue through cyan and green to orange
#: and deep red.
PRECIP_PALETTE = tuple(_hex(c) for c in [
    (63, 123, 234), (41, 188, 237), (37, 210, 209), (41, 230, 176),
    (193, 238, 52), (247, 168, 43), (211, 49, 4), (138, 11, 3),
    (138, 11, 3)])

#: Temperature, same source. Violet and pale blue through green to
#: amber and dark red.
TEMPERATURE_PALETTE = tuple(_hex(c) for c in [
    (149, 137, 212), (150, 209, 216), (128, 204, 197), (102, 179, 186),
    (95, 143, 197), (80, 140, 61), (122, 146, 28), (171, 161, 14),
    (223, 177, 6), (243, 150, 6), (236, 94, 21), (190, 65, 18),
    (138, 42, 10)])

#: What an unconfigured wind layer paints with.
DEFAULT_SPEED_PALETTE = WIND_PALETTE


def windBands(image, viz=None):
    """Resolve which two bands are the u/v (dx/dy) components.

    Mirrors ``Map.addLayer``: ``viz["bands"]`` may be a list or a
    comma-separated string. Absent, the FIRST TWO bands are used in
    order -- dx then dy.

    Two bands by position rather than a guess by name, because every
    product names them differently (``u_component_of_wind_10m_sfc`` vs
    ``..._above_ground`` vs ``..._mean``) and a name-sniffing heuristic
    that quietly picks the 100 m wind instead of the 10 m wind is worse
    than an explicit parameter.
    """
    b = _uv(viz)
    if b == [0, 1]:
        b = ee.Image(image).bandNames().slice(0, 2).getInfo()
    return [str(b[0]), str(b[1])]


def _uv(viz):
    """The two u/v selectors to hand to ``select()`` — names or indices.

    ``ee.Image.select`` takes positions as happily as names, so the
    default case resolves to ``[0, 1]`` and never asks the server what
    the bands are called. :func:`windBands` exists for callers who want
    the actual NAMES and is welcome to spend a round trip on them; the
    rendering path has no use for them and does not.
    """
    viz = viz or {}
    b = viz.get("bands")
    if isinstance(b, str):
        b = [x.strip() for x in b.split(",") if x.strip()]
    if not b:
        return [0, 1]
    if len(b) != 2:
        raise ValueError(
            f"wind needs exactly two bands (dx, dy); got {list(b)}. Pass "
            'viz={"bands": ["u_band", "v_band"]}.')
    return [b[0], b[1]]


def windImage(image, viz=None):
    """``speed`` and ``direction`` bands from the u/v components.

    These are the QUERY bands. Direction is meteorological by default --
    the bearing the wind blows FROM, so 270 is a westerly -- because
    that is what forecast products and barb charts mean by "wind
    direction". ``viz["directionConvention"] = "to"`` gives the way the
    air is moving, which is what a spread model wants.

    Speed is converted to ``viz["units"]`` (default km/hr).
    """
    viz = viz or {}
    u_b, v_b = _uv(viz)
    units = viz.get("units", "km/hr")
    if units not in SPEED_UNITS:
        raise ValueError(f"units must be one of {sorted(SPEED_UNITS)}")
    conv = viz.get("directionConvention", "from")
    if conv not in ("from", "to"):
        raise ValueError('directionConvention must be "from" or "to"')

    img = _uv_image(image, viz)

    # Reuses fireLib rather than restating the maths: that helper carries
    # the bearing = 90 - math_angle REFLECTION, which is right on the
    # diagonals and wrong on all four cardinals if you get it wrong by
    # adding an offset instead.
    sd = wind_speed_direction(img, "u", "v")
    speed = sd.select("speed").multiply(SPEED_UNITS[units]).rename("speed")
    direction = sd.select("direction_" + conv).rename("direction")
    return (speed.addBands(direction)
            .set({"wind_units": units, "wind_direction_convention": conv}))


def windTiles(image, viz=None):
    """u/v encoded as an RGB image, for the particle tile service.

    Red carries u, green carries v, each stretched from
    :data:`WIND_TILE_MIN_MS` .. :data:`WIND_TILE_MAX_MS` onto 0..255.
    Blue is a constant; it exists only because ``visualize`` wants three
    bands for an RGB rendering.

    This is what lets the particles work anywhere instead of only inside
    a region fixed at call time. The previous design shipped a JSON
    lattice sampled once, so panning past its edge simply stopped the
    animation. Tiles stream with the view: the client fetches the
    squares it is looking at, decodes them, and advects.
    """
    viz = viz or {}
    u_b, v_b = _uv(viz)
    img = _uv_image(image, viz)
    rgb = img.addBands(ee.Image.constant(0).rename("z").toFloat())
    return rgb.visualize(bands=["u", "v", "z"],
                         min=WIND_TILE_MIN_MS, max=WIND_TILE_MAX_MS)


def addWindLayer(Map, image, viz=None, name="Wind", visible=True):
    """Add a wind field: a queryable speed raster plus animated particles.

    Two layers, in the style of windy.com -- a smooth speed raster
    carrying the reading, with particle trails over it showing the flow.

    Args:
        image: ``ee.Image`` whose bands include the wind components.
        viz: Same spirit as ``Map.addLayer``'s viz dict.

            * ``bands`` (list or comma string) -- the dx/dy components.
              Defaults to the image's FIRST TWO bands, in order.
            * ``units`` -- ``"km/hr"`` (default), ``"m/s"``, ``"mi/hr"``.
            * ``min`` / ``max`` -- speed stretch. ``max`` defaults to a
              value chosen FOR THE UNIT (15 m/s, 54 km/h, 34 mi/h), so
              switching units cannot leave the raster all one colour.
            * ``palette`` -- speed ramp. Defaults to
              :data:`WIND_PALETTE`, taken from windy.com's legend.
            * ``particleColor`` -- trail colour, default ``"#fff"``.
            * ``particleOpacity`` (0.9) -- alpha at the head.

            **Size.** ``particleStrokeWeight`` (1.1) is the base width;
            ``particleMinSize`` and ``particleMaxSize`` are the absolute
            pixel widths at the tail and the head, defaulting to 0.45x
            and 1.5x the weight so changing the weight alone rescales
            the whole taper. Equal min and max give a constant-width
            ribbon instead of a comet. ``particleLineWidth`` is the old
            name for ``particleStrokeWeight`` and still works.

            **Shape.** ``particleTrailLength`` (26) is how many frames
            of history each trail draws -- that, times the per-frame
            step, IS the streak length. ``particleTaper`` (2.1) is the
            exponent on the tail fade: 1 is a linear wedge, higher
            stretches the faint part out. ``particleHeadBoost`` (1.6)
            brightens the leading segment. ``particleLineCap``
            (``"round"``, or ``"butt"`` for blunt tips).

            **Speed.** ``particleSpeedFactor`` (380) is seconds of
            advection per frame -- it sets how fast the field moves AND,
            because length is proportional to it, how long the streaks
            are. ``particleMinSpeed`` (3.0 m/s) and ``particleMaxSpeed``
            (45.0 m/s) are apparent-speed floor and ceiling applied to
            the advection only: without a floor a light breeze draws a
            one-pixel dot and a calm map reads as broken, without a
            ceiling a cyclone core smears across the screen. Direction
            is untouched, and the speed raster and click query still
            report the true value.

            **Field.** ``particleFieldSpacing`` (8) is the grid
            spacing, in canvas pixels, of the wind field the client
            builds once per view. The wind is resolved per CELL --
            projection, cos(lat), the speed clamp, the tile read -- and
            each particle then just reads the grid, so the per-frame
            cost is an array lookup. Smaller resolves more detail and
            costs more to build, quadratically.

            **Sampling.** ``particleMaxTileZoom`` (10) caps the zoom
            of the u/v tiles fetched. Tiles track the map so that this
            module's ``resample('bicubic')`` is evaluated near display
            resolution -- the CLIENT does not interpolate, so the tile
            has to arrive smooth. The cap only stops the pointless
            extreme, where a tile pixel is finer than 150 m against a
            28 km forecast grid. Lower it to trade sharpness for
            bandwidth; what actually bounds the request COUNT is the
            off-screen particle cull, not this.

            **Lifetime.** ``particleMinAge`` / ``particleMaxAge``
            (22.5 and 90) -- the range each particle's lifetime is drawn
            from. A young particle has laid down less trail, so
            spreading lifetimes is what puts short streaks alongside
            long ones. Equal values give one uniform length.

            **Count.** Derived from canvas WIDTH:
            ``particleDensity`` (1.75) particles per pixel of width, so
            about 3000 on a 1700 px canvas, clamped by
            ``particleMinCount`` (400) / ``particleMaxCount`` (20000).
            Pass ``particleCount`` to override it outright. Count no
            longer varies with zoom -- it used to, which was really
            compensating for streak length growing with zoom, and that
            is fixed at the source now.

            ``particleZoomRef`` (7) remains, as the zoom streak length
            is calibrated at; every other zoom is scaled to match, so a
            streak is the same size on screen however far in you are.

            * ``directionConvention`` -- ``"from"`` (default) or ``"to"``.

    Returns:
        ``(speed_direction_image, encoded_tiles_image)``.
    """
    viz = dict(viz or {})
    # Two bases the rest of the particle defaults hang off. Resolved
    # here so that setting only the base moves everything derived from
    # it, rather than leaving a half-scaled taper or lifetime range.
    # particleLineWidth is the old name for particleStrokeWeight and is
    # still honored.
    stroke_weight = viz.get("particleStrokeWeight",
                            viz.get("particleLineWidth", 1.1))
    max_age = viz.get("particleMaxAge", 90)
    units = viz.get("units", "km/hr")
    if units not in SPEED_UNITS:
        raise ValueError(f"units must be one of {sorted(SPEED_UNITS)}")
    vmin = viz.get("min", 0)
    vmax = viz.get("max", DEFAULT_MAX_SPEED[units])
    palette = viz.get("palette", DEFAULT_SPEED_PALETTE)
    if isinstance(palette, str):
        palette = [c.strip() for c in palette.split(",")]
    pal_csv = ",".join(c.lstrip("#") for c in palette)

    q = windImage(image, viz)

    # 1. The speed raster, and the layer a click reads. Both derived
    #    bands ride along so a query reports direction beside speed.
    Map.addLayer(q, {
        "layerType": "geeImage",
        "bands": "speed",
        "min": vmin, "max": vmax,
        "palette": pal_csv,
        "canQuery": True,
        "addToLegend": True,
        "yLabel": "Wind speed (" + units + ")",
        "legendLabelLeftBefore": "Calm",
        "legendLabelRightAfter": " " + units,
    }, name + " speed", visible)

    # 2. The particle layer. A real geeImage layer, so the viewer mints
    #    tiles for it and gives it a panel entry -- but the RGB is never
    #    shown. wind-particles.js hides it and reads those tiles
    #    numerically instead.
    tiles = windTiles(image, viz)
    Map.addLayer(tiles, {
        "layerType": "geeImage",
        "windParticles": True,
        "windTileMin": WIND_TILE_MIN_MS,
        "windTileMax": WIND_TILE_MAX_MS,
        "windUnits": units,
        "canQuery": False,          # the speed raster answers clicks
        "addToLegend": False,
        # ---- color ---------------------------------------------
        "particleColor": viz.get("particleColor", "#fff"),
        "particleOpacity": viz.get("particleOpacity", 0.9),

        # ---- count ---------------------------------------------
        # Derived from canvas WIDTH, not from zoom: a wider canvas has
        # more room to fill, and that is the whole of it. ~3000 on a
        # 1700 px canvas. The count used to compound with zoom, which
        # was really compensating for streak length growing with zoom;
        # length is held constant on screen now, so density should be
        # too, and the zoom term only thinned the field where it was
        # already densest.
        #
        # NOT sent unless the caller asked for it -- stamping a number
        # here would pin the count and the width derivation would never
        # run. This is the one particle key that is deliberately absent
        # by default.
        **({"particleCount": viz["particleCount"]}
           if viz.get("particleCount") is not None else {}),
        "particleDensity": viz.get("particleDensity", 1.75),
        "particleMinCount": viz.get("particleMinCount", 400),
        "particleMaxCount": viz.get("particleMaxCount", 20000),
        # The zoom streak length is calibrated at. Every other zoom is
        # scaled to match, so a streak is the same size on screen
        # however far in you are.
        "particleZoomRef": viz.get("particleZoomRef", 7),

        # ---- size ----------------------------------------------
        # strokeWeight is the base; min/max size are absolute pixel
        # widths at tail and head, defaulting to a fraction of it so
        # changing the weight alone scales the whole taper.
        "particleStrokeWeight": stroke_weight,
        "particleMinSize": viz.get("particleMinSize", stroke_weight * 0.45),
        "particleMaxSize": viz.get("particleMaxSize", stroke_weight * 1.5),

        # ---- sampling ------------------------------------------
        # Grid spacing, in canvas pixels, of the field the client builds
        # once per view. The wind is resolved per CELL -- projection,
        # cos(lat), the speed clamp, the tile read -- and each particle
        # then just reads the grid. Smaller resolves more detail and
        # costs more to build, quadratically: 8 px on a 1700x1200 canvas
        # is ~32,000 cells, built once when the map settles, against
        # 240,000 full samples per second the old way.
        "particleFieldSpacing": viz.get("particleFieldSpacing", 8),
        # Ceiling on the zoom of the u/v tiles fetched. Tiles track the
        # map so that windTiles' bicubic resampling is evaluated near
        # display resolution and the client can take the nearest pixel;
        # the cap only stops the pointless extreme, where a tile pixel
        # is finer than 150 m against a 28 km forecast grid. What bounds
        # the REQUEST COUNT is the off-screen particle cull, not this.
        "particleMaxTileZoom": viz.get("particleMaxTileZoom", 10),

        # ---- shape ---------------------------------------------
        # trailLength * the per-frame step IS the streak length. It
        # replaced a canvas fade constant, which could give length or a
        # bright head but never both: a fade slow enough for a long
        # trail is nearly flat over its first twenty frames.
        "particleTrailLength": viz.get("particleTrailLength", 26),
        "particleTaper": viz.get("particleTaper", 2.1),
        "particleHeadBoost": viz.get("particleHeadBoost", 1.6),
        "particleLineCap": viz.get("particleLineCap", "round"),

        # ---- speed ---------------------------------------------
        "particleSpeedFactor": viz.get("particleSpeedFactor", 380),
        # Apparent-speed floor and ceiling in m/s, applied to the
        # advection only. Streak length is proportional to wind speed,
        # so without a floor a light breeze draws a one-pixel dot and a
        # calm map reads as a broken map; without a ceiling a cyclone
        # core smears across the screen. Direction is untouched, and the
        # speed raster and click query still carry the truth.
        "particleMinSpeed": viz.get("particleMinSpeed", 3.0),
        "particleMaxSpeed": viz.get("particleMaxSpeed", 45.0),

        # ---- lifetime ------------------------------------------
        # Each particle draws its own lifetime from
        # [particleMinAge, particleMaxAge], so short, medium and long
        # streaks coexist instead of one uniform comb. Set them equal
        # for a uniform look.
        "particleMaxAge": max_age,
        "particleMinAge": viz.get("particleMinAge", max_age * 0.25),
    }, name + " particles", visible)

    return q, tiles


#: Common variables per model, with the unit each product actually
#: publishes -- measured, not assumed.
#:
#: Temperature is the trap. GFS and ECMWF NRT both publish CELSIUS in
#: Earth Engine while WeatherNext publishes KELVIN. Measured at Denver
#: for the same hour: 29.46 / 27.46 / 297.40. Charting the three
#: together without normalizing puts one line 273 units off the others,
#: and it reads as a model blow-up rather than a unit mismatch.
#:
#: ``None`` means the model does not publish that variable. GFS in
#: particular does NOT have a stable band list: some images carry
#: ``total_precipitation_surface`` while others carry
#: ``precipitation_rate`` alongside ``gust``, ``haines_index`` and
#: ``ventilation_rate``.
VARIABLES = {
    "temperature_2m": {
        "euro": ("temperature_2m_sfc", "C"),
        "gfs": ("temperature_2m_above_ground", "C"),
        "weathernext": ("temperature_2m_mean", "K"),
        "label": "2 m temperature",
    },
    "dewpoint_2m": {
        "euro": ("dewpoint_temperature_2m_sfc", "C"),
        "gfs": ("dew_point_temperature_2m_above_ground", "C"),
        "weathernext": ("dewpoint_temperature_2m_mean", "K"),
        "label": "2 m dewpoint",
    },
    "relative_humidity_2m": {
        "euro": None,                 # publishes dewpoint, not RH
        "gfs": ("relative_humidity_2m_above_ground", "%"),
        "weathernext": None,
        "label": "2 m relative humidity",
    },
    "precipitation": {
        "euro": ("total_precipitation_sfc", "m"),
        "gfs": ("precipitation_rate", "kg/m^2/s"),
        "weathernext": ("total_precipitation_1hr_mean", "m"),
        "label": "Precipitation",
    },
    "total_cloud_cover": {
        "euro": None,
        "gfs": ("total_cloud_cover_entire_atmosphere", "%"),
        "weathernext": ("total_cloud_cover_mean", "fraction"),
        "label": "Total cloud cover",
    },
    "mean_sea_level_pressure": {
        "euro": ("mean_sea_level_pressure_sfc", "Pa"),
        "gfs": None,
        "weathernext": ("mean_sea_level_pressure_mean", "Pa"),
        "label": "Mean sea level pressure",
    },
    "sea_surface_temperature": {
        "euro": None,
        "gfs": None,
        "weathernext": ("sea_surface_temperature_mean", "K"),
        "label": "Sea surface temperature",
    },
    "wind_speed_10m": {
        # euro/gfs publish components only -- derive with windImage.
        "euro": None,
        "gfs": None,
        "weathernext": ("wind_speed_10m_mean", "m/s"),
        "label": "10 m wind speed",
    },
}


def getVariable(collection, variable, model, *, to_celsius=True,
                resample="bicubic", stat=None):
    """Select one variable from a collection, unit-normalized.

    Args:
        collection: ``ee.ImageCollection`` from the asset ``model``
            names. Pass the RAW collection -- ``getForecastData`` has
            already narrowed its output to wind.
        variable: key of :data:`VARIABLES`.
        model: which model ``collection`` came from.
        to_celsius: Convert Kelvin products to Celsius so models are
            directly comparable.
        resample: Applied before selection so the layer is smooth at map
            zooms rather than blocky.
        stat: WeatherNext only. Swap the ensemble statistic --
            ``"p10"``, ``"p25"``, ``"p50"``, ``"p75"``, ``"p90"``. The 64
            members are published pre-aggregated, so forecast SPREAD is
            the difference of two of these rather than a reduction over
            members.

    Returns:
        ``ee.ImageCollection`` of single-band images named ``variable``.

    Raises:
        ValueError: if the model does not publish it -- better than a
            band-not-found twenty lines later, or an empty layer that
            renders as "no data" and reads as "no weather".
    """
    key, _ = _model(model)
    if variable not in VARIABLES:
        raise ValueError(f"unknown variable {variable!r} — choose from "
                         f"{sorted(VARIABLES)}")
    entry = VARIABLES[variable].get(key)
    if entry is None:
        have = [m for m in ("euro", "gfs", "weathernext")
                if VARIABLES[variable].get(m)]
        raise ValueError(
            f"{key!r} does not publish {variable!r}. Models that do: "
            f"{have or 'none'}.")
    band, units = entry
    if stat and key.startswith("weathernext"):
        band = band.replace("_mean", f"_{stat}")

    def _sel(img):
        if resample:
            img = img.resample(resample)
        out = img.select([band], [variable])
        if to_celsius and units == "K":
            out = out.subtract(273.15).rename(variable)
        return out.copyProperties(
            img, ["system:time_start", "forecast_time", "forecast_hours",
                  "forecast_hour", "creation_time", "start_time", "end_time"])

    return ee.ImageCollection(collection).map(_sel)
