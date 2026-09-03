"""Unpickling is arbitrary code execution, and the sandbox hands out a
file-write primitive.

Found while auditing whether scipy / scikit-learn / statsmodels could be
added safely. They can — but the audit turned up an escape that needed
NONE of them, using only what the sandbox already provides:

    save_file('x.pkl', <bytes whose __reduce__ calls anything>)
    pd.read_pickle(path)              -> attacker code ran
    np.load(path, allow_pickle=True)  -> attacker code ran

Both halves are legitimate in isolation. ``save_file`` exists so the
agent can hand the user a GIF or a report; pandas and numpy are the
point of the REPL. The ``pickle`` MODULE was already blocked, which is
what made this look covered — the hole is that several available
libraries will unpickle on your behalf from a trusted stack frame, so
neither the import blocklist nor the audit hook ever sees it.

Blocking the READ side is the narrow fix. Nothing in a geospatial
analysis needs to unpickle a file the same session just wrote.
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "mcp" / "server.py").read_text(encoding="utf-8")


def _code_only(text):
    out = []
    for line in text.splitlines():
        in_s, q, buf = False, "", []
        for i, ch in enumerate(line):
            if in_s:
                buf.append(ch)
                if ch == q and (i == 0 or line[i - 1] != "\\"):
                    in_s = False
            elif ch in "\"'":
                in_s, q = True, ch
                buf.append(ch)
            elif ch == "#":
                break
            else:
                buf.append(ch)
        out.append("".join(buf))
    s = "\n".join(out)
    try:
        tree = ast.parse(s)
    except SyntaxError:
        return s
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            b = getattr(node, "body", None)
            if (b and isinstance(b[0], ast.Expr)
                    and isinstance(b[0].value, ast.Constant)
                    and isinstance(b[0].value.value, str)):
                s = s.replace(b[0].value.value, "")
    return s


CODE = _code_only(SRC)


def test_the_stripper_works():
    assert "read_pickle" not in _code_only("x = 1  # read_pickle danger\n")


def test_unpickling_call_names_are_blocked():
    assert "_UNPICKLING_CALLS" in CODE, "no deserialization blocklist exists"
    m = re.search(r"_UNPICKLING_CALLS = frozenset\(\{(.*?)\}\)", CODE, re.S)
    assert m, "could not read the blocklist"
    names = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    assert "read_pickle" in names, "pandas read_pickle is not blocked"


def test_the_check_is_wired_into_the_ast_pass():
    """A blocklist nothing consults is decoration."""
    assert "_fname in _UNPICKLING_CALLS" in CODE, (
        "the blocklist is defined but never consulted")


def test_allow_pickle_true_is_refused():
    """np.load is legitimate; np.load(allow_pickle=True) is not."""
    assert 'allow_pickle' in CODE
    assert re.search(r'_kw\.arg == "allow_pickle"', CODE), (
        "allow_pickle= is not inspected on load() calls")


def test_allow_pickle_false_is_still_permitted():
    """Explicitly passing False is the safe form and must not be broken —
    the check has to look at the VALUE, not just the keyword's presence."""
    assert "_kw.value.value is False" in CODE, (
        "the guard refuses allow_pickle=False as well, which blocks the "
        "safe spelling people write to be explicit")


def test_the_guard_is_sandbox_scoped():
    """Local/stdio use is unrestricted by design; this must not leak into
    it and break someone's notebook."""
    i = CODE.index("_fname in _UNPICKLING_CALLS")
    window = CODE[max(0, i - 700):i]
    assert "_SANDBOX_ENABLED" in window, (
        "the deserialization guard is not gated on sandbox mode")


def test_pickle_module_is_still_blocked_too():
    """Defense in depth: the module blocklist is the first door, this is
    the second. Removing either leaves the other."""
    assert '"pickle"' in CODE
