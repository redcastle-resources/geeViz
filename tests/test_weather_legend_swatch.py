"""The particle layer's legend entry.

The viewer renders a class legend entry as
``<span style='border:...;background:<value>'>`` and ``addColorHash``
passes any value that is not a bare hex straight through. That is the
whole mechanism: the swatch is a CSS background, so it can draw the
particle itself instead of a flat chip, with no new rendering code and
the same border and spacing as every other legend row.

Two things have to hold for that to keep working, and neither is
visible from the map:

* the value must NOT look like a bare hex, or ``addColorHash`` prepends
  a ``#`` and the whole declaration becomes invalid;
* the numbers must come from the same place ``wind-particles.js`` draws
  with, or the key slowly stops describing the layer.

Offline -- this is string construction, no Earth Engine.
"""
import re

import pytest

PALETTE = ["#2b83ba", "#abdda4", "#ffffbf", "#fdae61", "#d7191c"]


def _swatch(**kw):
    import geeViz.weather as wx
    base = dict(rgb=(255, 255, 255), opacity=0.9, taper=2.1,
                head_boost=1.6, max_width=3.0, palette=PALETTE)
    base.update(kw)
    return wx._particle_swatch(**base)


def _alphas(css, rgb=(255, 255, 255)):
    """The trail's alpha stops, in order along the streak."""
    pat = r"rgba\(%d,%d,%d,([0-9.]+)\)" % rgb
    return [float(a) for a in re.findall(pat, css)]


def test_the_value_is_not_mistaken_for_a_hex_colour():
    """``addColorHash`` prepends '#' to anything ``isHexColor`` accepts.
    If that ever fired on this, the span's background becomes
    ``#linear-gradient(...)`` and the swatch renders as nothing."""
    css = _swatch()
    assert not re.fullmatch(r"#?[0-9a-fA-F]{3,8}", css.strip())
    assert css.startswith("linear-gradient(")


def test_the_trail_brightens_toward_the_head():
    """A comet, not a bar. Alpha rises along the streak and the leading
    stop is the brightest -- the same shape the renderer draws."""
    a = _alphas(_swatch())
    rising = a[:-1]          # the last stop is the cut back to zero
    assert rising == sorted(rising), f"alpha does not rise: {a}"
    assert max(a) > 0.9, f"no bright head: {a}"
    assert a[0] == 0.0 and a[-1] == 0.0, f"streak is not inset: {a}"


def test_the_head_uses_headBoost_and_the_trail_uses_taper():
    """Not free-chosen numbers: they are read from the same viz keys the
    renderer uses, so the key cannot drift from the map."""
    import geeViz.weather as wx
    assert max(_alphas(_swatch(opacity=0.5, head_boost=1.6))) == pytest.approx(
        0.8, abs=0.01)
    # Clamped at 1, as the renderer clamps it.
    assert max(_alphas(_swatch(opacity=0.9, head_boost=3.0))) == 1.0
    # A stronger taper pushes the fade toward the tail, so the mid-trail
    # stops get FAINTER while the head is untouched.
    soft = _alphas(_swatch(taper=1.0))
    hard = _alphas(_swatch(taper=3.0))
    assert hard[2] < soft[2], (soft, hard)


def test_the_streak_thickness_follows_particleMaxWidth():
    assert "100% 3px" in _swatch(max_width=3.0)
    assert "100% 6px" in _swatch(max_width=6.0)
    # Floored, so a hairline default is still visible in a 12 px swatch.
    assert "100% 2px" in _swatch(max_width=0.4)


def test_the_background_is_the_speed_ramp_at_low_opacity():
    """The second half of what the layer shows. On the map the particles
    are always over that ramp, so a swatch on a flat ground shows the
    comet in a context it never appears in."""
    css = _swatch(ramp_opacity=0.5)
    for hexc in PALETTE:
        r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
        assert f"rgba({r},{g},{b},0.50)" in css, (
            f"{hexc} is not in the swatch ramp")
    # Faded, not the real thing: the speed raster has its own colour bar
    # and that is the one to read values off.
    assert "1.00)" not in css.split("linear-gradient", 2)[2]


def test_the_ramp_alpha_is_adjustable_and_independent_of_the_comet():
    """One opacity on the element would fade both. The alpha is baked
    per stop precisely so the comet stays at full strength."""
    faint = _swatch(ramp_opacity=0.2)
    strong = _swatch(ramp_opacity=0.8)
    assert "0.20)" in faint and "0.80)" in strong
    assert max(_alphas(faint)) == max(_alphas(strong)), (
        "changing the ramp opacity changed the comet")


def test_it_falls_back_to_a_flat_chip_without_a_palette():
    """A caller passing no palette still gets a readable swatch rather
    than a transparent box."""
    assert _swatch(palette=None).endswith("#24303a")
    assert _swatch(palette=[]).endswith("#24303a")
    assert _swatch(palette=["#abc"]).endswith("#24303a")


def test_addWindLayer_puts_this_on_the_particle_layer():
    """The wiring. The swatch can be perfect and never reach the map."""
    import geeViz.weather as wx
    import inspect
    src = inspect.getsource(wx.addWindLayer)
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    assert "_particle_swatch(" in code, (
        "addWindLayer no longer builds the swatch")
    assert "classLegendDict" in code
    assert "palette=palette" in code, (
        "the swatch is not being given the layer's own speed ramp")


def test_the_particle_colour_is_what_is_drawn():
    """Whatever particleColor says, in the swatch too -- two wind layers
    up at once are told apart by exactly this."""
    import geeViz.weather as wx
    css = wx._particle_swatch(wx._rgb_of("#ffe066"), 0.9, 2.1, 1.6, 3.0,
                              palette=PALETTE)
    assert "rgba(255,224,102," in css
    assert _alphas(css, (255, 224, 102)), "no trail in the particle colour"


def test_rgb_parsing_is_forgiving_but_not_silent_about_shape():
    import geeViz.weather as wx
    assert wx._rgb_of("#ffe066") == (255, 224, 102)
    assert wx._rgb_of("ffe066") == (255, 224, 102)
    assert wx._rgb_of("#fff") == (255, 255, 255)
    # A legend chip is not worth failing a map layer over.
    assert wx._rgb_of("not-a-colour") == (255, 255, 255)
