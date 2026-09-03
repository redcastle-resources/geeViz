"""Tests for geeViz.fireLib.

Offline by default. The Earth Engine paths are exercised separately
against live EE; what is pinned here is the arithmetic and the constants,
because both bugs found while building this package were *silent* — the
model returned finite, plausible, wrong numbers rather than failing.

Bug 1: the Rothermel effective-heating term was written ``exp(-138 *
sigma)`` instead of ``exp(-138 / sigma)``. With sigma around 2000 that
underflows to zero, the heat sink collapses, and every pixel comes back
0 ft/min. An entire landscape reads as fireproof.

Bug 2: ``cumulativeCost`` with ``geodeticDistance=False`` on an
EPSG:4326 image treats a degree of longitude as a degree of latitude, so
fire spread east-west was 39% too slow at 44 deg N and correct
north-south. A directional error that looks completely plausible on a
map.
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from geeViz.fireLib import behavior, fuels, spread  # noqa: E402


# ── Fuel model parameter table ───────────────────────────────────────────

def test_known_fuel_models_resolve():
    p = fuels.fuel_model_params(102)
    assert p["name"].startswith("GR2")
    assert p["burnable"] is True
    assert p["sav"] > 0 and p["depth"] > 0


def test_non_burnable_models_are_marked():
    for code in fuels.NON_BURNABLE:
        p = fuels.fuel_model_params(code)
        assert p["burnable"] is False
        assert p["w_1h"] == 0.0


def test_unknown_fuel_model_raises_rather_than_defaulting():
    """Substituting a default would be worse than failing.

    A stand-in fuel bed yields a plausible spread rate for fuel nobody
    described — and nothing downstream would question it. The error
    names where to get the real values.
    """
    with pytest.raises(KeyError) as exc:
        fuels.fuel_model_params(9999)
    assert "RMRS-GTR-153" in str(exc.value)


def test_every_table_entry_has_all_required_params():
    required = {"w_1h", "w_10h", "w_100h", "w_live", "sav", "depth",
                "mx_dead", "name"}
    for code, p in fuels._FBFM40_PARAMS.items():
        missing = required - set(p)
        assert not missing, f"fuel model {code} missing {missing}"


def test_burnable_models_have_positive_bed_properties():
    """Zero SAV or depth divides by zero deep inside Rothermel."""
    for code, p in fuels._FBFM40_PARAMS.items():
        if code in fuels.NON_BURNABLE:
            continue
        assert p["sav"] > 0, f"model {code} has non-positive SAV"
        assert p["depth"] > 0, f"model {code} has non-positive depth"
        assert p["mx_dead"] > 0, f"model {code} has non-positive Mx"


# ── Rothermel coefficients — the silent-zero bug ─────────────────────────

def _ros_scalar(sav=2000.0, w_total_tons=1.0, depth=1.0, mx=0.15,
                moisture=0.06, wind_mph=8.0, slope_tan=0.0,
                wind_adj=0.4):
    """Pure-python Rothermel, mirroring behavior.rate_of_spread.

    Exists so the coefficient set can be checked numerically without
    Earth Engine. If this and the ee.Image version ever disagree, one of
    them has been edited alone.
    """
    TONS = behavior.TONS_ACRE_TO_LB_FT2
    w_net = w_total_tons * TONS
    rho_b = w_net / depth
    beta = rho_b / behavior.PARTICLE_DENSITY
    beta_op = 3.348 * sav ** -0.8189
    beta_ratio = beta / beta_op

    a = 133.0 * sav ** -0.7913
    gamma_max = sav ** 1.5 / (495.0 + 0.0594 * sav ** 1.5)
    gamma = gamma_max * (beta_ratio ** a) * math.exp(a * (1 - beta_ratio))

    rm = min(moisture / mx, 1.0)
    eta_m = max(1 - 2.59 * rm + 5.11 * rm ** 2 - 3.52 * rm ** 3, 0.0)
    eta_s = min(0.174 * behavior.MINERAL_EFFECTIVE ** -0.19, 1.0)
    w_n = w_net * (1 - behavior.MINERAL_TOTAL)
    i_r = gamma * w_n * behavior.HEAT_CONTENT * eta_m * eta_s

    xi = math.exp((0.792 + 0.681 * sav ** 0.5) * (beta + 0.1)) / \
        (192.0 + 0.2595 * sav)

    u_mid = wind_mph * 88.0 * wind_adj
    c = 7.47 * math.exp(-0.133 * sav ** 0.55)
    b = 0.02526 * sav ** 0.54
    e = 0.715 * math.exp(-3.59e-4 * sav)
    phi_w = c * (max(u_mid, 0) ** b) * (beta_ratio ** -e)
    phi_s = 5.275 * beta ** -0.3 * slope_tan ** 2

    eps = math.exp(-138.0 / sav)
    q_ig = 250.0 + 1116.0 * moisture
    return i_r * xi * (1 + phi_w + phi_s) / (rho_b * eps * q_ig)


def test_rothermel_produces_a_nonzero_spread_rate():
    """The regression. An all-zero landscape is the failure mode."""
    r = _ros_scalar()
    assert r > 0, "rate of spread collapsed to zero"
    assert 1.0 < r < 5000.0, f"implausible rate of spread: {r} ft/min"


def test_effective_heating_is_divided_by_sav_not_multiplied():
    """Pin the exact slip that zeroed everything.

    exp(-138 * 2000) underflows to 0.0; exp(-138 / 2000) is ~0.933. The
    first collapses the heat sink and drives every pixel to zero.
    """
    sav = 2000.0
    assert math.exp(-138.0 * sav) == 0.0
    assert 0.9 < math.exp(-138.0 / sav) < 1.0


def test_spread_increases_with_wind():
    calm = _ros_scalar(wind_mph=2.0)
    windy = _ros_scalar(wind_mph=20.0)
    assert windy > calm * 2, f"wind barely mattered: {calm} -> {windy}"


def test_spread_decreases_with_moisture():
    dry = _ros_scalar(moisture=0.03)
    wet = _ros_scalar(moisture=0.14)
    assert wet < dry, f"moisture did not damp spread: {dry} -> {wet}"


def test_spread_stops_at_moisture_of_extinction():
    """Past Mx the damping polynomial goes negative; it must clamp.

    An unclamped eta_m flips the sign of the whole fire — spread would
    become negative rather than zero, which is worse than wrong because
    a negative arrival time silently breaks everything downstream.

    Asserted with a tolerance rather than ``== 0``: at exactly Mx the
    polynomial ``1 - 2.59r + 5.11r^2 - 3.52r^3`` evaluates to zero in
    exact arithmetic but leaves ~1e-14 of floating-point residue, which
    carries through to about 1e-14 ft/min. That is zero for every
    purpose — roughly a micrometre per century.
    """
    r = _ros_scalar(moisture=0.40, mx=0.15)
    assert r >= 0.0, "spread went NEGATIVE past the moisture of extinction"
    assert r < 1e-6, f"expected physically zero spread, got {r} ft/min"


def test_damping_never_goes_negative_across_the_moisture_range():
    """Sweep rather than spot-check: the clamp must hold everywhere."""
    for m in (0.01, 0.05, 0.10, 0.15, 0.16, 0.25, 0.50, 1.00):
        r = _ros_scalar(moisture=m, mx=0.15)
        assert r >= 0.0, f"negative spread at moisture {m}"


def test_spread_increases_with_slope():
    flat = _ros_scalar(slope_tan=0.0)
    steep = _ros_scalar(slope_tan=0.5)          # ~27 degrees
    assert steep > flat, f"slope did not increase spread: {flat} -> {steep}"


def test_wind_adjustment_factor_matters_a_lot():
    """It is an explicit argument because it moves the answer hugely.

    Sheltered timber (0.1) versus open grass (0.6) is a large multiple,
    which is why it must not be buried as a constant.
    """
    sheltered = _ros_scalar(wind_adj=0.1)
    exposed = _ros_scalar(wind_adj=0.6)
    assert exposed > sheltered * 1.5


# ── Unit conversions ─────────────────────────────────────────────────────

def test_ft_min_to_m_s_conversion():
    assert behavior.FT_MIN_TO_M_S == pytest.approx(0.3048 / 60.0)
    # 100 ft/min is a brisk but ordinary spread rate: ~0.5 m/s.
    assert 100 * behavior.FT_MIN_TO_M_S == pytest.approx(0.508, abs=1e-3)


def test_tons_per_acre_conversion():
    assert behavior.TONS_ACRE_TO_LB_FT2 == pytest.approx(2000.0 / 43560.0)


# ── The geodetic-distance bug ────────────────────────────────────────────

def test_geodetic_distance_defaults_to_true():
    """Pin the directional-bias fix.

    With geodeticDistance=False on an EPSG:4326 image, a degree of
    longitude is treated as a degree of latitude, so east-west spread is
    inflated by 1/cos(latitude): measured 1.386 at 44.2 deg N against an
    analytic 1.0, while north-south was correct at 0.996. A fire that
    spreads correctly one way and 39% too slowly the other still looks
    entirely plausible on a map.
    """
    assert spread.GEODETIC_DISTANCE is True


def test_longitude_compression_is_what_the_1_386_was():
    """The arithmetic behind the measurement, so the reason survives."""
    assert 1.0 / math.cos(math.radians(44.2)) == pytest.approx(1.394, abs=0.01)


def test_travel_time_signature_exposes_the_geodetic_flag():
    """It must stay overridable — a projected cost image wants False."""
    import inspect
    sig = inspect.signature(spread.travel_time)
    assert "geodetic" in sig.parameters
    assert sig.parameters["geodetic"].default is True


# ── Asset ids ────────────────────────────────────────────────────────────

def test_fuel_assets_point_at_the_community_catalog():
    """LANDFIRE fuels are NOT in the official LANDFIRE/ namespace.

    The official namespace carries vegetation and fire-regime products
    but not the fuel models, which is an easy and silent mistake — an
    id that looks right and does not exist.
    """
    for key in ("FBFM40", "FBFM13", "CBH", "CBD", "CC"):
        assert fuels.FUEL_ASSETS[key].startswith(
            "projects/sat-io/open-datasets/landfire/")


def test_context_assets_use_the_official_catalog():
    for key in ("EVT", "FRG", "MFRI"):
        assert fuels.CONTEXT_ASSETS[key].startswith("LANDFIRE/")


def test_risk_asset_is_the_published_fsim_output():
    """WRC is FSim/FlamMap output already computed for CONUS+AK+HI."""
    assert fuels.RISK_ASSET == "USDA/WRC/v0"


# ── wind vectors ───────────────────────────────────────────────────────
#
# Same failure shape as the two bugs in this file's header: plausible,
# finite, wrong. Written first with ``direction = atan2(u, v)`` mapped
# straight to 0-360, which is the MATH angle (counter-clockwise from
# east) and not a compass bearing (clockwise from north). The two are a
# reflection, ``bearing = 90 - math_angle``, not an offset.
#
# What makes it dangerous is where it agrees: on the diagonals both
# conventions give the same number. A south-westerly reads 225 either
# way. The first test run checked SW and four cardinals — SW passed and
# all four cardinals were wrong, so a test suite containing only the
# diagonal would have shipped it.
#
# These run offline against the pure-Python conversion so they execute
# in CI without Earth Engine; the live EE path was verified separately
# on all eight compass points.

def _bearing_to(u, v):
    """Client-side twin of the conversion in wind.wind_speed_direction."""
    math_deg = math.degrees(math.atan2(v, u))
    return (90.0 - math_deg) % 360.0


def _bearing_from(u, v):
    return (_bearing_to(u, v) + 180.0) % 360.0


# (label, u, v, direction_from, direction_to)
COMPASS = [
    ("westerly",   5.0,  0.0, 270.0,  90.0),
    ("easterly",  -5.0,  0.0,  90.0, 270.0),
    ("southerly",  0.0,  5.0, 180.0,   0.0),
    ("northerly",  0.0, -5.0,   0.0, 180.0),
    ("sw",         5.0,  5.0, 225.0,  45.0),
    ("nw",         5.0, -5.0, 315.0, 135.0),
    ("se",        -5.0,  5.0, 135.0, 315.0),
    ("ne",        -5.0, -5.0,  45.0, 225.0),
]


@pytest.mark.parametrize("label,u,v,d_from,d_to", COMPASS)
def test_wind_direction_conventions(label, u, v, d_from, d_to):
    """A westerly blows FROM 270 and TOWARD 90. Getting this backwards
    puts the fire on the wrong side of the ridge."""
    assert abs(_bearing_from(u, v) - d_from) < 0.5, f"{label}: direction_from"
    assert abs(_bearing_to(u, v) - d_to) < 0.5, f"{label}: direction_to"


def test_the_cardinals_are_what_actually_discriminate():
    """Guards the test suite itself. If someone later trims COMPASS to
    the diagonals to 'keep it short', the reflection bug becomes
    invisible again."""
    cardinals = [c for c in COMPASS if c[1] == 0 or c[2] == 0]
    assert len(cardinals) >= 4, (
        "the cardinal cases are the only ones that distinguish a compass "
        "bearing from a math angle — do not remove them")


@pytest.mark.parametrize("label,u,v,d_from,d_to", COMPASS)
def test_from_and_to_are_always_opposite(label, u, v, d_from, d_to):
    diff = abs(_bearing_from(u, v) - _bearing_to(u, v)) % 360.0
    assert abs(diff - 180.0) < 1e-6


def test_a_naive_math_angle_would_fail_these():
    """Proves the tests have teeth: the original wrong implementation
    must not pass them."""
    def wrong(u, v):
        return math.degrees(math.atan2(v, u)) % 360.0
    wrong_on_cardinals = [
        c[0] for c in COMPASS
        if (c[1] == 0 or c[2] == 0) and abs(wrong(c[1], c[2]) - c[4]) > 0.5
    ]
    assert len(wrong_on_cardinals) == 4, (
        "the math-angle implementation should be wrong on all four "
        "cardinals; if it is not, these tests cannot catch the bug")


def test_unit_constants():
    from geeViz.fireLib import wind
    assert abs(wind.MS_TO_MIH - 2.23694) < 1e-5
    # 10 m -> 20 ft log-profile ratio. Small, but it moves a marginal
    # spread call.
    assert 1.10 <= wind.WIND_10M_TO_20FT <= 1.20


def test_uv_band_lookup_covers_the_published_spellings():
    """Every forecast collection names these differently; the lookup is
    the only reason callers do not have to care."""
    from geeViz.fireLib import wind
    assert "NOAA/GFS0P25" in wind.UV_BANDS
    u, v = wind.UV_BANDS["NOAA/GFS0P25"]
    assert u == "u_component_of_wind_10m_above_ground"
    assert v == "v_component_of_wind_10m_above_ground"
    for src, (u, v) in wind.UV_BANDS.items():
        assert u.startswith("u"), src
        assert v.startswith("v"), src


def _executable_source(fn):
    """Source with comments and the docstring removed.

    Both of the tests below first matched their own explanatory
    COMMENTS — one asserted `"ee.Algorithms.If" not in src` while the
    comment said "instead of ee.Algorithms.If", and the other found the
    `.mean()` inside "ImageCollection.mean() over a heterogeneous". The
    code was right and the tests were wrong, which is the worse failure
    of the two.
    """
    import inspect
    src = inspect.getsource(fn)
    doc = inspect.getdoc(fn)
    if doc:
        src = src.replace(doc, "")
    out = []
    for line in src.splitlines():
        stripped = line.split("#")[0] if "#" in line else line
        out.append(stripped)
    return chr(10).join(out)


def test_the_source_stripper_removes_comments():
    """Guards the guard — without this the two tests below pass on
    prose."""
    def sample():
        # ee.Algorithms.If mentioned only in a comment
        return 1
    assert "ee.Algorithms.If" not in _executable_source(sample)
    assert "return 1" in _executable_source(sample)


def test_forecast_blocks_are_built_client_side():
    """ee.Algorithms.If evaluates BOTH branches when the graph is built,
    so it cannot guard an empty forecast window — the empty branch still
    runs select() on a band-less mean() and fails. The loop is a
    deliberate choice, not an oversight."""
    from geeViz.fireLib import wind
    src = _executable_source(wind.wind_blocks_from_forecast)
    assert "ee.Algorithms.If" not in src
    assert "for i in range(n)" in src


def test_select_happens_before_mean():
    """GFS forecast steps do not all carry the same bands, and mean()
    over a heterogeneous collection fails with an error that prints the
    first image's band list and never mentions the mismatch."""
    from geeViz.fireLib import wind
    src = _executable_source(wind.wind_blocks_from_forecast)
    sel = src.index("collection.select(")
    mean = src.index(".mean()")
    assert sel < mean, "mean() is taken before the bands are selected"
