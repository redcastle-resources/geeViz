"""Carry attribution context across thread boundaries.

Why this exists
---------------
EE attribution rides on ``ContextVar``s. ``TenantAwareHttp`` reads
``CURRENT_USER_EMAIL`` / ``CURRENT_SESSION_ID`` / ``CURRENT_TENANT`` on
every outbound EE request and stamps them as ``X-Agent-*`` headers; the
ee-proxy resolves identity from those headers and mints the workload tag
that Cloud Monitoring bills against.

``ContextVar``s do **not** cross ``threading.Thread`` boundaries. A
thread starts with an empty context regardless of what the spawning
thread had set. That is normally harmless, but geeViz runs EE work in
threads constantly — ``run_code`` execs user code in one, ``printEE``
spawns one per call, map/chart helpers spawn more — so the identity set
for a tool call evaporated the moment the work moved off the calling
thread. Every such call reached the proxy with no identity headers and
was logged ``via=ANONYMOUS user=anonymous sub=- sess=-``, then billed to
nobody.

Wrapping the thread target with :func:`run_in_context` makes the child
thread run inside a snapshot of the spawning thread's context, so the
ContextVars are visible and the headers get stamped.

Usage
-----
Take the snapshot on the **spawning** thread, at spawn time::

    from geeViz.eeAuth.threadctx import run_in_context
    t = threading.Thread(target=run_in_context(work), args=(x,))
    t.start()

One wrapper per thread
----------------------
:func:`contextvars.Context.run` refuses re-entry — calling it on a
Context that is already executing raises ``RuntimeError``. Each call to
:func:`run_in_context` takes its own snapshot, so a wrapper is good for
exactly one thread. For a pool, wrap per task rather than reusing one
wrapper across workers::

    pool.map(lambda a: run_in_context(work)(a), items)   # per task

Deliberately stdlib-only, with no geeViz imports, so any module can
import it without risking a cycle.
"""
from __future__ import annotations

import contextvars
import threading
from typing import Any, Callable, Optional, TypeVar

__all__ = ["run_in_context", "context_thread"]

_T = TypeVar("_T")


def run_in_context(fn: Callable[..., _T]) -> Callable[..., _T]:
    """Wrap ``fn`` so it runs inside a snapshot of the CALLER's context.

    The snapshot is taken here, on the calling thread — not inside the
    wrapper — because by the time the wrapper runs it is already on the
    new thread, whose context is empty. Capturing late is the whole bug
    this function exists to avoid.

    The returned callable is single-use per thread; see the module
    docstring.
    """
    ctx = contextvars.copy_context()

    def _wrapped(*args: Any, **kwargs: Any) -> _T:
        return ctx.run(fn, *args, **kwargs)

    # Keep the wrapper introspectable — thread names and tracebacks that
    # say "_wrapped" instead of the real target make this plumbing much
    # harder to recognise in a log.
    try:
        _wrapped.__name__ = getattr(fn, "__name__", "_wrapped")
        _wrapped.__qualname__ = getattr(fn, "__qualname__", _wrapped.__name__)
        _wrapped.__doc__ = getattr(fn, "__doc__", None)
    except Exception:  # pragma: no cover - exotic callables
        pass
    return _wrapped


def context_thread(
    target: Callable[..., Any],
    *,
    args: tuple = (),
    kwargs: Optional[dict] = None,
    daemon: Optional[bool] = None,
    name: Optional[str] = None,
) -> threading.Thread:
    """``threading.Thread`` that inherits the caller's context.

    Convenience over ``Thread(target=run_in_context(fn), ...)``. Returns
    an unstarted thread so the caller keeps control of ``start()``.
    """
    return threading.Thread(
        target=run_in_context(target),
        args=args,
        kwargs=kwargs or {},
        daemon=daemon,
        name=name,
    )
