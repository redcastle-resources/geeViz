"""Rasterize a Plotly figure to PNG, and get Chrome if it is missing.

``fig.to_image()`` is Plotly's only supported way to turn a figure into
a raster. It has exactly two engines — kaleido (the default) and orca
(deprecated, removal announced) — and both drive an external browser,
because a Plotly figure is JavaScript. There is no pure-Python path.

kaleido **0.x bundled its own Chromium**. kaleido **1.0 dropped it** and
now requires a real Chrome. geeViz declared ``kaleido`` with no ceiling,
so a rebuild after 1.0 shipped quietly replaced a self-contained
renderer with one that needs a browser nobody had installed. Every
shipped feature that rasterizes a chart broke at once — report
generation, chart PNGs, thumbnails, and ``generate_map_chart_gif`` —
each with the same unhandled traceback:

    ChromeNotFoundError: Kaleido v1 and later requires Chrome to be
    installed.

Nothing in geeViz caught it or said what to do, so the error read like a
bug in geeViz rather than a missing binary. An agent hitting it in a
deployed container concluded the feature was unavailable and rebuilt a
worse version of it by hand.

So: catch it, and where it is reasonable to do so, fix it. ``plotly.io.
get_chrome()`` downloads a Chrome-for-Testing build — the same thing the
``plotly_get_chrome`` CLI does.

**Only when it is reasonable.** That download is ~150 MB. On a laptop it
is a one-time pause and exactly what the caller wants. Inside a request
on a cold serverless instance it is a 150 MB fetch competing with the
request clock, which is a good way to turn a slow chart into a gateway
error. So the fetch is automatic when the process looks interactive and
refused, with instructions, when it looks like a server — where the
right answer is to install Chrome when the image is built.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: Set to "0"/"false" to never auto-download, or "1"/"true" to always.
#: Unset means "decide from the environment" — see :func:`_may_autoget`.
_ENV_FLAG = "GEEVIZ_AUTO_GET_CHROME"

#: Env vars a managed runtime sets. Presence means "do not download
#: 150 MB inside a request".
_SERVERLESS_VARS = ("K_SERVICE", "CLOUD_RUN_JOB", "GAE_ENV",
                    "FUNCTION_TARGET", "AWS_LAMBDA_FUNCTION_NAME")

def _platform_install_hint() -> str:
    """The command that actually works on THIS machine.

    A generic "install Chrome" sends the reader to a download page when
    a one-line package install would do.
    """
    import sys
    if sys.platform.startswith("linux"):
        return ("    apt-get install -y chromium      # Debian/Ubuntu\n"
                "    dnf install -y chromium          # Fedora/RHEL")
    if sys.platform == "darwin":
        return "    brew install --cask google-chrome"
    if sys.platform == "win32":
        return ("    winget install Google.Chrome\n"
                "    (Microsoft Edge, already present on most Windows "
                "systems, also works)")
    return "    install Google Chrome, Chromium, or Microsoft Edge"


def _install_hint() -> str:
    """Explain what is missing, why, and the two ways to fix it."""
    return (
        "WHY: a Plotly figure is JavaScript, so turning one into an "
        "image means running a browser. kaleido 0.x bundled its own "
        "Chromium; kaleido 1.0 removed it and now looks for a browser "
        "already on the machine. None was found.\n"
        "\n"
        "FIX - install a browser, which BOTH geeViz and kaleido "
        "discover automatically (Chrome, Chromium, Edge or Brave):\n"
        + _platform_install_hint() + "\n"
        "\n"
        "or let Plotly fetch a private copy (~150 MB):\n"
        "    plotly_get_chrome\n"
        "    # or:  import plotly.io as pio; pio.get_chrome()\n"
        "\n"
        "A system browser is usually the better choice: it also enables "
        "geeViz's Sankey PNG export (outputLib.charts.html_to_png), "
        "which drives a browser directly and cannot use kaleido's "
        "private copy.\n"
        "\n"
        "In a container, do this in the image BUILD, not at run time."
    )

#: Set once we have tried, so a process does not attempt the download
#: repeatedly when it is going to keep failing.
_attempted = False


def _is_serverless() -> bool:
    return any(os.environ.get(v) for v in _SERVERLESS_VARS)


def _may_autoget() -> bool:
    """Whether this process should download Chrome on demand."""
    flag = (os.environ.get(_ENV_FLAG) or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    # Unset: fetch when interactive, refuse on a managed runtime.
    return not _is_serverless()


def _is_missing_chrome(exc: BaseException) -> bool:
    """Is this the "no browser" failure, rather than a real render error?

    Matched on the class NAME rather than by importing choreographer,
    which is kaleido's transitive dependency and not ours to require.
    The message is checked too, since the exception may arrive wrapped.
    """
    seen = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__name__ == "ChromeNotFoundError":
            return True
        text = str(cur).lower()
        if "requires chrome" in text or "chrome to be installed" in text:
            return True
        if "chromenotfound" in text:
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def ensure_chrome() -> bool:
    """Download Chrome for kaleido. True if it is available afterwards.

    Idempotent within a process: a failed attempt is not retried, because
    the usual cause (no network, read-only filesystem) will not have
    changed by the next chart.
    """
    global _attempted
    if _attempted:
        return False
    _attempted = True
    try:
        import plotly.io as pio
    except Exception:                                    # noqa: BLE001
        return False
    if not hasattr(pio, "get_chrome"):
        # kaleido < 1: it bundles its own Chromium, so a missing browser
        # is not something get_chrome could fix anyway.
        return False
    logger.info(
        "geeViz: Chrome is required to rasterize a Plotly chart and was "
        "not found — downloading it once (~150 MB). Set %s=0 to disable "
        "this.", _ENV_FLAG,
    )
    try:
        path = pio.get_chrome()
        logger.info("geeViz: Chrome installed at %s", path)
        return True
    except Exception as e:                               # noqa: BLE001
        logger.warning("geeViz: could not download Chrome: %s", e)
        return False


def fig_to_png(fig, *, width=None, height=None, scale=None, **kwargs) -> bytes:
    """``fig.to_image(format="png", ...)``, with Chrome handled.

    Args:
        fig: a Plotly figure, or a dict Plotly accepts.
        width, height, scale: passed straight through.

    Returns:
        bytes: PNG data.

    Raises:
        RuntimeError: when Chrome is unavailable and cannot be installed,
            carrying the command that fixes it. Any other failure from
            Plotly propagates unchanged — a broken figure is not a
            missing browser, and conflating the two would send the reader
            to install software they already have.
    """
    import plotly.io as pio

    opts = {"format": "png"}
    for k, v in (("width", width), ("height", height), ("scale", scale)):
        if v is not None:
            opts[k] = v
    opts.update(kwargs)

    try:
        return pio.to_image(fig, **opts)
    except Exception as exc:                             # noqa: BLE001
        if not _is_missing_chrome(exc):
            raise
        if _may_autoget() and ensure_chrome():
            return pio.to_image(fig, **opts)
        where = ("This looks like a managed/serverless runtime, where a "
                 "150 MB download inside a request is not safe — install "
                 "Chrome when the image is built instead.\n"
                 if _is_serverless() else "")
        raise RuntimeError(
            "Cannot render this Plotly chart to PNG: no Chrome found.\n"
            + where + _install_hint()
        ) from exc
