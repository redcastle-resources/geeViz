"""``module=`` must accept the name people actually type.

``geeViz.outputLib.thumbs`` is the real import path, so it is the first
thing anyone reaches for — and it resolved to nothing, while the
unprefixed ``outputLib.thumbs`` worked. From a caller's side those two
outcomes are indistinguishable from "that function does not exist", so
the response is to guess another spelling rather than to stop.

One recorded session spent EIGHT ``search_codebase`` calls locating a
single function, cycling ``thumbs`` / ``outputLib.thumbs`` /
``geeViz.outputLib.thumbs`` / ``geeViz.outputLib.thumb``. The
instructions already say "stop after at most 2 attempts"; the tool was
making that advice impossible to follow.
"""
import pytest


@pytest.fixture(scope="module")
def srv():
    import geeViz.mcp.server as _srv
    _srv._build_module_tree()
    assert len(_srv._MODULE_TREE) > 20, "module tree did not build"
    return _srv


# Every spelling of the same module that a caller might reasonably use.
@pytest.mark.parametrize("spelling,expected", [
    ("thumbs", "thumbs"),
    ("outputLib.thumbs", "thumbs"),
    ("geeViz.outputLib.thumbs", "thumbs"),
    ("GEEVIZ.OUTPUTLIB.THUMBS", "thumbs"),
    ("tl", "thumbs"),
    ("charts", "charts"),
    ("outputLib.charts", "charts"),
    ("geeViz.outputLib.charts", "charts"),
    ("cl", "charts"),
])
def test_equivalent_spellings_resolve_to_one_module(srv, spelling, expected):
    name, mod = srv._resolve_module(spelling)
    assert name == expected, f"{spelling!r} did not resolve"
    assert mod is not None


@pytest.mark.parametrize("spelling", [
    "geeViz.getImagesLib", "geeViz.weather", "geeViz.geeView",
])
def test_the_qualified_path_works_for_top_level_modules_too(srv, spelling):
    """It is the path in every import line in the docs."""
    name, mod = srv._resolve_module(spelling)
    assert mod is not None, f"{spelling!r} did not resolve"


def test_a_genuine_typo_still_fails(srv):
    """The prefix strip must not turn "not found" into a fuzzy match —
    a wrong answer is worse than a clear miss, and the caller's next
    move should be to check the name, not to trust a near-miss."""
    for bad in ("geeViz.outputLib.thumb", "geeViz.nosuchmodule",
                "outputLib.charrts"):
        name, mod = srv._resolve_module(bad)
        assert mod is None, f"{bad!r} resolved to {name!r}"


def test_the_prefix_is_stripped_only_at_the_front(srv):
    """``geeViz`` appearing later in a path is part of the name."""
    name, mod = srv._resolve_module("outputLib.geeViz")
    assert mod is None


def test_bare_geeviz_does_not_resolve_to_something_arbitrary(srv):
    """Stripping the prefix off "geeViz." alone leaves an empty string,
    which must not match the first entry in any table."""
    for probe in ("geeViz.", "geeViz"):
        name, mod = srv._resolve_module(probe)
        if mod is not None:
            assert name not in ("charts", "thumbs"), (
                f"{probe!r} resolved to an arbitrary submodule {name!r}")
