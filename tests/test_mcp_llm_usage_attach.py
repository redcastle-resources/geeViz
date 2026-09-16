"""The usage record has to cross a process boundary, and land where the
agent looks for it.

The MCP server runs as a subprocess of the agent. It is the only layer
that knows both things: that geeViz just spent tokens, and that a host
exists to tell. It collects what :mod:`geeViz.llmUsage` announces during
one tool call and attaches it to that call's result.

"Where the agent looks" is not a free choice. ``after_tool_callback``
unwraps MCP results in one specific order — ``structuredContent`` first,
then the first JSON ``content[].text``, then an inner
``{"result": "<json string>"}`` envelope — and reads its fields off
whatever that lands on. Attaching the field anywhere else means it is
technically present and never found.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

import geeViz.llmUsage as lu


@pytest.fixture(scope="module")
def srv():
    import geeViz.mcp.server as _s
    return _s


def _rec(rid="rid-1"):
    return {"prompt_tokens": 10, "candidates_tokens": 2,
            "response_id": rid, "source": "geeviz.reports",
            "model": "gemini-3.8-flash"}


class _Text:
    """A TextContent-shaped item. Mutable, like the real one usually is."""
    def __init__(self, text):
        self.text = text


# ── where the field lands ─────────────────────────────────────────────

def test_structured_content_is_preferred(srv):
    result = SimpleNamespace(structuredContent={"success": True}, content=[])
    srv._attach_llm_usage(result, [_rec()])
    assert result.structuredContent["_llm_usage"] == [_rec()]


def test_the_result_envelope_is_written_inside(srv):
    """FastMCP wraps a tool's JSON string as {"result": "<json>"}. The
    agent unwraps that before reading fields, so writing beside it
    rather than inside it puts the record somewhere nothing looks."""
    inner = {"success": True, "message": "done"}
    result = SimpleNamespace(
        structuredContent={"result": json.dumps(inner)}, content=[])
    srv._attach_llm_usage(result, [_rec()])
    back = json.loads(result.structuredContent["result"])
    assert back["_llm_usage"] == [_rec()]
    assert back["message"] == "done", "the tool's own payload was damaged"


def test_a_text_content_part_is_used_when_there_is_no_structured(srv):
    item = _Text(json.dumps({"success": True}))
    result = SimpleNamespace(structuredContent=None, content=[item])
    srv._attach_llm_usage(result, [_rec()])
    assert json.loads(item.text)["_llm_usage"] == [_rec()]


def test_a_bare_list_of_content_items_works(srv):
    """Older MCP SDKs return a list rather than a ToolResult."""
    item = _Text(json.dumps({"success": True}))
    srv._attach_llm_usage([item], [_rec()])
    assert json.loads(item.text)["_llm_usage"] == [_rec()]


def test_non_json_text_parts_are_skipped(srv):
    """A tool returning plain prose must not have JSON spliced into it."""
    prose = _Text("just some text")
    payload = _Text(json.dumps({"success": True}))
    result = SimpleNamespace(structuredContent=None, content=[prose, payload])
    srv._attach_llm_usage(result, [_rec()])
    assert prose.text == "just some text"
    assert "_llm_usage" in json.loads(payload.text)


# ── what must not happen ──────────────────────────────────────────────

def test_no_records_means_no_field(srv):
    """A tool that spent nothing must return exactly what it returned
    before — an empty accounting field is still noise in the model's
    context."""
    result = SimpleNamespace(structuredContent={"success": True}, content=[])
    srv._attach_llm_usage(result, [])
    assert "_llm_usage" not in result.structuredContent


def test_an_unrecognized_result_shape_is_returned_unharmed(srv):
    """Better to lose the accounting than the tool's answer."""
    weird = SimpleNamespace(structuredContent=None, content=None)
    assert srv._attach_llm_usage(weird, [_rec()]) is weird
    assert srv._attach_llm_usage(None, [_rec()]) is None


def test_the_field_name_matches_what_the_agent_drains(srv):
    """Two constants, two repos, one string. If they drift, the field
    is attached and never drained — so it reaches the model AND the
    events table, which is the one outcome the drain exists to stop."""
    assert srv._LLM_USAGE_FIELD == "_llm_usage"


# ── the collector spans the whole call ────────────────────────────────

def test_the_usage_layer_is_the_outermost_wrapper(srv):
    """It has to see everything the tool did. Wrapped INSIDE the scrub
    or workload-tag layers it would miss whatever those call."""
    assert srv.app._tool_manager.call_tool.__name__ == (
        "_tool_manager_call_tool_with_usage")


def test_a_tool_call_collects_and_attaches(srv, monkeypatch):
    """End to end through the real wrapper: a tool that reports usage
    the way geeViz does comes back with it attached."""
    async def fake_inner(name, arguments, context=None, convert_result=False):
        lu.report(_rec("from-the-tool"))
        return SimpleNamespace(
            structuredContent={"success": True}, content=[])

    monkeypatch.setattr(srv, "_pre_usage_call_tool", fake_inner)
    out = asyncio.run(srv._tool_manager_call_tool_with_usage("any_tool", {}))
    attached = out.structuredContent["_llm_usage"]
    assert [r["response_id"] for r in attached] == ["from-the-tool"]


def test_a_tool_that_spends_nothing_is_untouched(srv, monkeypatch):
    async def fake_inner(name, arguments, context=None, convert_result=False):
        return SimpleNamespace(structuredContent={"success": True}, content=[])

    monkeypatch.setattr(srv, "_pre_usage_call_tool", fake_inner)
    out = asyncio.run(srv._tool_manager_call_tool_with_usage("any_tool", {}))
    assert "_llm_usage" not in out.structuredContent


def test_the_collector_does_not_leak_into_the_next_call(
        srv, monkeypatch):
    """A tool that raises must not leave the collector installed — the
    next call would inherit it and bill one caller for another's work."""
    async def boom(name, arguments, context=None, convert_result=False):
        lu.report(_rec("before-the-error"))
        raise RuntimeError("tool failed")

    monkeypatch.setattr(srv, "_pre_usage_call_tool", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(srv._tool_manager_call_tool_with_usage("any_tool", {}))

    async def quiet(name, arguments, context=None, convert_result=False):
        return SimpleNamespace(structuredContent={"success": True}, content=[])

    monkeypatch.setattr(srv, "_pre_usage_call_tool", quiet)
    out = asyncio.run(srv._tool_manager_call_tool_with_usage("any_tool", {}))
    assert "_llm_usage" not in out.structuredContent


# ── the deadlock this layer caused once ───────────────────────────────

def test_the_usage_module_is_imported_at_module_scope(srv):
    """A call-time ``from geeViz import llmUsage`` inside the wrapper
    hung the server, and left no error anywhere to find it by.

    ``main()`` starts a daemon thread that prewarms EE and the geeViz
    imports; it holds the ``geeViz`` package import lock for tens of
    seconds. A tool call arriving in that window ran the import ON THE
    EVENT LOOP, which blocked on that lock. The tool itself finished —
    the server logged ``"status": "OK"`` — but its result was never
    serialized back over stdio, so the agent sat on a spinner with no
    traceback, no timeout and no clue.

    The module must therefore be bound before any request is served.
    """
    assert hasattr(srv, "_lu"), (
        "llmUsage is not bound at module scope — if it is imported "
        "inside the wrapper instead, a tool call racing the prewarm "
        "thread hangs the server")


def test_the_wrapper_does_not_import_anything(srv):
    """The general form of the bug. ANY import on this path can block on
    the same lock, not just this one."""
    import inspect
    src = inspect.getsource(srv._tool_manager_call_tool_with_usage)
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    assert "import " not in code, (
        "the call_tool wrapper imports at request time; it runs on the "
        "event loop while the prewarm thread may hold the import lock")


def test_the_reporting_call_sites_do_not_import_either(srv):
    """Same hazard in the libraries — they are imported BY the prewarm
    thread, so a call-time import from inside one contends for exactly
    the lock that thread is holding."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in (root / "googleMapsLib.py", root / "inventoryLib.py",
                 root / "outputLib" / "reports.py"):
        for i, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if "from geeViz import llmUsage" not in line:
                continue
            if line.startswith("from geeViz import llmUsage"):
                continue          # module scope — correct
            offenders.append(f"  {path.name}:{i} {line.strip()}")
    assert not offenders, (
        "llmUsage imported inside a function:\n" + "\n".join(offenders))


# ── the shape the REAL dispatch produces ──────────────────────────────

def test_the_convert_result_tuple_is_handled(srv):
    """FastMCP's actual dispatch passes ``convert_result=True``, and
    that returns a plain ``(content_list, structured_dict)`` TUPLE — not
    a ToolResult.

    This is the shape that matters and the one the first version missed.
    The tuple fell through to the list/tuple branch, whose two items are
    a list and a dict rather than TextContent, so the function returned
    the result untouched: every geeViz LLM call went unbilled, with no
    error anywhere. The tests above all passed, because their fake inner
    returned a ToolResult-shaped object the real dispatch never
    produces.
    """
    structured = {"result": json.dumps({"success": True, "stdout": "ok"})}
    result = ([_Text("ok")], structured)
    srv._attach_llm_usage(result, [_rec()])
    inner = json.loads(structured["result"])
    assert inner["_llm_usage"] == [_rec()]
    assert inner["stdout"] == "ok", "the tool's own payload was damaged"


def test_a_tuple_without_a_structured_dict_is_left_alone(srv):
    """Not every 2-tuple is that shape."""
    pair = ([_Text("a")], [_Text("b")])
    assert srv._attach_llm_usage(pair, [_rec()]) is pair


def test_run_code_attaches_through_the_real_dispatch(srv):
    """End to end on the actual call FastMCP makes, with user code
    reporting from run_code's worker thread.

    Everything between — the ContextVar collector, ``run_in_context``
    carrying it onto the exec thread, the convert_result tuple — has to
    line up, and each of those was wrong at some point. Only a test that
    makes the real call can tell.
    """
    import asyncio

    code = ("import geeViz.llmUsage as lu\n"
            "lu.report({'source': 'geeviz.test', 'response_id': 'rc-1',\n"
            "           'prompt_tokens': 5})\n"
            "print('done')\n")
    out = asyncio.run(srv._tool_manager_call_tool_with_usage(
        "run_code", {"code": code, "session_id": "attach-test"},
        convert_result=True))

    assert isinstance(out, tuple) and len(out) == 2, (
        "FastMCP no longer returns a tuple here — re-check _attach_llm_usage")
    structured = out[1]
    inner = structured
    if len(structured) == 1 and isinstance(structured.get("result"), str):
        inner = json.loads(structured["result"])
    got = inner.get("_llm_usage") or []
    assert [r["response_id"] for r in got] == ["rc-1"], (
        "usage reported inside run_code did not reach the tool result")


# ── the prewarm deadlock, removed rather than locked ──────────────────

def test_there_is_no_prewarm_thread():
    """Three rounds of this decision are recorded in the source.

    A prewarm thread and the first tool call do the SAME heavy
    initialization. Round 1 they raced; round 2 added _init_lock to
    serialize them; round 3 the lock turned the race into a deadlock —
    prewarm holding the lock, wedged inside a numpy C-extension import,
    tool thread blocked acquiring it, neither ever moving.

    Serializing two threads that duplicate each other's work only
    decides which one hangs. One code path is the fix.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "mcp" / "server.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "geeviz-mcp-prewarm" not in code, (
        "the EE prewarm thread is back; it deadlocks against the first "
        "tool call under _init_lock")


def test_the_catalog_prewarm_waits_for_init():
    """The one background thread that remains must not overlap the
    geeViz/numpy import cascade — that concurrency is what wedged the
    other one."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "mcp" / "server.py").read_text(encoding="utf-8")
    i = src.index("def _prewarm_catalogs():")
    body = src[i:i + 500]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "_init_done.wait()" in code, (
        "the catalog prewarm runs alongside global init again")


def test_the_init_gate_is_set_after_the_work_not_during():
    """Setting it mid-cascade would release the catalog thread into
    exactly the concurrent-import window it is meant to avoid."""
    import inspect
    import geeViz.mcp.server as srv
    src = inspect.getsource(srv._ensure_initialized)
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "_init_done.set()" in code, "the gate is never set"
    assert code.index("_ensure_initialized_locked") < code.index("_init_done.set()"), (
        "the gate is set before the init work completes")
