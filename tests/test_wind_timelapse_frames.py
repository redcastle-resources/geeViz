"""A wind time lapse is N layers behind ONE particle overlay.

``Map.addWindTimeLapse`` adds every forecast hour as its own geeImage
layer, and each one carries ``windParticles``. Read naively, that is
nine particle fields adopted at once, nine canvases stacked on the map,
nine independent flows drawn over each other.

So the frames are grouped: ``viz.timeLapseID`` is the overlay's
identity, the layer id becomes a frame within it, and one overlay
samples whichever frame the lapse is showing. Nothing is torn down
between frames, so the trails keep advecting through each new field
instead of resetting to a fresh scatter on every step.

The part that is easy to get wrong -- and was wrong -- is *which frame
is showing*. A geeImage lapse does not tick checkboxes. The viewer turns
every frame visible at once (``turnOnTimeLapseLayers``) and then raises
one frame's OPACITY (``selectFrame`` -> ``setFrameOpacity``); only a
``tileMapService`` lapse switches by clicking. Selecting on ``visible``
gives a flow that animates beautifully and never leaves frame 0: no
error, no exception, and no tell on screen beyond a two-day forecast in
which the weather never changes.

Driven through node against the real source, so this tests the shipped
file rather than a description of it.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "geeViz" / "geeView" / "src" / "js" / "wind-particles.js"
PROBE = Path(__file__).with_name("wind_timelapse_probe.js")

LAPSE = "GFS-wind-particles"


def _node():
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node not available")
    return exe


@pytest.fixture(scope="module")
def result():
    out = subprocess.run([_node(), str(PROBE), str(SRC)],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_nine_frames_become_one_overlay(result):
    """The whole reason the grouping exists."""
    assert result["adoptedLapse"], "the lapse was never adopted at all"
    assert result["overlayIds"] == ["plain", "tl:" + LAPSE], (
        f"expected one overlay for the lapse and one for the plain layer, "
        f"got {result['overlayIds']}")
    assert result["frameCount"] == 9, (
        f"the overlay is serving {result['frameCount']} frames, not 9")
    assert result["perFrameOverlays"] == 0, (
        f"{result['perFrameOverlays']} frames got their own particle "
        f"overlay — that many flows are drawing on top of each other")


def test_every_frame_is_taken_off_the_map(result):
    """Not just the showing one.

    The frames carry u/v encoded as RGB. A frame left on the map paints
    that encoding over the basemap as a magenta-green wash, and with a
    lapse there are eight of them behind the one being watched.
    """
    slots = result["overlayAfterScan"]
    assert all(s is None for s in slots), (
        f"an encoded u/v raster is still on the map: {slots}")
    # setAt(null), never removeAt: the array is positional and every
    # other layer addresses it by a fixed index.
    assert len(slots) == 10, (
        f"overlayMapTypes went from 10 slots to {len(slots)} — every "
        f"layerId above the particle layers now addresses the wrong tiles")


def test_the_overlay_follows_the_frame_the_lapse_raised(result):
    """Opacity is the discriminator, not the visibility checkbox.

    This is the mutation guard: put the selection back on ``visible``
    and every one of these lands on frame0.
    """
    assert result["atFrame0"]["frameId"] == LAPSE + "-frame0"
    assert result["atFrame4"]["frameId"] == LAPSE + "-frame4", (
        "the lapse raised frame 4 and the particles stayed on "
        f"{result['atFrame4']['frameId']} — the field never advances")
    assert result["atFrame8"]["frameId"] == LAPSE + "-frame8"


def test_the_tile_source_advances_with_the_frame(result):
    """frameId alone proves nothing if the tiles keep coming from
    frame 0: the particles sample DECODED TILES, so the getTileUrl has
    to move too."""
    urls = [result[k]["url"] for k in ("atFrame0", "atFrame4", "atFrame8")]
    assert len(set(urls)) == 3, f"the frames share a tile source: {urls}"
    assert "/0/" in urls[0] and "/4/" in urls[1] and "/8/" in urls[2], urls


def test_the_trails_survive_a_frame_change(result):
    """The point of one overlay per lapse.

    Reseeding on every step would play as a stutter -- the flow would
    restart from a fresh random scatter nine times instead of carrying
    on through an evolving field.
    """
    assert result["particlesSurvivedFrameChange"], (
        "the particles were reseeded on a frame change; the trails "
        "restart from scratch every step")
    assert result["fieldKeyCleared"], (
        "the sampled field was not invalidated, so the new frame's "
        "tiles are decoded and then ignored")


def test_cumulative_mode_picks_the_latest_raised_frame(result):
    """Cumulative mode raises frames 0..current to the SAME opacity.
    The current one is the last of them, not the first."""
    assert result["cumulative"]["frameId"] == LAPSE + "-frame5", (
        f"cumulative mode selected {result['cumulative']['frameId']}, "
        f"expected the newest raised frame")


def test_dimming_a_lapse_does_not_stop_it(result):
    """Opacity zero is not the same as switched off.

    With the raster and the particles on independent controls, dragging
    the raster down to nothing takes every frame to opacity 0 and leaves
    no frame looking "raised" — but the lapse is still playing and still
    ticked. Reading that as off would stop the particles the user was
    trying to look at on their own.
    """
    assert result["whenDimmedToZero"]["running"] is True, (
        "dimming the raster to zero stopped the particles")
    assert result["whenDimmedToZero"]["frameId"] == LAPSE + "-frame4", (
        "the frame was lost when every opacity went to zero")


def test_a_lapse_that_is_switched_off_draws_nothing(result):
    """The other half. Animating a field nobody can see burns a core
    for nothing, and this is what "off" actually looks like: no frame
    visible."""
    assert result["whenSwitchedOff"]["running"] is False


def test_a_plain_wind_layer_is_still_driven_by_visibility(result):
    """The opacity rule is for lapses only.

    A single ``addWindLayer`` has no lapse controlling it; its checkbox
    is the whole story, and it sits at opacity 1 the entire time. Read
    through the lapse rule it would be indistinguishable from a raised
    frame and would never switch off.
    """
    assert result["plain"]["adopted"] and result["plain"]["isLapse"] is False
    assert result["plain"]["running"] is True
    assert result["plainAfterHide"] is False, (
        "unchecking a plain wind layer left the particles running")
    assert result["plainAfterShow"] is True


def test_the_canvas_stacks_at_the_showing_frames_slot(result):
    """The particle canvas shares the ``overlayLayer`` pane with the
    rasters, so a z-index is what orders it against them.

    A lapse's ``st.id`` is the group key, which is not a registry entry
    at all — looked up by it the layerId was never found, the canvas
    kept whatever z-index it had, and dragging the lapse in the layer
    list moved the rasters while the particles stayed put.
    """
    assert result["zAtFrame3"] == "3", (
        f"the canvas is at z-index {result['zAtFrame3']!r}, not the "
        f"showing frame's layerId")
    assert result["zAfterReorder"] == "7", (
        "the canvas did not follow updateMapLayerOrder — a z-index "
        "written once keeps the order the list had at adoption")


def test_the_opacity_slider_reaches_the_particles(result):
    """It did nothing at all on a lapse.

    The particles skipped opacity inheritance entirely for a lapse,
    because a lapse's per-frame opacities are the frame-SELECTION
    mechanism — eight of nine sit at 0 at any instant, and taking one as
    an alpha would make the flow lurch between invisible and full as it
    played. But the frame that is RAISED carries exactly the lapse's own
    opacity setting, so reading that one frame is a faithful reading of
    the slider.
    """
    assert result["opacityAtFull"] == 1, (
        f"at a full slider the layer should be undimmed, got "
        f"{result['opacityAtFull']}")
    assert result["opacityAtHalf"] == 0.5, (
        f"dragging the lapse's opacity to 50% left the particles at "
        f"{result['opacityAtHalf']} — the slider does not reach them")
    assert result["strokeAlphaUntouched"] == 0.9, (
        "the slider rewrote the stroke alpha; that is the trail's SHAPE "
        "— taper and head boost — not a user preference, and rewriting "
        "it discards the configured particleOpacity")


def test_the_opacity_change_is_eased(result):
    """A slider drags in 0.05 steps and a playing lapse re-raises a
    frame on every step. Applying either instantly reads as a jump
    rather than as a control, so the dimmer rides on the canvas ELEMENT
    where CSS can transition it."""
    assert result["fadeIsEased"], (
        "the canvas has no opacity transition — every change lands "
        "instantly and reads as flicker")
    assert result["bothCanvasesEased"], (
        "the merged layer's two canvases are not both eased")


def test_the_frame_gap_does_not_blank_the_layer(result):
    """selectFrame() zeroes EVERY frame and then raises one.

    A refresh landing between those two steps sees no raised frame at
    all. Reading that as an opacity would hand the layer a zero alpha on
    every step of a playing lapse — a strobe, at the frame rate. The
    last positive value has to stand until a new one arrives.
    """
    assert result["opacityDuringFrameGap"] == 0.5, (
        f"the layer went to {result['opacityDuringFrameGap']} while the "
        f"lapse was between frames")


def test_the_opacity_slider_does_not_compound(result):
    """Scaled off the PRISTINE configured value, not off the last result.

    refreshRunState runs on a 500 ms interval, so multiplying
    cfg.opacity into itself would fade the particles to nothing within a
    few seconds of sitting still — a bug that looks like a rendering
    fault rather than an arithmetic one.
    """
    assert result["opacityAfterIdleTicks"] == result["opacityAtHalf"], (
        f"opacity drifted from {result['opacityAtHalf']} to "
        f"{result['opacityAfterIdleTicks']} on idle ticks alone")


# ---------------------------------------------------------------------------
# The merged layer: one lapse drawing both halves
# ---------------------------------------------------------------------------


def test_the_merged_layer_gets_its_own_raster_canvas(result):
    """Two canvases, not one.

    frame() clears and repaints the trails thirty times a second; the
    speed field only changes when the view or the hour does. Sharing a
    canvas would mean ~800,000 palette lookups per animation frame to
    redraw a picture that did not change.
    """
    assert result["merged"]["adopted"]
    assert result["merged"]["frames"] == 3
    assert result["merged"]["speedRaster"] is True
    assert result["mergedHasSpeedCanvas"], (
        "no raster canvas — the merged layer would show trails over "
        "nothing")


def test_the_query_is_retargeted_once_the_panel_exists(result):
    """The retry path, which is the one that happens.

    The merged layer draws u/v bytes; clicking it would report those
    bytes as if they were a wind reading. queryObj is built
    asynchronously and is NOT there when the layer is adopted, so
    retargeting has to keep trying rather than give up on first look.
    """
    assert result["retargetBeforePanel"] is False, (
        "the probe did not exercise the retry path")
    assert result["retargetAfterPanel"] is True, (
        "the query was never retargeted; the inspector reports the "
        "encoding")
    assert result["queryItemNow"] == "SERIALIZED_SPEED_IC", (
        "queryObj is not pointed at the speed collection")


def test_the_two_opacities_are_independent(result):
    """The whole point of one client owning both renders.

    The lapse's own slider drives the raster — it is the layer-shaped
    thing on screen — and the injected slider drives the trails. Moving
    either must leave the other exactly where it was; with two Earth
    Engine layers that was not possible without a second slider in the
    viewer bundle.
    """
    assert result["speedAlphaAt40"] == 0.4, (
        f"the lapse slider did not reach the raster: "
        f"{result['speedAlphaAt40']}")
    assert result["particleAlphaUnaffected"] == 1, (
        f"dimming the raster also dimmed the trails: "
        f"{result['particleAlphaUnaffected']}")
    assert result["speedAlphaStill40"] == 0.4, (
        "moving the particle slider moved the raster too")
    assert result["particleAlphaAtHalf"] == 0.5, (
        f"the particle slider did not reach the trails: "
        f"{result['particleAlphaAtHalf']}")


def test_the_raster_paints_from_the_tiles_already_decoded(result):
    """No extra requests. u and v are in the red and green of the tiles
    this module fetches anyway, and speed is sqrt(u^2 + v^2) — the same
    bytes, read a second way."""
    assert result["paintDrew"], "the raster painted nothing"
    assert result["paintTileDraws"] > 0
    assert result["paintCached"], (
        "a complete paint was not cached, so it repaints every "
        "animation frame")


def test_the_raster_repaints_only_when_it_must(result):
    """Skipped on an unchanged view, redrawn on a new hour. Getting
    either wrong is expensive in opposite directions: a stale raster
    under a moving lapse, or ~800,000 palette lookups per frame."""
    assert result["paintSkippedWhenUnchanged"], (
        "the raster repainted with nothing changed")
    assert result["paintRedrewOnFrameChange"], (
        "the raster did not repaint when the hour advanced — the colors "
        "would stay on the previous frame's wind")


def test_an_incomplete_raster_backs_off(result):
    """The lockup guard.

    A repaint is tens of tiles of per-pixel palette lookup. While a
    lapse streams the next hour the paint keeps coming out incomplete,
    and retrying at the animation rate asked for tens of millions of
    operations a second — enough that the tab stopped answering script
    at all, which is a worse failure than a slow one because nothing on
    the page still works.
    """
    assert result["paintBackoffArmed"], (
        "an incomplete raster did not arm the back-off; it will repaint "
        "on every animation frame")
    assert result["paintHeldWhileBackedOff"], "the back-off did not hold"
    assert result["paintResumedAfterBackoff"], (
        "the back-off never released — the raster would stay half-drawn")


def test_switching_the_layer_off_wipes_both_canvases(result):
    """Reported from a real map: the trails vanished and the speed
    raster stayed painted over the ground.

    Only the particle context was being cleared. The raster is a SECOND
    canvas, and tick() does not redraw it while the overlay is stopped —
    so a stale paint simply stayed there, with nothing in the layer
    panel able to remove it. Unchecking a layer and having half of it
    remain is the kind of failure that makes a viewer feel broken.
    """
    assert result["offOnRunningWhileOn"] is True, (
        "the probe never got the layer running")
    assert result["offOnRunningWhileOff"] is False
    assert result["offOnWipedBothCanvases"], (
        "switching the layer off cleared only one canvas — the speed "
        "raster is still painted over the map")
    assert result["offOnSpeedKeyForgotten"], (
        "the paint key survived the layer being switched off, so "
        "switching it back on would match and skip the repaint")


def test_switching_it_back_on_repaints(result):
    """The other half. Forgetting the key on the way out is only right
    if coming back in actually redraws."""
    assert result["offOnRunningAfterBack"] is True, (
        "the layer did not restart when switched back on")
    assert result["offOnRepaintsOnReturn"], (
        "no repaint is queued on return; the map would come back with "
        "an empty raster")


def test_a_removed_layer_takes_its_overlay_with_it(result):
    """``Map.clearMap()`` empties the registry, and an overlay whose
    frames have all disappeared has nothing left to draw.

    Left behind it is invisible — the canvases get cleared — but it
    accumulates one canvas pair per wind layer ever added, each still
    answering the map's idle and resize handlers, and each still holding
    its decoded tiles. A frame's worth of those is megabytes, and a
    lapse holds one per frame.
    """
    assert result["dropHadOverlay"], "the probe never adopted anything"
    # However many the probe happened to build -- the point is that
    # none survive an empty registry, not that there was exactly one.
    assert result["dropAdoptedBefore"] >= 1
    assert result["dropAdoptedAfter"] == 0, (
        "the overlay outlived every layer it was drawing")
    assert result["dropStopped"] is True
    assert result["dropCanvasesReleased"], (
        "the canvases are still in the overlay pane")
    assert result["dropTilesReleased"], (
        "the decoded tiles were not released — that is the big "
        "allocation here")


def test_the_raster_opacity_comes_from_viz(result):
    """``viz.opacity`` is the layer's opacity, and the raster is the
    layer-shaped half of this layer — so that is what it starts at.

    geeViz sets ``layer.opacity`` from ``viz.opacity`` (defaulting to
    1), and the raster reads it. The particle canvas deliberately does
    NOT: it has its own control, so moving one must leave the other
    exactly where it was.
    """
    assert result["vizOpacityRaster"] == 0.6, (
        f"a layer added with opacity 0.6 started its raster at "
        f"{result['vizOpacityRaster']}")
    assert result["vizOpacityRasterFull"] == 1, (
        "the raster did not follow viz.opacity back to full")
    assert result["vizOpacityLeavesParticles"] == 0.3, (
        f"viz.opacity moved the trails too — they are on their own "
        f"control and sat at {result['vizOpacityLeavesParticles']}")
