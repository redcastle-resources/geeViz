"""Earth Engine workload-tag helpers.

EE workload tags surface in GCP Billing under the
``goog-earth-engine-workload-tag`` label, so tagged calls can be broken
down per user / session / source. This module builds well-formed tags
from arbitrary string parts (sanitizing each so the result is always
accepted by EE).

EE constraints (from ``ee/_state.py`` validation):

- 1 - 63 characters
- begins and ends with a lowercase alphanumeric ``[a-z0-9]``
- middle characters: ``[a-z0-9_-]`` (lowercase alphanumeric, dash, underscore)

No uppercase, no ``.``, no other punctuation. Anything outside that set
(``@``, spaces, slashes, dots, uppercase, etc.) gets sanitized to ``-``.

**Separator: ``__`` (double underscore).** Single ``-`` already appears
inside sanitized parts (e.g. ``ihousman-redcastleresources-com``), so we
reserve double underscore as the between-parts delimiter. That makes
tags trivially parseable with ``tag.split("__")``::

    agent__run_code__ihousman-redcastleresources-com__db208a06-1c49

To keep ``__`` an unambiguous separator, runs of ``_`` *within* a part
get collapsed to a single ``_`` during sanitization (so an input like
``run__code`` becomes ``run_code``). Underscores from sources like tool
names — ``run_code``, ``map_control`` — pass through intact because
they're already singletons.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

_TAG_ALLOWED_CHAR = re.compile(r"[^a-z0-9_\-]")
_TAG_MAX_LEN = 63
SEPARATOR = "__"

_TAG_PREFIX = "wl"


def sanitize_workload_tag_part(s: str) -> str:
    """Sanitize a single component of a workload tag.

    - Lowercases.
    - Replaces disallowed characters with ``-``.
    - Collapses runs of ``-`` to a single ``-``.
    - Collapses runs of ``_`` to a single ``_`` so the ``__`` separator
      stays unambiguous when parts are joined.
    - Strips leading/trailing ``-`` and ``_`` (EE rejects tags that don't
      begin and end with an alphanumeric).
    """
    if not s:
        return ""
    s = s.lower()
    s = _TAG_ALLOWED_CHAR.sub("-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = re.sub(r"_{2,}", "_", s)
    s = s.strip("-_")
    return s


def build_workload_tag(*parts: str) -> str:
    """Join sanitized parts with ``__`` and clamp to EE's 63-char limit.

    Empty / falsy parts are dropped. The final tag is guaranteed to satisfy
    EE's regex: ``[a-z0-9][a-z0-9_\\-]{0,61}[a-z0-9]``. Returns an empty
    string if everything was dropped — callers should treat empty as "no
    tag" and skip the workload-tag header / body field entirely.
    """
    clean = [sanitize_workload_tag_part(p) for p in parts]
    clean = [c for c in clean if c]
    if not clean:
        return ""
    tag = SEPARATOR.join(clean)[:_TAG_MAX_LEN]
    # Re-strip in case the truncation left a dangling separator at the end.
    tag = tag.rstrip("-_")
    return tag


# ---------------------------------------------------------------------------
# Deterministic short-tag minting + reversible lookup
# ---------------------------------------------------------------------------
#
# EE workload tags are capped at 63 chars, which isn't enough to encode a
# realistic identity tuple (user email + session id + action + tenant). The
# recovery pattern is:
#
#   tag   = mint_workload_tag(parts, secret)   # short deterministic hash
#   store.put(tag, parts)                      # remember the mapping
#   ...
#   parts = store.lookup(tag)                  # get parts back later
#
# `mint_workload_tag` is deterministic: same (parts, secret) always yields
# the same tag, so re-minting during a session collapses onto the same row
# rather than growing the store.


def _canonical_parts(parts: dict[str, Any]) -> str:
    """Stable serialization of a parts dict — sorted by key, string-cast
    values. So {'user':'x','tenant':'a'} and {'tenant':'a','user':'x'}
    hash to the SAME tag."""
    if not isinstance(parts, dict):
        raise TypeError(f"parts must be a dict, got {type(parts).__name__}")
    items = sorted((str(k), "" if v is None else str(v)) for k, v in parts.items())
    return "|".join(f"{k}={v}" for k, v in items)


def mint_workload_tag(
    parts: dict[str, Any], *, secret: str, digest_size: int = 8
) -> str:
    """Deterministic short tag from a parts dict + secret.

    Returns ``wl_<hex>`` where the hex is a ``digest_size``-byte blake2b of
    the canonicalised parts (default 16 hex chars → collision probability
    ~10⁻⁹ at millions of tags). Same input always yields the same tag.

    The tag is NOT reversible on its own — pair with a ``TagStore`` that
    records ``tag → parts`` at mint time so lookups can recover identity
    later.
    """
    if not secret:
        raise ValueError("mint_workload_tag: secret is required")
    canonical = _canonical_parts(parts)
    h = hashlib.blake2b(
        (canonical + "|" + secret).encode("utf-8"),
        digest_size=digest_size,
    ).hexdigest()
    tag = f"{_TAG_PREFIX}_{h}"
    # Belt-and-suspenders: minted tags are guaranteed valid but pass them
    # through build_workload_tag anyway so any future format tweak stays
    # consistent with the sanitiser.
    return build_workload_tag(tag)


# ---------------------------------------------------------------------------
# TagStore Protocol + default impls
# ---------------------------------------------------------------------------


@runtime_checkable
class TagStore(Protocol):
    """Minimal contract for tag → parts persistence.

    Implementations MUST be thread-safe (the proxy calls concurrently from
    request handlers) and idempotent on ``put`` (mint is deterministic —
    re-inserting the same (tag, parts) is a no-op, not an error).
    """

    def put(self, tag: str, parts: dict[str, Any]) -> None:  # pragma: no cover
        ...

    def lookup(self, tag: str) -> Optional[dict[str, Any]]:  # pragma: no cover
        ...


class InMemoryTagStore:
    """Process-local dict-backed store.

    Fast, zero-dependency, but the mapping dies with the Python process
    and doesn't cross processes/instances. Use for one-shot scripts and
    unit tests; use ``SQLiteTagStore`` (or a Postgres impl) for anything
    that outlives the process.
    """

    def __init__(self) -> None:
        self._map: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, tag: str, parts: dict[str, Any]) -> None:
        with self._lock:
            self._map[tag] = dict(parts)

    def lookup(self, tag: str) -> Optional[dict[str, Any]]:
        with self._lock:
            v = self._map.get(tag)
            return dict(v) if v is not None else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._map)


import contextlib


@contextlib.contextmanager
def _sqlite_conn(path: str | Path):
    """Open a short-lived sqlite3 connection and guarantee close on exit.

    ``with sqlite3.connect(...)`` commits on exit but does NOT close the
    connection — on Windows that leaves the file locked and breaks
    ``TemporaryDirectory`` cleanup and any process that wants to reopen.
    """
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        yield conn
    finally:
        conn.close()


class SQLiteTagStore:
    """File-backed store using ``sqlite3`` (stdlib, no extra deps).

    Survives kernel restarts and re-runs of the same script. Single-file,
    typically at ``~/.geeViz/workload_tags.db``. Suitable for notebooks
    and single-instance CLIs; NOT suitable for multi-instance Cloud Run
    (each instance would have its own file, cross-instance lookups would
    silently miss). Use a Postgres impl for that.

    Concurrent read/write across threads in one process is safe (sqlite3
    connection is created per-call with a short-lived cursor). Multiple
    processes sharing the same file also work (sqlite handles the file
    lock), though heavy write contention will degrade.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS workload_tags (
        tag        TEXT PRIMARY KEY,
        parts_json TEXT NOT NULL,
        created_at REAL NOT NULL DEFAULT (strftime('%s', 'now'))
    );
    """

    def __init__(self, path: Optional[str | Path] = None) -> None:
        if path is None:
            path = Path.home() / ".geeViz" / "workload_tags.db"
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # Init schema once at construction — subsequent calls open short
        # connections. isolation_level=None → autocommit for the tiny
        # single-statement writes below.
        with _sqlite_conn(self.path) as conn:
            conn.execute(self._SCHEMA)

    def put(self, tag: str, parts: dict[str, Any]) -> None:
        payload = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        with _sqlite_conn(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO workload_tags (tag, parts_json) "
                "VALUES (?, ?)",
                (tag, payload),
            )

    def lookup(self, tag: str) -> Optional[dict[str, Any]]:
        with _sqlite_conn(self.path) as conn:
            row = conn.execute(
                "SELECT parts_json FROM workload_tags WHERE tag = ?",
                (tag,),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None

    def __len__(self) -> int:
        with _sqlite_conn(self.path) as conn:
            (n,) = conn.execute("SELECT COUNT(*) FROM workload_tags").fetchone()
        return int(n)


def default_tag_store() -> TagStore:
    """Return the process-wide default store. First call constructs
    ``SQLiteTagStore()`` at ``~/.geeViz/workload_tags.db``. Callers who
    want in-memory or a custom store should set it explicitly via
    ``eeCreds.setTagStore(...)`` before ``eeCreds.start()``."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        with _DEFAULT_STORE_LOCK:
            if _DEFAULT_STORE is None:
                _DEFAULT_STORE = SQLiteTagStore()
    return _DEFAULT_STORE


_DEFAULT_STORE: Optional[TagStore] = None
_DEFAULT_STORE_LOCK = threading.Lock()


def _default_secret() -> str:
    """Read the workload-tag secret from ``WORKLOAD_TAG_SECRET`` env var.
    Falls back to a per-machine constant so mints are stable across
    process restarts on the same box; this fallback is fine for local
    dev / notebooks but production callers should set the env var."""
    env = os.environ.get("WORKLOAD_TAG_SECRET")
    if env:
        return env
    return "geeviz-workload-tag-local-dev-secret"
