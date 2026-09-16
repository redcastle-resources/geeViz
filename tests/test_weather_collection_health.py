"""The registered collections are live, and not deprecated.

This is the failure that retired ``WeatherNextTimeLapse.py``. It was
built on the WeatherNext Graph and Gen collections; both were deprecated
in place and both stopped publishing on 2026-07-29. Nothing raised --
a deprecated Earth Engine id keeps resolving. The example found no
recent run, printed "usually transient, try again later", and exited
successfully, and would have gone on doing that indefinitely.

So neither half of that is detectable by asking whether the code runs.
Both have to be asserted directly:

* **not deprecated** -- the client emits a ``DeprecationWarning`` that
  nothing in a normal run looks at.
* **still publishing** -- a deprecated id usually keeps serving its
  back catalogue, so "the collection has images" is not the question.
  The question is whether it has RECENT ones.

A failure here is not necessarily a bug in geeViz; it is a bug in what
geeViz points at, which is the only kind the library cannot fix at
runtime.
"""
import datetime
import warnings

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


# Generous: a model can miss a cycle, and WeatherNext is gated so a
# transient permission blip should not read as a dead dataset. Seven days
# is far short of the 47 the retired collections had gone dark for.
STALE_DAYS = 7


# Spelled out rather than read from wx.MODELS, because a parametrize list
# is built at COLLECTION time -- and importing geeViz.weather pulls in
# getImagesLib, which constructs an ee.ImageCollection at import and so
# needs an initialized client. At collection there is not one yet.
# test_every_registered_model_is_covered keeps this honest.
MODEL_KEYS = ["euro", "gfs", "weathernext", "weathernext_stations"]


def _newest(cid, days):
    """Newest image within ``days``, or None. Bounded on purpose.

    ``aggregate_max`` over the whole collection is a reduce across every
    image ever published and takes minutes; a filter plus a descending
    ``limit(1)`` answers the same question against an index.
    """
    import ee
    lo = ee.Date(datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(days=days)).millis()
    got = (ee.ImageCollection(cid)
           .filter(ee.Filter.gt("system:time_start", lo))
           .limit(1, "system:time_start", False)
           .aggregate_array("system:time_start").getInfo())
    return got[0] if got else None


@pytest.mark.parametrize("key", MODEL_KEYS)
def test_registered_collection_is_not_deprecated(key):
    import ee
    import geeViz.weather as wx
    cid = wx.MODELS[key]["collection"]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ee.ImageCollection(cid).limit(1).size().getInfo()
    dep = [w for w in caught if issubclass(w.category, DeprecationWarning)
           and "deprecated asset" in str(w.message)]
    assert not dep, (
        f"MODELS[{key!r}] points at a DEPRECATED id.\n  {cid}\n"
        f"  {' '.join(str(dep[0].message).split())}\n"
        f"A deprecated id keeps working, so nothing else will tell you.")


@pytest.mark.parametrize("key", MODEL_KEYS)
def test_registered_collection_is_still_publishing(key):
    import geeViz.weather as wx
    cid = wx.MODELS[key]["collection"]
    newest = _newest(cid, STALE_DAYS)
    if newest is None:
        # Say HOW dead, not just that it is -- "no data in 7 days" and
        # "no data since July" call for different responses.
        far = _newest(cid, 400)
        when = ("nothing in 400 days" if far is None else
                datetime.datetime.fromtimestamp(
                    far / 1000, datetime.timezone.utc).strftime("%Y-%m-%d"))
        pytest.fail(
            f"MODELS[{key!r}] has published nothing in {STALE_DAYS} days.\n"
            f"  {cid}\n  newest image: {when}\n"
            f"Check the catalog for a replacement id — this is how the "
            f"WeatherNext Graph and Gen collections went dark.")


def test_the_check_would_actually_catch_a_dead_collection():
    """Guard the guard.

    Both assertions above pass trivially against a healthy catalog, so
    this pins them to a case known to be bad: the Graph collection the
    retired example used, deprecated and dark since 2026-07-29.

    Without this, the pair could stop testing anything -- a typo'd
    warning category or a filter that silently matches everything -- and
    stay green for as long as the live ids happen to be fine.
    """
    import ee
    dead = "projects/gcp-public-data-weathernext/assets/59572747_4_0"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ee.ImageCollection(dead).limit(1).size().getInfo()
    dep = [w for w in caught if issubclass(w.category, DeprecationWarning)
           and "deprecated asset" in str(w.message)]
    assert dep, "the deprecation probe no longer detects a deprecated id"
    assert _newest(dead, STALE_DAYS) is None, (
        "the Graph collection is publishing again — if that is real, this "
        "test needs a different dead id, not deleting")


def test_every_registered_model_is_covered():
    """MODEL_KEYS is a hand-written copy of wx.MODELS' keys, so a model
    registered later would otherwise never be health-checked -- silently,
    which is the same class of failure the whole module exists to catch.
    """
    import geeViz.weather as wx
    assert sorted(wx.MODELS) == sorted(MODEL_KEYS), (
        "wx.MODELS changed; update MODEL_KEYS so the new collection is "
        "checked for deprecation and staleness too")
