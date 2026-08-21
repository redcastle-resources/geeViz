"""Isolation fixtures for the ``geeViz.eeAuth`` test suite.

Several tests in this package mutate state that outlives the test
function, so without the fixtures below the suite only passes in one
particular order. Two distinct leaks matter.

**1. The machine-wide detached proxy.**

``EECreds.stop()`` deliberately reaches outside the current process: it
reads the state file at ``<tmp>/.geeViz_eeauth_proxy.json``, kills
whatever PID it names, and deletes the file. Several tests call
``stop()`` on a throwaway ``EECreds()`` instance, and because that state
file is machine-global, every one of them tears down the developer's
real background proxy.

That matters because importing ``geeViz.geeView`` runs
``robustInitializer()`` -> ``EECreds.robust_init()`` ->
``ensure_started(mode="detached")`` at *import* time, and a handful of
tests import ``geeViz.geeView`` lazily inside the test body. Whichever
of those runs first either

* finds the state file intact and attaches in milliseconds -- which is
  what happens when the test runs alone, so it passes; or
* finds it gone and has to SPAWN a replacement, a subprocess whose
  ``import geeViz`` takes ~20s on a loaded machine while
  ``_spawn_detached`` gives up at 15s and raises -- so the import
  itself fails and the test errors out, which is what happens in a
  full-suite run.

That was the order-dependent failure in
``test_set_ee_api_upstream_round_trip`` and
``test_resolve_ee_tenant_precedence_request_then_referer_then_current``.
Both are pure-function tests that never wanted a proxy at all.

The fix has two halves:

* force ``GEEVIZ_EEAUTH_MODE=legacy`` for the whole session *before*
  anything can import ``geeViz.geeView``, so that import never spawns,
  attaches to, or kills a proxy; and
* redirect ``EECreds._detached_state_path`` at a per-session temp file,
  so a test calling ``stop()`` can never reach the real one.

**2. Process-global mutables.**

``geeView._EE_API_UPSTREAM``, the ``CURRENT_TENANT`` ContextVar and
``os.environ`` are all written by individual tests. They are
snapshotted and restored around every test so that any ordering works
(the suite is run both with ``-p no:randomly`` and with random order).
"""
import os

import pytest

# This assignment has to happen at conftest IMPORT time, not inside a
# fixture: pytest imports conftest.py before it collects the test
# modules, which is the last moment guaranteed to precede any
# ``import geeViz.geeView``. Restored by the session fixture below.
_ORIGINAL_EEAUTH_MODE = os.environ.get("GEEVIZ_EEAUTH_MODE")
os.environ["GEEVIZ_EEAUTH_MODE"] = "legacy"


def _real_geeview():
    """Return the imported ``geeViz.geeView`` module, or ``None``.

    ``None`` also covers the case where something else in the wider test
    run has swapped a stand-in into ``sys.modules`` -- ``geeViz/tests/
    test_esriLib.py`` installs a stub module there at import time so it
    can import ``geeViz.esriLib`` without EE credentials, and that stub
    has no ``_set_ee_api_upstream``. There is nothing for this fixture
    to restore in that case.
    """
    import sys

    module = sys.modules.get("geeViz.geeView")
    if module is None or not hasattr(module, "_set_ee_api_upstream"):
        return None
    return module


@pytest.fixture(scope="session", autouse=True)
def _no_machine_wide_detached_proxy(tmp_path_factory):
    """Point the detached-proxy state file at a throwaway path.

    ``EECreds.stop()`` / ``_kill_detached()`` / ``_clear_detached_state()``
    all route through ``_detached_state_path()``. Redirecting it for the
    session means no test can kill (or resurrect) the real background
    proxy, and no test inherits one another test left behind.
    """
    from geeViz.eeAuth.eeCreds import EECreds

    state_file = str(
        tmp_path_factory.mktemp("eeauth") / ".geeViz_eeauth_proxy.json"
    )
    original = EECreds.__dict__["_detached_state_path"]
    EECreds._detached_state_path = staticmethod(lambda: state_file)
    try:
        yield
    finally:
        EECreds._detached_state_path = original
        if _ORIGINAL_EEAUTH_MODE is None:
            os.environ.pop("GEEVIZ_EEAUTH_MODE", None)
        else:
            os.environ["GEEVIZ_EEAUTH_MODE"] = _ORIGINAL_EEAUTH_MODE


@pytest.fixture(autouse=True)
def _isolate_process_globals():
    """Snapshot and restore the process-wide state this suite mutates.

    Tests reach for ``os.environ`` directly (not only via
    ``patch.dict``), set the ``CURRENT_TENANT`` ContextVar, and register
    an ``/ee-api`` upstream on ``geeViz.geeView``. Any of those leaking
    forward makes a later test's result depend on run order -- e.g.
    ``test_geeviz_request_handler_503s_when_no_upstream_registered``
    only holds while ``_EE_API_UPSTREAM`` is ``None``.
    """
    from geeViz.eeAuth import CURRENT_TENANT

    env_before = dict(os.environ)
    tenant_before = CURRENT_TENANT.get()
    upstream_before = getattr(_real_geeview(), "_EE_API_UPSTREAM", None)

    try:
        yield
    finally:
        for key in [k for k in os.environ if k not in env_before]:
            del os.environ[key]
        for key, value in env_before.items():
            if os.environ.get(key) != value:
                os.environ[key] = value

        CURRENT_TENANT.set(tenant_before)

        # geeViz.geeView may have been imported *during* the test.
        geeview = _real_geeview()
        if geeview is not None:
            geeview._set_ee_api_upstream(upstream_before)
