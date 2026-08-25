"""The MCP server must never write non-protocol bytes to stdout.

``geeViz/mcp/server.py`` speaks JSON-RPC over **stdio**. Anything written
to stdout that is not a protocol frame is injected straight into that
stream, desyncs the client's parser, and the in-flight request never
receives a matching response. The client eventually gives up with::

    mcp.shared.exceptions.McpError: Timed out while waiting for response
    to ClientRequest. Waited 300.0 seconds.

which reads like a hung Earth Engine call and sends you looking in
entirely the wrong place. The real cause is a corrupted pipe.

This bit specifically: ``_build_module_tree()`` printed a one-line
summary to stdout, and it is called from ``_ensure_initialized_locked``
— lazily, on the FIRST tool call, not at import. So the line landed in
the middle of a live session and wedged the first turn of every cold
start.

Two categories of print exist in that module and only one is a bug:

* **Diagnostics** (module tree, instruction loading, import failures)
  run outside any capture and MUST target stderr.
* **Tool output** (``map_control`` / export progress) runs while
  ``sys.stdout`` is deliberately swapped for a capture buffer, and its
  text is surfaced to the user in the tool result. Those MUST stay on
  stdout — redirecting them would silently empty the UI panel.

So this cannot be a blanket "no bare print" rule; it has to know the
difference.
"""

import ast
import os

import pytest

SERVER = os.path.join(
    os.path.dirname(__file__), "..", "..", "mcp", "server.py"
)


def _tree():
    with open(SERVER, encoding="utf-8") as fh:
        return ast.parse(fh.read()), fh


def _bare_print_lines():
    """Line numbers of print() calls that do not pass file=."""
    with open(SERVER, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Name) and fn.id == "print"):
            continue
        if not any(kw.arg == "file" for kw in node.keywords):
            out.append(node.lineno)
    return sorted(out)


def _enclosing_function(lineno):
    with open(SERVER, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= lineno <= (node.end_lineno or node.lineno):
                if best is None or node.lineno > best.lineno:
                    best = node
    return best.name if best else "<module>"


# Functions whose stdout is captured on purpose (sys.stdout is swapped
# for a streaming buffer around them, and the text becomes tool output).
_CAPTURED = {"_map_control_inner", "map_control", "export_image"}


def test_diagnostic_prints_do_not_write_to_stdout():
    """Every bare print must live inside a capture-wrapped function.

    A new bare print anywhere else is a latent 300s hang.
    """
    offenders = []
    for lineno in _bare_print_lines():
        fn = _enclosing_function(lineno)
        if fn not in _CAPTURED:
            offenders.append(f"server.py:{lineno} in {fn}()")

    assert not offenders, (
        "these print() calls write to stdout outside a captured context; "
        "stdout is the MCP JSON-RPC pipe, so each one can desync the "
        "protocol and hang the client for 300s. Pass file=sys.stderr:\n  "
        + "\n  ".join(offenders)
    )


def test_module_tree_summary_goes_to_stderr():
    """Regression guard on the specific line that caused the outage."""
    with open(SERVER, encoding="utf-8") as fh:
        src = fh.read()

    idx = src.find("Module tree:")
    assert idx != -1, "module-tree summary line not found"
    # Look at the call this literal belongs to.
    window = src[idx: idx + 400]
    assert "sys.stderr" in window, (
        "the module-tree summary must print to stderr — it is emitted from "
        "_build_module_tree(), which runs lazily on the first tool call, "
        "so on stdout it corrupts a live JSON-RPC session"
    )


def test_captured_prints_are_left_on_stdout():
    """The inverse mistake: don't 'fix' tool output onto stderr.

    map_control swaps sys.stdout for a streaming buffer and injects the
    captured text into its JSON response. Sending those to stderr would
    silently blank the output the user sees.
    """
    captured_prints = [
        ln for ln in _bare_print_lines()
        if _enclosing_function(ln) in _CAPTURED
    ]
    assert captured_prints, (
        "expected map_control's progress prints to remain on stdout; if "
        "they were redirected to stderr the tool's visible output is lost"
    )


def test_build_module_tree_is_called_lazily_not_at_import():
    """Explains why the stdout write was mid-session rather than at boot.

    If this ever moves to import time the hazard changes character, and
    the reasoning in these tests should be revisited.
    """
    with open(SERVER, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    callers = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Name)
                        and sub.func.id == "_build_module_tree"):
                    callers.append(node.name)

    assert callers, "_build_module_tree is never called from a function"
    assert any("initialized" in c for c in callers), (
        f"expected a lazy init caller; found {callers}"
    )
