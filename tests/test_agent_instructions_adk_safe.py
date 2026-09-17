"""``agent-instructions.md`` must survive ADK's instruction interpolation.

This file is loaded verbatim as the ADK system instruction. Before the
model ever sees it, ADK runs ``inject_session_state`` over it, which
substitutes every ``{...}`` with a session-state value and raises
``KeyError`` when the key is missing. There is no try/except around that
call, so a single bad brace does not degrade one feature -- it kills
every chat turn on the tenant, at the first LLM request:

    KeyError: 'Context variable not found: `x`.'

Observed: a plotly hover-template example added to this file contained
``%{x}``. ADK read ``x`` as a session key. Every request 500'd.

The rule, from ADK's own ``_is_valid_state_name``: braces holding a bare
identifier get resolved. Braces holding anything else -- notably anything
with a colon, which covers every plotly format spec like ``%{y:.1f}`` --
are passed through untouched. So hover templates are safe if and only if
the placeholder carries a format spec.

The check is reimplemented here rather than imported, deliberately:
geeViz does not depend on google-adk, and this must run in geeViz's own
test environment.
"""
import re
from pathlib import Path

import pytest

INSTRUCTIONS = (Path(__file__).resolve().parents[1]
                / "mcp" / "agent-instructions.md")

# Mirrors google.adk.utils.instructions_utils._async_sub
_BRACE_RE = r"{+[^{}]*}+"
_PREFIXES = ("app:", "user:", "temp:")


def _adk_would_resolve(var_name: str) -> bool:
    """Mirror of ADK's ``_is_valid_state_name``.

    Valid state name = a bare identifier, or ``<known prefix>:<identifier>``.
    Everything else ADK returns untouched.
    """
    parts = var_name.split(":")
    if len(parts) == 1:
        return var_name.isidentifier()
    if len(parts) == 2 and (parts[0] + ":") in _PREFIXES:
        return parts[1].isidentifier()
    return False


def _offenders(text: str):
    out = []
    for m in re.finditer(_BRACE_RE, text):
        var = m.group().strip("{}")
        optional = var.endswith("?")          # ADK's opt-out suffix
        if optional:
            continue
        if _adk_would_resolve(var):
            out.append((text[:m.start()].count("\n") + 1, m.group()))
    return out


def test_the_mirror_matches_adks_rule():
    """Guard the guard. If this drifts from ADK the test passes while the
    instruction file is broken."""
    assert _adk_would_resolve("x") is True
    assert _adk_would_resolve("user:name") is True
    assert _adk_would_resolve("y:.1f") is False          # plotly format spec
    assert _adk_would_resolve("customdata:.1f") is False
    assert _adk_would_resolve("'df': DataFrame") is False
    assert _adk_would_resolve("") is False


def test_the_file_exists():
    assert INSTRUCTIONS.is_file(), INSTRUCTIONS


def test_no_brace_expression_would_be_resolved_by_adk():
    """The whole point. A bare ``{word}`` anywhere in this file takes the
    tenant down at the first chat turn, with a traceback that names ADK
    and gives no hint that a markdown file caused it."""
    bad = _offenders(INSTRUCTIONS.read_text(encoding="utf-8"))
    assert not bad, (
        "these brace expressions will be treated as ADK session-state "
        "variables and raise KeyError on every chat turn: "
        + ", ".join(f"line {ln}: {raw}" for ln, raw in bad)
        + " -- give the placeholder a format spec (e.g. %{y:.1f}) or "
          "rephrase so the braces do not hold a bare identifier"
    )


@pytest.mark.parametrize("snippet,expect_bad", [
    ("hovertemplate='%{x}'", True),                      # the bug
    ("hovertemplate='%{y:.1f}'", False),                 # safe
    ("hovertemplate='%{customdata:.1f}'", False),        # safe
    ("returns {'df': DataFrame, 'chart': Figure}", False),
    ("use {tenant} here", True),
])
def test_detector_catches_the_shapes_that_matter(snippet, expect_bad):
    assert bool(_offenders(snippet)) is expect_bad
