"""The same content saved under two names shows once, not twice.

Session f3c49da1 (2026-10-09): to "replace the embedded preview", the
agent saved each new GIF twice, under its new name and over an earlier
GIF's name. Every save is its own chat artifact, so each GIF appeared,
and downloaded, twice. run_code now shows identical files once, prefers
the new name, and tells the model why.
"""
import asyncio
import json
import os
import shutil
import uuid

import pytest

import geeViz.mcp.server as srv


@pytest.fixture
def sid():
    s = "test_dup_" + uuid.uuid4().hex[:10]
    yield s
    shutil.rmtree(os.path.join(srv._BASE_OUTPUT_DIR, s), ignore_errors=True)


def _run(code, s):
    return json.loads(asyncio.run(srv.run_code(code, session_id=s)))


def _shown(out):
    return sorted(os.path.basename(p) for p in __import__("re").findall(r"\]\(([^)]+)\)", out.get("output_markdown") or ""))


def test_the_sessions_double_save_shows_the_new_file_once(sid):
    # an earlier turn's output already exists under the old name
    first = _run("save_file('palmer_snowfield_map_chart.gif', b'GIF89a-old', mode='wb')", sid)
    assert _shown(first) == ["palmer_snowfield_map_chart.gif"]
    # the session's own pattern: the new GIF, then the same bytes over the old name
    out = _run(
        "data = b'GIF89a-new-15-years'\n"
        "save_file('palmer_snowfield_low_years_all_15.gif', data, mode='wb')\n"
        "save_file('palmer_snowfield_map_chart.gif', data, mode='wb')\n", sid)
    assert out["success"] is True
    assert _shown(out) == ["palmer_snowfield_low_years_all_15.gif"], "the new name is the one shown"
    assert "palmer_snowfield_map_chart.gif is identical to palmer_snowfield_low_years_all_15.gif" in out["stdout"]
    assert "does not replace its preview" in out["stdout"]
    # both files are still on disk; only the display is deduplicated
    folder = os.path.join(srv._BASE_OUTPUT_DIR, sid)
    assert os.path.isfile(os.path.join(folder, "palmer_snowfield_map_chart.gif"))


def test_different_files_are_all_shown(sid):
    out = _run("save_file('a.png', b'one', mode='wb')\nsave_file('b.png', b'two', mode='wb')\n", sid)
    assert _shown(out) == ["a.png", "b.png"]
    assert "same content" not in (out["stdout"] or "")


def test_the_helper_prefers_new_names(tmp_path):
    for n, b in (("old.gif", b"x"), ("new.gif", b"x"), ("other.gif", b"y")):
        (tmp_path / n).write_bytes(b)
    kept, note = srv._dedupe_new_outputs(["new.gif", "old.gif", "other.gif"], {"old.gif"}, str(tmp_path))
    assert kept == ["new.gif", "other.gif"]
    assert "old.gif is identical to new.gif" in note
    assert srv._dedupe_new_outputs(["other.gif"], set(), str(tmp_path)) is None


def test_the_rule_is_in_the_instructions():
    from pathlib import Path
    md = (Path(srv.__file__).parent / "agent-instructions.md").read_text(encoding="utf-8")
    i = md.index("**Save each output once, under one name.**")
    rule = md[i:md.index("\n", i)]
    assert "earlier previews are never replaced" in rule
