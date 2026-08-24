"""Shared HTTP plumbing for the Forest Service API clients.

Both upstreams are public, unauthenticated, and occasionally slow. They
also fail in different ways, and one of them fails in a way that is easy
to miss:

* **FIADB-API** signals failure with an HTTP status, the ordinary case.
* **LCMS** returns **HTTP 200 with a ``ParameterError`` inside the body**
  when the requested summary area does not exist. A client that checks
  ``response.ok`` treats that as success and hands back an empty result,
  which is the most likely source of silent wrong answers in this whole
  subpackage. :func:`get_json` therefore inspects the payload, not just
  the status line.

Everything here is deliberately small. The goal is one place that knows
about timeouts, retries, and the two upstreams' error dialects, so the
client modules can be about their data.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Both APIs are government-hosted and can take several seconds on a cold
#: cache. A 60s ceiling is generous enough that a slow-but-working call
#: succeeds, and short enough that a hung one surfaces during a notebook
#: session rather than at the end of it.
DEFAULT_TIMEOUT = 60

#: Retries apply to transport errors and 5xx only — never to a 4xx, which
#: means the request was wrong and will stay wrong.
DEFAULT_RETRIES = 2

_USER_AGENT = "geeViz.fsInsights (+https://geeviz.org)"


class FSInsightsError(RuntimeError):
    """Base for every error raised by this subpackage."""


class UpstreamError(FSInsightsError):
    """The API was reached but refused or failed the request.

    Carries ``url`` and, when the upstream provided one, the parameters
    it echoed back — LCMS returns those, and they are usually enough to
    see the mistake without re-reading the call site.
    """

    def __init__(self, message: str, *, url: str = "",
                 provided: Optional[dict] = None):
        super().__init__(message)
        self.url = url
        self.provided = provided or {}


class UpstreamUnavailable(FSInsightsError):
    """The API could not be reached at all.

    Distinct from :class:`UpstreamError` because callers respond to it
    differently: a bad parameter needs a code change, an unreachable
    host needs a retry later or a fall back to cached data.
    """


def get_json(url: str, params: Optional[dict] = None, *,
             timeout: int = DEFAULT_TIMEOUT,
             retries: int = DEFAULT_RETRIES) -> Any:
    """GET ``url`` and return decoded JSON, raising on either failure mode.

    Args:
        url: Absolute URL. Trailing slashes matter to LCMS — see
            :mod:`geeViz.fsInsights.lcms` for why the paths there are
            written the way they are.
        params: Query parameters. Values are passed through to
            ``requests`` for encoding.
        timeout: Seconds before giving up on a single attempt.
        retries: Extra attempts after the first, for transport errors
            and 5xx responses only.

    Returns:
        The decoded JSON body — usually a ``dict`` or ``list``.

    Raises:
        UpstreamError: The request was rejected, returned a non-2xx, was
            not JSON, or carried an in-body error (LCMS's
            ``ParameterError``).
        UpstreamUnavailable: The host could not be reached within
            ``timeout`` across all attempts.
    """
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - requests is a core dep
        raise FSInsightsError(
            "geeViz.fsInsights needs 'requests' (a core geeViz dependency)"
        ) from exc

    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    last_exc: Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout,
                                headers=headers)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                # Linear, not exponential: these are public services with
                # no published rate limit, and the failures we see are
                # transient DNS/TLS rather than throttling.
                time.sleep(1 + attempt)
                continue
            raise UpstreamUnavailable(
                f"could not reach {url} after {retries + 1} attempt(s): "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if resp.status_code >= 500 and attempt < retries:
            time.sleep(1 + attempt)
            continue

        if not resp.ok:
            raise UpstreamError(
                f"HTTP {resp.status_code} from {url}"
                + (f" — {resp.text[:200]}" if resp.text else ""),
                url=resp.url,
            )

        try:
            payload = resp.json()
        except Exception as exc:
            # HTML where JSON was asked for. Two very different causes,
            # and telling them apart matters because the advice differs.
            server_err = _evalidator_error(resp.text)
            if server_err:
                # FIADB-API delivers its 500s as an HTML error page under
                # HTTP 200 — "Internal Server Error: list index out of
                # range" and the like. Observed affecting every endpoint
                # at once, including ones that worked minutes earlier, so
                # it behaves like a 5xx and is retried like one.
                if attempt < retries:
                    time.sleep(1 + attempt)
                    continue
                raise UpstreamError(
                    f"FIADB-API returned a server error (as HTTP 200 with "
                    f"an HTML error page): {server_err}. This is upstream, "
                    f"not a bad request - it has been seen to affect every "
                    f"endpoint at once and clear on its own. Cached "
                    f"vocabularies still work offline; see "
                    f"geeViz.fsInsights.vocab.",
                    url=resp.url,
                ) from exc
            raise UpstreamError(
                f"expected JSON from {url} but got "
                f"{resp.headers.get('Content-Type', 'unknown')!r}. "
                f"FIADB-API parameter endpoints need outputFormat=JSON; "
                f"without it they serve a browser table.",
                url=resp.url,
            ) from exc

        _raise_for_inband_error(payload, resp.url)
        return payload

    # Unreachable in practice; keeps type checkers happy.
    raise UpstreamUnavailable(f"could not reach {url}: {last_exc}")


def _evalidator_error(html: str) -> str:
    """Extract FIADB-API's error text from its HTML error page, or ''.

    The API answers failures with a rendered page under HTTP 200::

        EVALIDator | Error Page
        Error Type: Internal Server Error
        Received an Error: list index out of range

    Pulling those two lines out turns "expected JSON, got text/html" —
    which reads like a client mistake and sends people looking for a
    missing ``outputFormat`` — into the upstream error it actually is.
    """
    import re

    if not html or "EVALIDator" not in html[:4000]:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    # Bounded by the label that follows, not by a character class — the
    # error type is itself capitalized ("Internal Server Error"), so a
    # [^A-Z] run matches nothing at all.
    kind = re.search(r"Error Type:\s*(.+?)\s*(?:Received an Error|API Version|$)",
                     text)
    detail = re.search(r"Received an Error:\s*(.+?)\s*(?:If you used|API Version|$)",
                       text)
    parts = [m.group(1).strip() for m in (kind, detail) if m]
    if parts:
        return " - ".join(parts)
    return "unspecified EVALIDator error" if "Error Page" in text else ""


def _raise_for_inband_error(payload: Any, url: str) -> None:
    """Raise if ``payload`` carries an error despite a 2xx status.

    LCMS answers an unknown summary area with 200 and::

        {"Result": {"ParameterError": "Invalid Summary Area for ...",
                    "ProvidedParameters": {...}}}

    The echoed parameters are genuinely useful, so they are attached to
    the exception rather than discarded.
    """
    if not isinstance(payload, dict):
        return
    result = payload.get("Result")
    if not isinstance(result, dict):
        return
    err = result.get("ParameterError")
    if not err:
        return
    provided = result.get("ProvidedParameters")
    provided = provided if isinstance(provided, dict) else {}
    detail = (f" (sent: {', '.join(f'{k}={v!r}' for k, v in provided.items())})"
              if provided else "")
    raise UpstreamError(f"{err}{detail}", url=url, provided=provided)
