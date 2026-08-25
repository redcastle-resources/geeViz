"""Tests for cross-thread attribution context.

The bug: EE attribution rides on ContextVars, which ``TenantAwareHttp``
turns into ``X-Agent-*`` headers on each outbound EE request. ContextVars
do not cross ``threading.Thread`` boundaries, and geeViz runs EE work in
threads constantly — ``run_code`` execs user code in one, ``printEE``
spawns one per call. So the identity set for a tool call vanished the
moment the work moved off the calling thread, every such call reached the
proxy as ``via=ANONYMOUS user=anonymous sub=- sess=-``, and the spend was
billed to nobody.

Nothing raised. The work completed correctly; only the attribution was
lost, which is why this survived so long.
"""

import contextvars
import threading

import pytest

from geeViz.eeAuth.threadctx import context_thread, run_in_context

CV = contextvars.ContextVar("cv_test", default="")


def _capture(box, key="v"):
    box[key] = CV.get()


# ── The bug itself ───────────────────────────────────────────────────────

def test_plain_thread_loses_context():
    """Characterizes the defect. If this ever fails, the platform
    changed and the wrapper may no longer be needed."""
    CV.set("user@example.com")
    box = {}
    t = threading.Thread(target=_capture, args=(box,))
    t.start(); t.join()

    assert box["v"] == "", (
        "a bare thread unexpectedly saw the parent's ContextVar")


def test_wrapped_thread_keeps_context():
    CV.set("user@example.com")
    box = {}
    t = threading.Thread(target=run_in_context(_capture), args=(box,))
    t.start(); t.join()

    assert box["v"] == "user@example.com"


def test_context_thread_helper_keeps_context():
    CV.set("someone@example.com")
    box = {}
    t = context_thread(_capture, args=(box,), daemon=True)
    t.start(); t.join()

    assert box["v"] == "someone@example.com"


# ── Snapshot timing ──────────────────────────────────────────────────────

def test_snapshot_is_taken_at_wrap_time_not_run_time():
    """Capturing late would defeat the whole purpose.

    If the copy happened inside the wrapper it would run on the new
    thread, whose context is empty — exactly the bug being fixed.
    """
    CV.set("first")
    wrapped = run_in_context(_capture)
    CV.set("second")          # changes AFTER the snapshot

    box = {}
    t = threading.Thread(target=wrapped, args=(box,))
    t.start(); t.join()

    assert box["v"] == "first", "wrapper must carry the value from wrap time"


def test_child_does_not_leak_back_into_parent():
    """A thread writing the var must not mutate the caller's context."""
    CV.set("parent")

    def _mutate(_box):
        CV.set("child")

    t = threading.Thread(target=run_in_context(_mutate), args=({},))
    t.start(); t.join()

    assert CV.get() == "parent"


# ── The re-entry constraint the call sites must respect ──────────────────

def test_one_wrapper_cannot_serve_two_threads():
    """Context.run refuses re-entry — documents why call sites wrap
    per-thread rather than sharing a single wrapper.

    The parallel-query site iterates queries and wraps inside the loop
    for exactly this reason; sharing one wrapper would raise on the
    second query.
    """
    CV.set("x")
    entered = threading.Event()
    release = threading.Event()

    def _hold():
        entered.set()
        release.wait(timeout=5)

    wrapped = run_in_context(_hold)
    errors = []

    def _second():
        # Only overlapping execution trips the guard; without forcing the
        # first call to still be inside the Context, the two run
        # sequentially and both succeed.
        entered.wait(timeout=5)
        try:
            wrapped()
        except RuntimeError as exc:
            errors.append(exc)
        finally:
            release.set()

    t1 = threading.Thread(target=wrapped)
    t2 = threading.Thread(target=_second)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors, "expected Context.run re-entry to be rejected"


def test_separate_wrappers_serve_separate_threads():
    """The supported pattern: one wrapper per thread."""
    CV.set("shared-identity")
    boxes = [{} for _ in range(6)]
    ts = [
        threading.Thread(target=run_in_context(_capture), args=(b,))
        for b in boxes
    ]
    for t in ts: t.start()
    for t in ts: t.join()

    assert all(b["v"] == "shared-identity" for b in boxes)


# ── Behaviour preservation ───────────────────────────────────────────────

def test_return_value_and_args_pass_through():
    def _add(a, b, c=0):
        return a + b + c

    assert run_in_context(_add)(1, 2, c=3) == 6


def test_exceptions_propagate_unchanged():
    def _boom():
        raise ValueError("kaboom")

    with pytest.raises(ValueError, match="kaboom"):
        run_in_context(_boom)()


def test_wrapper_keeps_target_name_for_readable_tracebacks():
    def _named_target():
        pass

    assert run_in_context(_named_target).__name__ == "_named_target"


# ── The nesting case that made a one-level fix insufficient ──────────────

def test_context_survives_two_thread_hops():
    """printEE is called BY user code that is itself already on a worker
    thread, so a single-level fix would still lose identity one level
    deeper. Both hops must be wrapped.
    """
    CV.set("deep@example.com")
    box = {}

    def _outer():
        inner = threading.Thread(target=run_in_context(_capture), args=(box,))
        inner.start(); inner.join()

    t = threading.Thread(target=run_in_context(_outer))
    t.start(); t.join()

    assert box["v"] == "deep@example.com"
