"""A band that does not exist yet should say so, not fail on the server.

GFS does not have a stable band list, and it varies along two axes.

By DATE, at one boundary rather than on a rolling window. Bisected
against the live collection on 2026-09-23: an image at 2025-01-14
carries 9 bands, one at 2025-01-15 carries 22. ``precipitation_rate``
and ``dew_point_temperature_2m_above_ground`` both arrive in that single
change.

And by LEAD. A lead-0 analysis is a short image in either era -- 6 bands
in 2024, 15 today -- and in particular never carries
``total_precipitation_surface``, because an accumulation over the
forecast interval is undefined at the analysis hour rather than zero.

Asking for ``precipitation`` over an older window used to produce::

    EEException: Collection.toList: Error in map(ID=2024092718F000):
    Image.select: Band pattern 'precipitation_rate' did not match any
    bands. Available bands: [temperature_2m_above_ground, ...]

-- raised from inside a ``map()``, naming an image the caller never
asked for and a band list that means nothing without the table, and
saying nothing about what to do instead.

It is caught in Python now. The check is a date comparison, which
matters: ``getForecastData`` is otherwise fully lazy (measured at 7 ms,
zero round trips) and a ``bandNames().getInfo()`` to look before leaping
would add ~0.8 s to EVERY call to catch a case that is usually absent.
The tests below therefore also pin that laziness, because a correctness
fix that quietly made the common path 100x slower would be a bad trade
made invisibly.

Nothing is substituted automatically, and that is the other half. GFS
precipitation is an ACCUMULATION before the boundary and a RATE after --
different physical quantities in different units -- so swapping one for
the other silently would yield numbers wrong by whatever the interval
happens to be, while looking entirely plausible.
"""
import time

import pytest


def _ee_ready():
    """Is Earth Engine up?

    Imported inside the function, not at module level: importing
    ``geeViz.weather`` pulls in ``getImagesLib``, which builds an
    ``ee.ImageCollection`` AT IMPORT TIME and therefore needs EE already
    initialized. pytest imports every test module during collection,
    before any test runs -- so a module-level import here aborts the
    whole run with "client library not initialized", not just this file.
    """
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


@pytest.fixture(scope="module")
def wx():
    if not _ee_ready():
        pytest.skip("Earth Engine not reachable")
    return pytest.importorskip("geeViz.weather")


# Before the boundary, after it, and straddling it.
PAST = ("2024-09-26T00:00Z", "2024-09-27T23:59Z")
STRADDLE = ("2025-01-10", "2025-01-20")
RECENT = ("2026-09-19", "2026-09-21")


# ── the gate table itself ──────────────────────────────────────────────


def test_the_gated_bands_are_the_ones_that_moved(wx):
    """Two, both GFS, both at the same boundary because they arrived in
    one catalog change."""
    assert set(wx.BAND_AVAILABLE_FROM) == {
        ("precipitation", "gfs"), ("dewpoint_2m", "gfs")}
    assert {d for d, _ in wx.BAND_AVAILABLE_FROM.values()} == {"2025-01-15"}


def test_every_gated_variable_is_a_real_variable(wx):
    """A typo in the key silently disables the gate -- the lookup misses
    and the server error comes back."""
    for var, model in wx.BAND_AVAILABLE_FROM:
        assert var in wx.VARIABLES, f"{var!r} is not a VARIABLES key"
        assert model in wx.MODELS, f"{model!r} is not a model"
        assert isinstance(wx.VARIABLES[var][model], tuple), (
            f"{var}/{model} is gated but has no band to gate")


def test_the_advice_is_actionable(wx):
    """A message that names a dead end is worse than none. Neither entry
    may point at ``precipitation_accumulated`` on GFS, which this API
    cannot serve at any date."""
    for (var, model), (_since, advice) in wx.BAND_AVAILABLE_FROM.items():
        assert len(advice) > 40, f"{var}/{model}: advice is a stub"
        assert "'precipitation_accumulated'" not in advice, (
            f"{var}/{model} points at a variable getForecastData cannot "
            f"return for gfs -- it is published only at leads past the "
            f"analysis hour")


# ── the refusal ────────────────────────────────────────────────────────


@pytest.mark.parametrize("variable", ["precipitation", "dewpoint_2m"])
def test_an_older_window_is_refused_in_python(variable, wx):
    """The reported bug. A ValueError, not an EEException."""
    with pytest.raises(ValueError) as e:
        wx.getForecastData(*PAST, "gfs", variable=variable)
    msg = str(e.value)
    assert "2025-01-15" in msg, f"the boundary is not named: {msg}"
    assert "gfs" in msg


@pytest.mark.parametrize("variable", ["precipitation", "dewpoint_2m"])
def test_a_window_straddling_the_boundary_is_refused_too(variable, wx):
    """Checked against the START of the window, deliberately. The
    collection is mapped band-by-band, so ONE image without the band
    fails the whole request -- a straddling window is exactly as broken
    as one entirely before it, and half-working is the worse failure."""
    with pytest.raises(ValueError):
        wx.getForecastData(*STRADDLE, "gfs", variable=variable)


def test_the_refusal_names_the_band_the_caller_did_not_choose(wx):
    """The caller asked for 'precipitation'; the thing that is missing is
    'precipitation_rate'. Saying only the former sends them looking for
    a variable that is right there in the table."""
    with pytest.raises(ValueError, match="precipitation_rate"):
        wx.getForecastData(*PAST, "gfs", variable="precipitation")


# ── ...and only where it applies ───────────────────────────────────────


@pytest.mark.parametrize("variable", ["temperature_2m", "wind"])
def test_variables_that_span_the_record_still_work_on_old_windows(variable, wx):
    """The gate must not become a blanket refusal of old data. Wind is
    the one that matters most here -- the wind examples all use that
    window."""
    ic = wx.getForecastData(*PAST, "gfs", variable=variable)
    assert ic is not None


@pytest.mark.parametrize("variable", ["precipitation", "dewpoint_2m"])
def test_recent_windows_are_untouched(variable, wx):
    assert wx.getForecastData(*RECENT, "gfs", variable=variable) is not None


def test_other_models_are_not_gated(wx):
    """The boundary is a GFS catalog change. Nothing about it applies to
    ECMWF or WeatherNext."""
    assert wx.getForecastData(*RECENT, "euro",
                              variable="precipitation_accumulated") is not None


# ── the GFS accumulation, which this API cannot serve ──────────────────


def test_gfs_precipitation_accumulated_explains_itself(wx):
    """It is a real band, present across the whole record -- but only at
    leads past the analysis hour, and ``getForecastData`` returns the
    shortest lead. A tuple here would be a band that is never there.

    The table's idiom for that is a STRING: not "does not publish",
    which is untrue and sends people hunting, but the reason."""
    entry = wx.VARIABLES["precipitation_accumulated"]["gfs"]
    assert isinstance(entry, str), (
        "a tuple here promises a band getForecastData never selects")
    assert "lead" in entry.lower()
    with pytest.raises(ValueError, match="lead"):
        wx.getForecastData(*RECENT, "gfs",
                           variable="precipitation_accumulated")


# ── and the check stays free ───────────────────────────────────────────


def test_resolution_makes_no_round_trip(wx):
    """``getForecastData`` builds a server-side collection and returns.
    The gate is a date comparison and must not change that: a
    ``bandNames().getInfo()`` here would be ~0.8 s on every call.

    The threshold is loose on purpose -- this is catching a round trip,
    which is hundreds of milliseconds, not a slow machine."""
    t = time.time()
    wx.getForecastData(*RECENT, "gfs", variable="precipitation")
    assert time.time() - t < 0.25, "the resolver appears to hit the network"


def test_the_refusal_is_raised_before_any_server_work(wx):
    """It has to fail at the call, not on the first ``getInfo`` some
    lines later -- that is the whole difference from the EEException."""
    t = time.time()
    with pytest.raises(ValueError):
        wx.getForecastData(*PAST, "gfs", variable="precipitation")
    assert time.time() - t < 0.25
