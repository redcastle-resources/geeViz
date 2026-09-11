"""Wind as a vector — speed, direction, and something you can look at.

The rest of this package treats wind as a **scalar**: ``rate_of_spread``
takes ``wind_speed_20ft`` in mi/h and ``spread_with_wind_blocks`` chains
periods of it. That is deliberate and documented — ``cumulativeCost``
assigns cost per pixel, not per edge, so Tier 2 cannot express "cheap
downwind, expensive upwind" no matter what direction it is handed.

But wind is a vector everywhere it is *published*, and the direction is
the part a person actually wants to see. Forecast collections carry it
as **u/v components** rather than speed and bearing, so every project
rewrites the same ``hypot`` / ``atan2`` pair. One such copy used to live
in ``examples/weather_forecast_examples.ipynb``, where nothing could
import it — and it was wrong: its direction was
``(atan2(v, u) / pi + 1) * 180``, the MATH angle rescaled to 0..360
rather than a compass bearing, which is right on the diagonals and wrong
on all four cardinals. That notebook now calls :mod:`geeViz.weather`,
which routes here.

This module is the importable version, plus the two things it always
gets used for: sampling the field down to a drawable grid, and turning
those samples into map geometry.

**Direction convention — read this before trusting a number.**
Meteorology reports the direction wind blows *from* ("a westerly" comes
from the west, 270°). Fire spread cares where it is going *to*. The two
differ by exactly 180°, which is the kind of error that looks plausible
on a map and puts the fire on the wrong side of the ridge. Both are
returned, named unambiguously, and never abbreviated to "direction":

    direction_from  meteorological, 0 = from the north, 90 = from the east
    direction_to    where a parcel travels, = direction_from + 180

**On rendering.** ``ee.FeatureCollection.style()`` has ``pointShape``
but no rotation, so a rotated arrow glyph is not available server-side.
:func:`wind_barbs` therefore draws real line segments — a shaft along
the vector with a two-stroke head — which needs no rotation support and
renders anywhere geeViz renders vectors. It is a static barb field, not
the animated particle advection windy.com does; that is a client-side
canvas effect over a u/v texture and does not belong in Earth Engine.
"""

import math

#: Forecast/reanalysis collections and their u/v band names. Every one of
#: these spells it differently, which is most of why this lookup exists.
#: Verified against the live catalog.
UV_BANDS = {
    "NOAA/GFS0P25": (
        "u_component_of_wind_10m_above_ground",
        "v_component_of_wind_10m_above_ground",
    ),
    "ECMWF/NRT_FORECAST/IFS/OPER": (
        "u_component_of_wind_10m_sfc",
        "v_component_of_wind_10m_sfc",
    ),
    "ECMWF/ERA5_LAND/HOURLY": (
        "u_component_of_wind_10m",
        "v_component_of_wind_10m",
    ),
    "ECMWF/ERA5/HOURLY": (
        "u_component_of_wind_10m",
        "v_component_of_wind_10m",
    ),
}

#: Above the surface layer GFS also carries boundary-layer wind, which is
#: closer to what drives a plume-dominated run than the 10 m value.
UV_BANDS_PBL = {
    "NOAA/GFS0P25": (
        "u_component_of_wind_planetary_boundary_layer",
        "v_component_of_wind_planetary_boundary_layer",
    ),
}

#: 20-ft wind is the Rothermel input; forecasts publish 10 m. The
#: log-profile ratio between them over open ground is ~1.15, and the
#: number is small enough that people skip it and large enough to matter
#: on a marginal spread call.
WIND_10M_TO_20FT = 1.15

MS_TO_MIH = 2.23694


def _uv_bands_for(image, u_band=None, v_band=None):
    """Resolve the u/v band names for ``image``.

    Explicit names win. Otherwise the image's own bands are matched
    against every spelling in :data:`UV_BANDS`, so a caller who already
    has an image does not have to say where it came from.
    """
    if u_band and v_band:
        return u_band, v_band
    names = set(image.bandNames().getInfo())
    for u, v in list(UV_BANDS.values()) + list(UV_BANDS_PBL.values()):
        if u in names and v in names:
            return u, v
    if {"u", "v"} <= names:
        return "u", "v"
    raise ValueError(
        "Could not find u/v wind bands on this image. Pass u_band= and "
        f"v_band= explicitly. Bands present: {sorted(names)[:12]}"
    )


def wind_uv(image, u_band=None, v_band=None):
    """Return just the wind components, renamed to ``u`` / ``v``.

    Args:
        image: ``ee.Image`` from any collection in :data:`UV_BANDS`, or
            one already carrying ``u`` / ``v``.
        u_band, v_band: Override the band lookup.

    Returns:
        ``ee.Image`` with bands ``u`` (eastward m/s) and ``v``
        (northward m/s).
    """
    u_band, v_band = _uv_bands_for(image, u_band, v_band)
    return image.select([u_band, v_band], ["u", "v"])


def wind_speed_direction(image, u_band=None, v_band=None, *,
                         to_mih=False, to_20ft=False):
    """Speed and BOTH direction conventions from u/v components.

    Args:
        image: ``ee.Image`` carrying wind components.
        u_band, v_band: Override the band lookup.
        to_mih: Return speed in mi/h instead of m/s. Use this when the
            value is headed for :func:`~geeViz.fireLib.behavior.
            rate_of_spread`, which is unit-bearing English.
        to_20ft: Scale a 10 m wind to 20 ft by
            :data:`WIND_10M_TO_20FT`. Only valid if the input really is
            10 m wind — applying it to boundary-layer wind overstates
            the surface value.

    Returns:
        ``ee.Image`` with bands:

        * ``speed`` — magnitude, m/s unless ``to_mih``
        * ``direction_from`` — degrees the wind blows FROM
          (meteorological; 270 = a westerly)
        * ``direction_to`` — degrees it blows TOWARD; this is the one
          fire spread follows

    Note:
        ``direction_from`` and ``direction_to`` differ by 180°. Naming
        one of them "direction" and moving on is how a barb field ends
        up pointing backwards.
    """
    uv = wind_uv(image, u_band, v_band)
    u = uv.select("u")
    v = uv.select("v")

    speed = u.hypot(v)
    if to_20ft:
        speed = speed.multiply(WIND_10M_TO_20FT)
    if to_mih:
        speed = speed.multiply(MS_TO_MIH)
    speed = speed.rename("speed")

    # ``u.atan2(v)`` is atan2(y=v, x=u): the MATH angle, counter-clockwise
    # from east. A compass bearing is clockwise from north, so the two
    # are related by ``bearing = 90 - math_angle`` — a reflection, not an
    # offset. Adding a constant instead is the classic error, and it is
    # invisible on the diagonals: a south-westerly reads 225° either way,
    # so a test that only checks SW passes while N/S/E/W are all wrong.
    math_deg = u.atan2(v).multiply(180.0 / math.pi)
    bearing_to = math_deg.multiply(-1).add(90)
    direction_to = bearing_to.add(360).mod(360).rename("direction_to")
    direction_from = (bearing_to.add(180).add(360).mod(360)
                      .rename("direction_from"))

    return speed.addBands(direction_from).addBands(direction_to)


def wind_grid(image, region, *, grid_m=12000, u_band=None, v_band=None):
    """Sample the wind field onto a regular grid — the downsampling step.

    A forecast grid is far denser than anything worth drawing: GFS is
    0.25°, and a state-sized region is thousands of cells. Drawing all of
    them produces a black smear. ``scale=grid_m`` on ``sample`` is the
    whole trick — Earth Engine reduces the field to that resolution and
    returns one point per cell.

    Args:
        image: ``ee.Image`` carrying wind components.
        region: ``ee.Geometry`` to sample within.
        grid_m: Spacing in meters — one arrow per cell. 12 km over a
            county-to-state view is legible; drop it for a small AOI.

    Returns:
        ``ee.FeatureCollection`` of points, each with ``u``, ``v``,
        ``speed``, ``direction_from`` and ``direction_to``.
    """
    uv = wind_uv(image, u_band, v_band)
    sd = wind_speed_direction(uv)
    return uv.addBands(sd).sample(
        region=region, scale=grid_m, geometries=True, dropNulls=True,
    )


def wind_barbs(image, region, *, grid_m=12000, seconds=900,
               head_frac=0.3, head_deg=25.0,
               u_band=None, v_band=None):
    """Draw the wind field as arrows you can put straight on a map.

    Each grid sample becomes a shaft from the sample point along the
    wind vector, plus two short strokes forming an arrowhead at the
    downwind end. Shaft length is proportional to speed, so the field
    reads the way a barb field should: long arrows are fast.

    Line segments rather than glyphs because ``FeatureCollection.style()``
    supports ``pointShape`` but not rotation — there is no way to spin a
    marker to a bearing server-side. Segments need no rotation support at
    all.

    Args:
        image: ``ee.Image`` carrying wind components.
        region: ``ee.Geometry`` to cover.
        grid_m: Arrow spacing in meters.
        seconds: Shaft length expressed as travel time — the arrow spans
            where a parcel would go in this many seconds. This is what
            makes length physical instead of an arbitrary scale factor:
            at 900 s a 10 m/s wind draws a 9 km shaft.
        head_frac: Arrowhead length as a fraction of the shaft.
        head_deg: Half-angle of the head, degrees.

    Returns:
        ``ee.FeatureCollection`` of ``LineString`` features carrying
        ``speed``, ``direction_from``, ``direction_to``. Style it with
        ``.style(color=..., width=1)`` or drive a palette off ``speed``.

    Example:
        >>> gfs = ee.ImageCollection("NOAA/GFS0P25").filterDate(a, b).first()
        >>> barbs = fl.wind_barbs(gfs, aoi, grid_m=12000)
        >>> Map.addLayer(barbs.style(color="white", width=1), {}, "Wind")
    """
    import ee

    pts = wind_grid(image, region, grid_m=grid_m,
                    u_band=u_band, v_band=v_band)

    # Degrees per meter varies with latitude for longitude and is
    # effectively constant for latitude. Doing this per-feature rather
    # than with a single scale factor keeps arrows the right length at
    # the top and bottom of a tall AOI.
    M_PER_DEG_LAT = 111320.0
    half = head_deg * math.pi / 180.0

    def _barb(f):
        coords = ee.List(f.geometry().coordinates())
        lon = ee.Number(coords.get(0))
        lat = ee.Number(coords.get(1))
        u = ee.Number(f.get("u"))
        v = ee.Number(f.get("v"))

        m_per_deg_lon = lat.multiply(math.pi / 180.0).cos() \
                           .multiply(M_PER_DEG_LAT).max(1.0)

        dlon = u.multiply(seconds).divide(m_per_deg_lon)
        dlat = v.multiply(seconds).divide(M_PER_DEG_LAT)
        tip_lon = lon.add(dlon)
        tip_lat = lat.add(dlat)

        # Arrowhead: two strokes back from the tip, rotated +/- head_deg
        # off the reversed shaft. Rotation is done on the offset vector
        # in degree space, which is why it uses the same per-latitude
        # scaling as the shaft.
        bx = dlon.multiply(-head_frac)
        by = dlat.multiply(-head_frac)
        cos_h, sin_h = math.cos(half), math.sin(half)
        lx = bx.multiply(cos_h).subtract(by.multiply(sin_h))
        ly = bx.multiply(sin_h).add(by.multiply(cos_h))
        rx = bx.multiply(cos_h).add(by.multiply(sin_h))
        ry = by.multiply(cos_h).subtract(bx.multiply(sin_h))

        geom = ee.Geometry.MultiLineString([
            [[lon, lat], [tip_lon, tip_lat]],
            [[tip_lon, tip_lat], [tip_lon.add(lx), tip_lat.add(ly)]],
            [[tip_lon, tip_lat], [tip_lon.add(rx), tip_lat.add(ry)]],
        ])
        return ee.Feature(geom, {
            "speed": f.get("speed"),
            "direction_from": f.get("direction_from"),
            "direction_to": f.get("direction_to"),
        })

    return pts.map(_barb)


def wind_blocks_from_forecast(collection, region, *, start, end,
                              block_hours=6, u_band=None, v_band=None,
                              moisture_1h=0.06):
    """Turn a forecast into the ``blocks`` list ``spread_with_wind_blocks``
    expects.

    Averages each period over ``region`` and converts to the units and
    key names that function wants — 20-ft wind in mi/h, duration in
    seconds. ``direction_to`` rides along so a caller writing their own
    ``ros_fn`` can use it, even though the default isotropic spread
    ignores it.

    Args:
        collection: ``ee.ImageCollection`` of forecast steps.
        region: ``ee.Geometry`` to average over.
        start, end: ``ee.Date`` or ISO strings bounding the forecast.
        block_hours: Length of each wind period.

    Returns:
        list[dict] — ``wind_speed`` (mi/h at 20 ft), ``duration_s``,
        ``moisture_1h``, ``direction_to`` (degrees).

    Note:
        Spread within a block stays isotropic. This makes the SHIFTS
        available, which is what chaining blocks is for; it does not
        make ``cumulativeCost`` directional.
    """
    import ee

    # Resolve band names once, on the client. Doing it inside a mapped
    # function fails: the image there is a server-side placeholder with
    # no bands to fetch.
    u_band, v_band = _uv_bands_for(collection.first(), u_band, v_band)

    # SELECT BEFORE MEAN. GFS forecast steps do not all carry the same
    # band list, and ImageCollection.mean() over a heterogeneous
    # collection fails with an error that prints the first image's 15
    # bands and says nothing about the mismatch.
    uv_coll = collection.select([u_band, v_band], ["u", "v"])

    start = ee.Date(start)
    end = ee.Date(end)
    n = int(ee.Number(end.difference(start, "hour"))
            .divide(block_hours).ceil().getInfo())

    # Deliberately a CLIENT-side loop. It is one reduceRegion per block
    # and blocks number in the tens, so the round trips are cheap — and
    # an empty window is then just an `if`, instead of ee.Algorithms.If,
    # which evaluates BOTH branches when the graph is built and so cannot
    # guard against the empty case at all.
    blocks = []
    for i in range(n):
        b0 = start.advance(i * block_hours, "hour")
        b1 = b0.advance(block_hours, "hour")
        sub = uv_coll.filterDate(b0, b1)
        if sub.size().getInfo() == 0:
            continue
        sd = wind_speed_direction(sub.mean(), "u", "v",
                                  to_mih=True, to_20ft=True)
        s = sd.select(["speed", "direction_to"]).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region,
            scale=27830, bestEffort=True, maxPixels=1e9,
        ).getInfo()
        if s.get("speed") is None:
            continue
        blocks.append({
            "wind_speed": s["speed"],
            "direction_to": s["direction_to"],
            "duration_s": block_hours * 3600,
            "moisture_1h": moisture_1h,
        })
    return blocks
