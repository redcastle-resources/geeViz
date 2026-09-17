"""``hovertemplate`` on summarize_and_chart, and the mutate-don't-rebuild rule.

Hover text was the one presentational thing the function could not
express. Observed cost, from a real agent session: asked for a
temperature chart, it called ``summarize_and_chart`` correctly, got back
a perfectly good Figure, then discarded it and rebuilt the whole thing
with ``go.Figure()`` and four hand-written ``add_trace`` calls -- 86
lines -- for one reason, stated in its own code comment: "custom styling,
hover templates, and both F and C".

Rebuilding is not free. It throws away the tick-label capping,
class-label truncation and layout defaults this function sets, and
re-derives series that ``result['df']`` already holds. When the same
request was answered by saving ``result['chart']`` directly it took 14
lines.

So: one parameter for the common case, and a documented
``update_traces`` path for the per-trace case.

Read as TEXT rather than imported, deliberately. Importing ``charts``
costs this file twice over:

* ``charts`` -> ``gee2Pandas`` evaluates ``ee.Reducer.first()`` at import
  time, so it needs a live EE session for assertions that are purely
  about source.
* it binds ``geeViz.geeView`` as an attribute of the ``geeViz`` package.
  ``test_esriLib`` stubs that name in ``sys.modules`` and then does
  ``import geeViz.geeView as gv``, which resolves through
  ``getattr(geeViz, 'geeView')`` FIRST -- so the real module wins and the
  stub is silently bypassed. This file sorts earlier alphabetically, so
  importing at module scope broke twelve esriLib tests in the full suite
  while passing in isolation.
"""
import re
from pathlib import Path

import pytest

CHARTS = Path(__file__).resolve().parents[1] / "outputLib" / "charts.py"
SRC = CHARTS.read_text(encoding="utf-8", errors="replace")

HT = "%{y:.1f} degF<extra></extra>"


def _no_comments(src: str) -> str:
    """Drop ``#`` comment lines before asserting on source.

    Required by convention here: source-grepping tests in this repo have
    repeatedly matched their own explanatory comments and passed
    vacuously. The block under test sits directly beneath a comment that
    itself mentions ``update_traces``.
    """
    return "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))


def test_the_comment_stripper_works():
    assert _no_comments("a\n  # b\nc") == "a\nc"


def _func() -> str:
    """Source of summarize_and_chart, comments stripped."""
    i = SRC.index("def summarize_and_chart(")
    m = re.search(r"\ndef [a-z_]+\(", SRC[i + 10:])
    return _no_comments(SRC[i:i + 10 + m.start()] if m else SRC[i:])


def _hook() -> str:
    """The shared return hook every chart type passes through."""
    f = _func()
    i = f.index("def _apply_axis_overrides")
    return f[i:f.index("return result_dict", i)]


def _docstring() -> str:
    i = SRC.index("def summarize_and_chart(")
    j = SRC.index('"""', i)
    return SRC[j + 3:SRC.index('"""', j + 3)]


# ── the parameter exists and defaults to off ────────────────────────────

def test_hovertemplate_is_a_parameter():
    sig = SRC[SRC.index("def summarize_and_chart("):SRC.index("):", SRC.index(
        "def summarize_and_chart("))]
    assert "hovertemplate=None" in sig, "not in the signature"


def test_it_defaults_to_none():
    """Plotly's own default hover is good; this must be opt-in so that no
    existing caller's chart changes."""
    sig = SRC[SRC.index("def summarize_and_chart("):SRC.index("):", SRC.index(
        "def summarize_and_chart("))]
    assert re.search(r"hovertemplate\s*=\s*None", sig)


# ── it is wired where every chart type passes through ───────────────────

def test_it_is_applied_in_the_shared_return_hook():
    """Sankey, scatter, histogram, per-feature and standard charts all
    return through _apply_axis_overrides. Wiring it at one trace-building
    site instead would reach one chart type and silently miss the rest."""
    assert "fig.update_traces(hovertemplate=hovertemplate)" in _hook()


def test_it_is_guarded_on_none():
    """Passing hovertemplate=None to update_traces would CLEAR plotly's
    default hover, turning an opt-in feature into a regression for every
    caller who never asked for it."""
    assert "if hovertemplate is not None" in _hook()


def test_a_bad_template_does_not_cost_the_chart():
    """Same posture as the axis overrides beside it: the figure is the
    thing the caller waited on an EE reduction for."""
    hook = _hook()
    i = hook.index("update_traces(hovertemplate")
    assert "except Exception" in hook[i:i + 260]


def test_sankey_html_is_not_mistaken_for_a_figure():
    """Sankey returns an HTML string, not a Figure. The hasattr guard is
    what keeps that path from raising."""
    assert 'hasattr(fig, "update_traces")' in _hook()


# ── the documented escape hatch ─────────────────────────────────────────

def test_the_docstring_says_mutate_not_rebuild():
    """The fix is only half a fix if the next agent still reaches for
    go.Figure(). The docstring is where it looks."""
    doc = _docstring()
    assert "update_traces" in doc
    assert "go.Figure()" in doc
    assert "hovertemplate" in doc


def test_the_docstring_shows_the_per_trace_selector():
    """One template for every trace is the common case; naming a single
    trace is the case that drove the rebuild."""
    assert "selector=dict(name=" in _docstring()


# ── behaviour, against a real reduction ─────────────────────────────────

@pytest.mark.network
def test_it_reaches_every_trace_and_keeps_the_layout():
    """The only test here that needs the module imported, so it is the
    only one that pays for EE. Skips rather than errors when EE is not
    available -- a source assertion must never depend on credentials."""
    ee = pytest.importorskip("ee")
    try:
        from geeViz.outputLib import charts as cl
        ee.Number(1).getInfo()
    except Exception as exc:                                # noqa: BLE001
        pytest.skip(f"EE unavailable: {str(exc)[:80]}")

    slc = ee.Geometry.Point([-111.891, 40.7608]).buffer(8000)
    ic = (ee.ImageCollection("OREGONSTATE/PRISM/ANm")
          .filterDate("2025-01-01", "2025-12-31")
          .map(lambda i: i.select("tmean").multiply(1.8).add(32)
               .rename("Average_Temp")
               .copyProperties(i, ["system:time_start"])))
    r = cl.summarize_and_chart(ic, geometry=slc, scale=4000,
                               date_format="YYYY-MM", title="SLC 2025",
                               chart_type="line+markers", hovertemplate=HT)
    fig = r["chart"]
    assert fig.data, "no traces"
    assert all(t.hovertemplate == HT for t in fig.data)
    # the override must not have cost the title
    assert fig.layout.title.text == "SLC 2025"
    assert len(r["df"]) == 12
