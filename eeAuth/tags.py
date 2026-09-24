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

Tag stores
----------
63 characters isn't enough to spell out a real identity tuple (user
email + session id + action + tenant), so :func:`mint_workload_tag`
hashes the parts into a short ``wl_<hex>`` tag instead. That tag is not
reversible on its own — recovering who a billing row belongs to needs
the ``tag -> parts`` mapping written down somewhere. That "somewhere" is
this module's store layer:

- :class:`TagStore` — the ``put`` / ``lookup`` Protocol every store
  implements. Implementations must be thread-safe and idempotent on
  ``put``.
- :class:`InMemoryTagStore` — process-local dict. Fine for one-shot
  scripts and tests; the mapping dies with the process.
- :class:`SQLiteTagStore` — single file, typically
  ``~/.geeViz/workload_tags.db``. Survives kernel restarts and reruns.
  Not suitable for multi-instance deployments, where each instance
  would keep its own file and miss the others' tags.
- :class:`ChainedTagStore` — several stores treated as one.
- :func:`default_tag_store` — the store used when nobody configured one.

:class:`ChainedTagStore` is the newest piece and the least obvious,
because its two operations deliberately disagree about scope:

- ``put`` writes to the **primary (first) store only**. Attribution
  needs exactly one writer; fanning writes out to every backend would
  create diverging partial copies and turn a lookup miss into "which
  copy is right?".
- ``lookup`` reads from **every backend in order**, first hit wins (a
  failing backend is logged and skipped rather than breaking the
  chain). Reads have no such problem — tags are content-addressed, so
  the same parts and secret always produce the same tag and it does not
  matter which backend answered.

That asymmetry exists because more than one store can be live on a
machine at once — an agent writing to Postgres beside a notebook using
the sqlite default. Without chaining, a tag minted under one is simply
invisible to the other's ``lookup``, and the caller gets a bare ``None``
that reads as "never minted" when the truth is "you asked the wrong
store".
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

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


# How much of a tag the env suffix may take. Real values are "prod",
# "test", "dev"; the clamp is only so a caller passing something long
# cannot push the suffix into the 63-char truncation that would corrupt
# it into a DIFFERENT env's name.
_ENV_PART_MAX_LEN = 12


def mint_workload_tag(
    parts: dict[str, Any], *, secret: str, digest_size: int = 8
) -> str:
    """Deterministic short tag from a parts dict + secret.

    Returns ``wl_<hex>``, or ``wl_<hex>__<env>`` when ``parts`` carries a
    non-empty ``env``. The hex is a ``digest_size``-byte blake2b of the
    canonicalized parts (default 16 hex chars → collision probability
    ~10⁻⁹ at millions of tags). Same input always yields the same tag.

    Why the env is spelled out when the hash already covers it
    ----------------------------------------------------------
    ``env`` is part of the hash input, so test and prod already mint
    DIFFERENT tags for the same person — but they mint two opaque hashes,
    and opaque is the problem. Cloud Monitoring is per GCP *project*, and
    every deployment of a tenant shares one, so a puller sees its own
    tags and its siblings' in the same stream with ``workload_tag`` as the
    only label to separate them by. Faced with a bare hash it did not
    mint, it cannot tell "another deployment's traffic" from "traffic
    nobody minted attribution for", and the honest fallback is to record
    the row as unattributed. Production accumulated 141 CDU of test's
    Earth Engine spend that way.

    Long-form pre-v2 tags never had this problem: they spelled out tenant
    and user, so a foreign tag was recognizable on sight. Naming the env
    restores exactly that much legibility -- enough to answer "is this
    mine?" without a lookup -- and nothing more. The identity stays in the
    hash, where it is not readable from a billing label.

    Recover it with :func:`env_of_workload_tag`.

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
    env = sanitize_workload_tag_part(
        str(parts.get("env") or "") if isinstance(parts, dict) else "")
    # Hand the hash and the env to build_workload_tag as SEPARATE parts
    # rather than pre-joining them. It sanitizes each part, and part
    # sanitization collapses runs of ``_`` to keep ``__`` unambiguous as
    # the separator -- so a pre-joined ``wl_<hex>__prod`` comes back out
    # as ``wl_<hex>_prod``, with the separator gone and the env no longer
    # parseable. Joining is build_workload_tag's job; let it do it.
    return build_workload_tag(f"{_TAG_PREFIX}_{h}",
                              env[:_ENV_PART_MAX_LEN])


def env_of_workload_tag(tag: str) -> str:
    """The env a minted tag names, or ``""`` if it names none.

    ``""`` is the answer for two different things, and callers must treat
    them alike: a tag minted before the suffix existed, and a tag minted
    without an env. Both mean "this tag cannot tell you whose deployment
    it is" — never "it isn't yours". Reading an empty result as foreign
    would discard real spend for every tag minted before this change.
    """
    if not tag or not tag.startswith(f"{_TAG_PREFIX}_"):
        return ""
    parts = tag.split(SEPARATOR)
    if len(parts) < 2:
        return ""
    return parts[-1].strip()


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


class ChainedTagStore:
    """Write to the first store; read from all of them in order.

    Exists because more than one store can be live on the same machine.
    A geeViz agent installs a Postgres-backed store, while notebooks and
    standalone scripts use the sqlite default — so a tag minted under
    one is invisible to the other's ``lookup``, and the caller sees a
    bare ``None`` that reads as "this tag was never minted" when the
    truth is "you asked the wrong store". That is how EE usage ends up
    labeled unattributed while its mapping sits intact a few
    directories away.

    The asymmetry is deliberate:

    * ``put`` -> **primary only**. Writing to every backend would make
      two partial, diverging copies of the mapping and turn a lookup
      miss into a correctness question ("which one is right?").
      Attribution needs exactly one writer.
    * ``lookup`` -> **every backend, in order**, first hit wins. Reads
      are free of that problem: finding a mapping somewhere is strictly
      better than not finding it, and the answer is the same wherever
      it came from because tags are content-addressed (same parts +
      same secret = same tag).

    A failing backend never breaks the chain — it's logged and skipped,
    so an unreachable Postgres degrades to "sqlite still answers"
    instead of taking lookups down with it.

    Example::

        eeCreds.setTagStore(ChainedTagStore(PostgresTagStore(...),
                                            SQLiteTagStore()))
    """

    def __init__(self, *stores) -> None:
        real = [s for s in stores if s is not None]
        if not real:
            raise ValueError("ChainedTagStore: at least one store required")
        self._stores = real

    @property
    def primary(self):
        """The store that receives writes."""
        return self._stores[0]

    def put(self, tag: str, parts: dict[str, Any]) -> None:
        self._stores[0].put(tag, parts)

    def lookup(self, tag: str) -> Optional[dict[str, Any]]:
        for i, store in enumerate(self._stores):
            try:
                hit = store.lookup(tag)
            except Exception:
                logger.exception(
                    "ChainedTagStore: %s.lookup failed for %r; trying the "
                    "next store", type(store).__name__, tag,
                )
                continue
            if hit is not None:
                if i:
                    # Found somewhere other than where writes go. Worth
                    # saying out loud: it means this process is reading
                    # a mapping some OTHER writer produced.
                    logger.debug(
                        "ChainedTagStore: %r resolved from fallback %s "
                        "(primary %s had no row)",
                        tag, type(store).__name__,
                        type(self._stores[0]).__name__,
                    )
                return hit
        return None

    def __repr__(self) -> str:
        names = " -> ".join(type(s).__name__ for s in self._stores)
        return f"ChainedTagStore({names})"


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
