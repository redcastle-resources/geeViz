"""The two opacity sliders must stay legible at every root font size.

The viewer's layer panel is sized in ``rem`` and its root font-size
moves with the viewport -- 12px on a narrow window, 16px on a wide one,
so every padding, margin and control height in the panel is a third
bigger at one end of the range than the other.

The first cut of the wind slider CSS was measured on a 12px root and
written down in ``px``. On a wide window everything around those numbers
grew and they did not: the gap stayed 9px between two sliders that were
now 3.19px tall instead of 2.39, and the row stayed 38px holding content
that wanted 51. The pair reads as pinched and crowded -- and only at one
end of the range, which is how it survived being looked at.

Measured in a real browser at three root sizes before this was written:

    root   shipped (px)              rem
    12px   row 38.0  gap  9          row 38.4  gap 12
    16px   row 38.0  gap  9   <--    row 51.2  gap 16
    20px   row 38.0  gap  9   <--    row 64.0  gap 20

So this file pins the UNIT, not the appearance. A px length in these
rules is the bug, whatever value it holds, because it cannot track the
thing it has to stay in proportion to.

Comments are stripped before anything is asserted. CSS and JS assertions
in this repo have repeatedly matched their own explanatory comments and
passed vacuously -- the block under test is a JS string literal built
out of concatenated pieces with comments between them, which is exactly
the shape that goes wrong.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "geeViz" / "geeView" / "src" / "js" / "wind-particles.js"


def _strip_comments(js: str) -> str:
    """Drop block comments, and line comments that own their whole line.

    Deliberately NOT trailing ``//`` comments: this file is full of
    ``"https://..."`` inside string literals and a trailing-comment rule
    truncates every one of them. Whole-line is enough here because every
    comment in the stylesheet block sits on its own line -- which is the
    shape that caused the vacuous passes this strip exists to prevent.
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^[ \t]*//.*$", "", js)


def _stylesheet() -> str:
    """Reassemble the CSS the module actually injects.

    It is built as a run of double-quoted pieces joined by ``+``, and a
    selector routinely ends one piece while its declaration block starts
    the next:

        ".wind-two-sliders .wind-speed-opacity-slider," +
        ".wind-two-sliders .wind-particle-opacity-slider" +
        "{clear:right !important;}" +

    Matching rules against the raw source therefore finds selectors with
    no body and bodies with no selector -- the first version of this file
    "passed" four assertions against a single rule because of exactly
    that. Concatenate first, then match.
    """
    src = _strip_comments(SRC.read_text(encoding="utf-8"))
    i = src.index("function injectSliderStyle")
    j = src.index("el.id = STYLE_ID", i)
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', src[i:j]))


@pytest.fixture(scope="module")
def css() -> str:
    """Every rule in that stylesheet whose selector names the row."""
    sheet = _stylesheet()
    rules = [m.group(0) for m in re.finditer(r"[^{}]*\{[^}]*\}", sheet)
             if "wind-two-sliders" in m.group(0)]
    assert rules, f"no wind-two-sliders rules found in:\n{sheet[:400]}"
    return "\n".join(rules)


def test_the_stripper_actually_strips():
    """The guard the rest of the file rests on."""
    assert "drop" not in _strip_comments("  // min-height:38px drop\n")
    assert "drop" not in _strip_comments("keep /* drop */ more")
    assert "keep" in _strip_comments("keep /* drop */ more")
    # ...and leaves URLs in string literals intact, which is why it is
    # whole-line only.
    assert "https://x.example" in _strip_comments('var u = "https://x.example";')


def test_the_stylesheet_reassembly_finds_real_rules(css):
    """If the reassembly broke, every assertion below would pass against
    whatever fragment it happened to salvage."""
    assert css.count("{") >= 3, (
        f"expected the row's several rules, reassembled only:\n{css}")
    assert "clear:right" in css, (
        "the stacking rule is missing -- the reassembly is not seeing the "
        "real stylesheet")


def test_the_row_height_is_in_rem(css):
    """The row has to grow with the sliders it contains. A px min-height
    is right at exactly one root size and too short above it, at which
    point the lower slider crowds the bottom edge."""
    m = re.search(r"min-height\s*:\s*([\d.]+)(px|rem)", css)
    assert m, f"no min-height on the two-slider row:\n{css}"
    assert m.group(2) == "rem", (
        f"row min-height is {m.group(1)}{m.group(2)} -- a fixed height "
        f"cannot hold rem-sized content across root font sizes")
    # 2.1rem is the float stack itself (0.7 stock top + 0.2 + 1.0 gap +
    # 0.2); below that the lower slider leaves the row no matter what
    # the root size is.
    assert float(m.group(1)) >= 2.5, (
        f"min-height {m.group(1)}rem is under what the stack needs")


def test_the_gap_between_the_two_is_in_rem(css):
    """Same reasoning one level down: a fixed gap between two controls
    that scale is the part that reads as 'pinched'."""
    m = re.search(r"margin-bottom\s*:\s*([\d.]+)(px|rem)", css)
    assert m, f"no margin-bottom carrying the gap:\n{css}"
    assert m.group(2) == "rem", (
        f"the slider gap is {m.group(1)}{m.group(2)} -- it will not track "
        f"the sliders it separates")


def test_no_pixel_lengths_survive_anywhere_in_the_row(css):
    """The catch-all. Any nonzero px length in these rules is the same
    bug wearing a different property name."""
    px = [v for v in re.findall(r"[\d.]+px", css) if not v.startswith("0")]
    assert not px, f"fixed pixel lengths in the two-slider rules: {px}\n{css}"


def test_one_declaration_owns_the_gap(css):
    """`clear:right` makes the lower float clear the upper float's
    MARGIN edge, so the spacing is expressible once. Two margins both
    contributing is how it drifted out of proportion in the first place
    -- one of them got tuned and the other was forgotten."""
    assert re.search(r"wind-speed-opacity-slider[^{]*\{[^}]*margin-top\s*:\s*0\b",
                     css), (
        "the lower slider still carries a top margin; the gap is being "
        "set in two places")


def test_the_time_lapse_variant_scales_too(_=None):
    """A lapse stacks its own controls, so it only needs the gap -- but
    it is the same panel and the same root font size."""
    src = _strip_comments(SRC.read_text(encoding="utf-8"))
    m = re.search(
        r"simple-time-lapse-layer-range-first\.wind-particle-opacity-slider"
        r"[^{]*\{[^}]*?margin-top\s*:\s*([\d.]+)(px|rem)", src)
    assert m, "the time lapse slider rule is gone"
    assert m.group(2) == "rem", (
        f"time lapse slider gap is {m.group(1)}{m.group(2)}, not rem")
