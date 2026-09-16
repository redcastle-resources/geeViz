"""geeViz burns Gemini tokens nobody was billed for.

``outputLib.reports``, ``googleMapsLib`` and ``inventoryLib`` each call
Gemini directly. Two of them pulled token counts off the response and
returned them in a ``metadata`` dict; the third discarded them. All
three used different key names for the same four numbers, and none of
the counts reached anything that accounts for spend.

:mod:`geeViz.llmUsage` gives them one record shape and one way to
announce it. The shape is not arbitrary — it matches the field names the
consumer's ``gemini_usage`` table and CDU pricing already use, so a
record crosses into billing without a translation step. Tests below pin
that, because a rename on either side re-opens the gap silently: the
tokens still get counted, just into fields nobody reads.
"""
import threading
from types import SimpleNamespace

import pytest

import geeViz.llmUsage as lu


def _um(prompt=0, out=0, thoughts=0, cached=0, tool=0, total=None,
        details=None):
    return SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=out,
        thoughts_token_count=thoughts,
        cached_content_token_count=cached,
        tool_use_prompt_token_count=tool,
        total_token_count=total,
        prompt_tokens_details=details,
    )


def _resp(um=None, response_id=None, model_version=None):
    return SimpleNamespace(usage_metadata=um, response_id=response_id,
                           model_version=model_version)


@pytest.fixture(autouse=True)
def _no_hook():
    """Each test starts with no host listening."""
    prev = lu.on_usage
    lu.on_usage = None
    yield
    lu.on_usage = prev


# ── the record shape ──────────────────────────────────────────────────

def test_the_field_names_match_the_consumer():
    """These are geeViz_agent's ``gemini_usage`` column names, and the
    argument names of ``usage_logging.record_usage``. A record whose
    keys drift stops being recordable without a mapping layer — and the
    mapping layer is what this module exists to delete."""
    rec = lu.usage_from_response(_resp(_um(1, 2, 3, 4, 5)), model="m")
    for field in ("prompt_tokens", "candidates_tokens", "thoughts_tokens",
                  "cached_tokens", "tool_use_prompt_tokens", "model",
                  "response_id"):
        assert field in rec, f"{field} missing from the canonical record"


def test_the_old_geeviz_spellings_are_gone():
    """``input_tokens`` / ``output_tokens`` / ``thought_tokens`` were
    the second vocabulary. Keeping them as aliases would let a consumer
    read one set while a producer filled the other."""
    rec = lu.usage_from_response(_resp(_um(1, 2, 3)), model="m")
    for dead in ("input_tokens", "output_tokens", "thought_tokens"):
        assert dead not in rec


def test_counts_come_through():
    rec = lu.usage_from_response(_resp(_um(10, 20, 30, 40, 50)), model="m")
    assert rec["prompt_tokens"] == 10
    assert rec["candidates_tokens"] == 20
    assert rec["thoughts_tokens"] == 30
    assert rec["cached_tokens"] == 40
    assert rec["tool_use_prompt_tokens"] == 50


def test_every_field_is_an_int_even_when_absent():
    """The old extractors defaulted to ``None``, which turned a missing
    count into a TypeError inside whichever ``f"{n:,}"`` formatted it
    next — far from the cause."""
    rec = lu.usage_from_response(_resp(_um()), model="m")
    for k, v in rec.items():
        if k.endswith("_tokens"):
            assert isinstance(v, int), f"{k} is {type(v).__name__}, not int"


def test_a_response_with_no_usage_metadata_still_yields_a_record():
    """Zero tokens is correctly free. No record at all is a gap."""
    rec = lu.usage_from_response(_resp(None), model="m", source="s")
    assert rec["prompt_tokens"] == 0
    assert rec["model"] == "m"
    assert rec["source"] == "s"


def test_total_is_derived_when_gemini_omits_it():
    """A report reading "0 tokens" under a paragraph the model clearly
    wrote is worse than an approximation."""
    rec = lu.usage_from_response(_resp(_um(10, 20, 5, total=None)), model="m")
    assert rec["total_tokens"] == 35


def test_a_reported_total_wins_over_the_derived_one():
    rec = lu.usage_from_response(_resp(_um(10, 20, 5, total=99)), model="m")
    assert rec["total_tokens"] == 99


def test_the_modality_split_is_read_when_present():
    details = [SimpleNamespace(modality="TEXT", token_count=7),
               SimpleNamespace(modality="IMAGE", token_count=11),
               SimpleNamespace(modality="TEXT", token_count=3)]
    rec = lu.usage_from_response(_resp(_um(21, details=details)), model="m")
    assert rec["prompt_text_tokens"] == 10
    assert rec["prompt_image_tokens"] == 11


# ── the model, because CDU pricing is per-model ───────────────────────

def test_the_response_model_beats_the_argument():
    """Billing at the wrong model's rate produces plausible numbers
    rather than an error, which is why it went unnoticed on the agent
    side for months."""
    rec = lu.usage_from_response(
        _resp(_um(1), model_version="gemini-3.8-flash"), model="asked-for")
    assert rec["model"] == "gemini-3.8-flash"


def test_the_argument_is_used_when_the_response_is_silent():
    """Gemini leaves model_version empty on streamed responses."""
    rec = lu.usage_from_response(_resp(_um(1), model_version=""),
                                 model="gemini-3.8-flash")
    assert rec["model"] == "gemini-3.8-flash"


# ── the de-duplication id ─────────────────────────────────────────────

def test_geminis_own_id_is_preferred():
    rec = lu.usage_from_response(_resp(_um(1), response_id="rid-1"))
    assert rec["response_id"] == "rid-1"


def test_an_id_is_minted_when_gemini_supplies_none():
    """The consumer de-dups on this key. An empty one means a replayed
    record cannot be recognized as a repeat — and a replayed record
    bills somebody twice."""
    rec = lu.usage_from_response(_resp(_um(1), response_id=None))
    assert rec["response_id"]
    assert rec["response_id"].startswith("geeviz-")


def test_minted_ids_are_unique_per_call():
    ids = {lu.mint_call_id(None) for _ in range(200)}
    assert len(ids) == 200


def test_the_id_is_fixed_when_the_response_is_read():
    """Re-reporting the SAME record must present the same id — that is
    what makes a replay recognizable. Minting at report time instead
    would give every replay a fresh id and defeat the whole mechanism."""
    rec = lu.usage_from_response(_resp(_um(1)))
    first = rec["response_id"]
    lu.report(rec)
    lu.report(rec)
    assert rec["response_id"] == first


# ── reporting ─────────────────────────────────────────────────────────

def test_the_hook_receives_the_record():
    seen = []
    lu.on_usage = seen.append
    lu.report({"prompt_tokens": 5})
    assert seen == [{"prompt_tokens": 5}]


def test_no_hook_is_not_an_error():
    """A notebook or a script uses geeViz with no agent in front of it.
    That is the normal case, not a degraded one."""
    assert lu.report({"prompt_tokens": 5}) == {"prompt_tokens": 5}


def test_a_broken_hook_cannot_fail_the_work():
    """Accounting must never be able to fail the thing it is accounting
    for. A geeViz function raising because a billing hook threw would
    be a far worse bug than an unbilled call."""
    def boom(_):
        raise RuntimeError("host is on fire")
    lu.on_usage = boom
    assert lu.report({"prompt_tokens": 1})["prompt_tokens"] == 1


def test_collect_gathers_what_was_reported():
    with lu.collect() as records:
        lu.report({"response_id": "a"})
        lu.report({"response_id": "b"})
    assert [r["response_id"] for r in records] == ["a", "b"]


def test_collect_nests():
    """A host collecting around a whole tool call must not lose what a
    geeViz function collected around part of its own work."""
    with lu.collect() as outer:
        lu.report({"response_id": "a"})
        with lu.collect() as inner:
            lu.report({"response_id": "b"})
        assert [r["response_id"] for r in inner] == ["b"]
    assert sorted(r["response_id"] for r in outer) == ["a", "b"]


def test_collect_releases_on_an_exception():
    """A tool that raises must not leave the collector installed — the
    next call would inherit it and attribute its tokens to whoever ran
    the one that failed."""
    with pytest.raises(ValueError):
        with lu.collect():
            raise ValueError("boom")
    with lu.collect() as clean:
        lu.report({"response_id": "later"})
    assert len(clean) == 1


def test_the_hook_still_fires_inside_a_collector():
    """Collecting is a host concern; a hook may be doing something else
    entirely (a progress meter, a log). One must not suppress the
    other."""
    seen = []
    lu.on_usage = seen.append
    with lu.collect() as records:
        lu.report({"response_id": "a"})
    assert len(records) == 1 and len(seen) == 1


def test_collectors_do_not_leak_across_threads():
    """The MCP server serves concurrently. A process-wide collector
    would attribute one caller's tokens to whichever call happened to
    be collecting — silently, and in the direction of over-billing
    somebody."""
    other = []

    def worker():
        lu.report({"response_id": "from-thread"})
        other.append("done")

    with lu.collect() as records:
        t = threading.Thread(target=worker)
        t.start()
        t.join()
        lu.report({"response_id": "mine"})

    assert other == ["done"]
    assert [r["response_id"] for r in records] == ["mine"], (
        "a report from another thread landed in this thread's collector")


# ── the summariser ────────────────────────────────────────────────────

def test_totals_sums_the_token_fields():
    t = lu.totals([
        lu.usage_from_response(_resp(_um(10, 20, 30))),
        lu.usage_from_response(_resp(_um(1, 2, 3))),
    ])
    assert t["calls"] == 2
    assert t["prompt_tokens"] == 11
    assert t["candidates_tokens"] == 22
    assert t["thoughts_tokens"] == 33


def test_totals_does_not_invent_a_model_or_an_id():
    """A total over two models belongs to neither, and a single id on a
    sum would let it be mistaken for one billable record."""
    t = lu.totals([lu.usage_from_response(_resp(_um(1), response_id="x"))])
    assert "model" not in t
    assert "response_id" not in t


def test_totals_tolerates_junk():
    assert lu.totals([])["calls"] == 0
    assert lu.totals(None)["calls"] == 0
    assert lu.totals([{"prompt_tokens": "not a number"}])["prompt_tokens"] == 0


# ── the call sites ────────────────────────────────────────────────────

@pytest.mark.parametrize("module,attr", [
    ("geeViz.googleMapsLib", "_extract_gemini_metadata"),
])
def test_the_maps_extractor_reports(module, attr):
    """Extracting the counts and never announcing them is what the old
    code did — the numbers existed and reached nothing."""
    import importlib
    mod = importlib.import_module(module)
    seen = []
    lu.on_usage = seen.append
    meta = getattr(mod, attr)(
        _resp(_um(7, 8), response_id="rid"), model="m", temperature=0.0,
        mode=None, prompt_used="p", source="geeviz.maps.test")
    assert len(seen) == 1, "the extractor did not report"
    assert seen[0]["prompt_tokens"] == 7
    assert seen[0]["source"] == "geeviz.maps.test"
    # And the caller still gets the numbers in its metadata dict.
    assert meta["prompt_tokens"] == 7
    assert meta["candidates_tokens"] == 8


def test_every_geeviz_gemini_call_site_reports():
    """A new direct ``generate_content`` call that does not report is a
    new leak. Counted against the report call sites so adding one
    without accounting for it fails here rather than on a bill."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in (root / "googleMapsLib.py", root / "inventoryLib.py",
                 root / "outputLib" / "reports.py"):
        src = path.read_text(encoding="utf-8", errors="replace")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.strip().startswith("#"))
        calls = len(re.findall(r"models\.generate_content\(", code))
        # Counts ANNOUNCEMENTS, not extractions. Building the record
        # and never passing it to report() leaves the numbers exactly
        # where they were before this module existed: in a local dict
        # that reaches nothing. An earlier version of this check
        # counted ``usage_from_response(`` and was satisfied by that.
        #
        # Plus calls to the shared maps extractor, which reports on its
        # caller's behalf — its own ``def`` line excluded so the
        # definition is not mistaken for a call site.
        reports = len(re.findall(r"\.report\(", code))
        reports += len(re.findall(r"(?<!def )_extract_gemini_metadata\(", code))
        if calls > reports:
            offenders.append(
                f"  {path.name}: {calls} generate_content call(s), "
                f"{reports} reported")
    assert not offenders, (
        "Gemini calls in geeViz that report no usage:\n" + "\n".join(offenders))


# ── the sandbox, which this module is now inside ──────────────────────

def test_llm_usage_imports_nothing_the_mcp_sandbox_blocks():
    """This module is imported at MODULE SCOPE by outputLib.reports,
    googleMapsLib and inventoryLib. Sandboxed ``run_code`` imports those
    routinely, so every import here is effectively an import inside the
    sandbox.

    It used to ``import threading`` — which is on the blocked list — for
    a thread-local. That did not raise a clean "blocked import" error:
    the tool logged ``"status": "OK"``, its result was never returned
    over stdio, and the agent hung on a spinner with nothing in any log.
    Two full days of debugging would have been one failing test.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    blocked = _sandbox_blocked_names()
    tree = ast.parse((root / "llmUsage.py").read_text(encoding="utf-8"))

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        for n in names:
            if n in blocked:
                offenders.append(f"  line {node.lineno}: {n}")
    assert not offenders, (
        "llmUsage imports modules the MCP sandbox blocks:\n"
        + "\n".join(offenders))


def _sandbox_blocked_names() -> set:
    """The sandbox's own denylist, read from the server rather than
    copied. A copy here would go stale the first time the real list
    grew, and this test would then pass while the sandbox refused."""
    import geeViz.mcp.server as srv
    names = set()
    for attr in ("_AUDIT_BLOCKED_IMPORTS", "_BLOCKED_MODULES"):
        names |= set(getattr(srv, attr, ()) or ())
    assert names, "could not read the sandbox denylist from the server"
    return names


def test_the_libraries_that_import_it_are_clean_too():
    """The same hazard one level up: anything reports / maps / inventory
    imports at module scope is also an import inside the sandbox."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    blocked = _sandbox_blocked_names()
    # These three are the ones that gained a module-scope llmUsage
    # import. Only their OWN top-level imports are in scope here — the
    # wider geeViz import graph predates this and is a separate matter.
    offenders = []
    for rel in ("outputLib/reports.py", "googleMapsLib.py",
                "inventoryLib.py"):
        path = root / rel
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in tree.body:          # top level only
            if isinstance(node, ast.ImportFrom) and node.module == "geeViz":
                for a in node.names:
                    if a.name in blocked:
                        offenders.append(f"  {rel}:{node.lineno} {a.name}")
    assert not offenders, "\n".join(offenders)


def test_the_collector_reaches_a_worker_thread_the_way_fastmcp_runs_tools():
    """Load-bearing and non-obvious.

    The collector is a ContextVar, and a geeViz tool body runs in a
    worker thread — FastMCP dispatches sync tool functions through
    ``anyio.to_thread.run_sync``. anyio copies the calling context into
    that worker, so a report made inside the tool still lands in the
    collector the MCP layer opened around the call.

    ``loop.run_in_executor`` does NOT copy the context. If the dispatch
    ever moves to a bare executor, every geeViz usage record silently
    goes nowhere — no error, just an accounting hole. Hence this test.
    """
    import asyncio
    import anyio.to_thread

    def work():
        lu.report({"response_id": "from-worker"})

    async def drive():
        with lu.collect() as records:
            await anyio.to_thread.run_sync(work)
        return records

    records = asyncio.run(drive())
    assert [r["response_id"] for r in records] == ["from-worker"], (
        "the collector did not reach the worker thread — geeViz usage "
        "reported inside a tool would be dropped")
