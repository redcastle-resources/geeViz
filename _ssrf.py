"""Refuse outbound requests to addresses only the host should reach.

Every HTTP helper in geeViz — esriLib, googleMapsLib, edwLib,
fsInsights — takes a URL, and several are PUBLIC functions the agent can
call from ``run_code``:

    from geeViz import esriLib
    esriLib.getServiceMetadata('http://whatever')

Those run in a geeViz frame, which ``_called_from_trusted_lib`` trusts,
so the MCP sandbox's import blocklist never sees them. Verified: with
``urllib3`` fully blocked, that one call still fetched example.com and
returned the response body inside the exception message. The sandbox had
no outbound HTTP and a trusted wrapper handed it back.

On a cloud runtime the payoff is specific. The instance metadata service
at ``169.254.169.254`` issues the runtime service account's OAuth token
to anything that can make a local HTTP request. Link-local, loopback and
RFC1918 addresses are all reachable from inside a container and none of
them are anywhere a geospatial API lives.

This is a guard, not a boundary. It closes the obvious targets; a
determined caller can still reach a public host that redirects inward,
which is why redirects are re-checked, and can still reach any public
address at all, which is what network egress control is for. It buys
time and removes the cheap credential grab.
"""

import ipaddress
import socket
from urllib.parse import urlparse

#: Schemes that make sense for a data API. ``file://`` would turn every
#: fetch helper into an arbitrary file read.
ALLOWED_SCHEMES = ("http", "https")


class BlockedAddressError(ValueError):
    """Raised when a URL resolves somewhere outbound requests may not go."""


def _is_forbidden(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True          # unparseable — refuse rather than guess
    return (
        addr.is_private          # RFC1918 / RFC4193 — inside the VPC
        or addr.is_loopback      # 127/8, ::1 — other services on the host
        or addr.is_link_local    # 169.254/16 — CLOUD METADATA lives here
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def check_url(url: str) -> str:
    """Raise :class:`BlockedAddressError` if ``url`` points somewhere
    outbound requests must not go. Returns the URL unchanged otherwise.

    Resolves the hostname first, because the address is what matters:
    a name that looks public can resolve to 169.254.169.254, and several
    public resolvers will happily do that.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedAddressError(
            f"URL scheme {parsed.scheme!r} is not allowed; use http or https."
        )
    host = parsed.hostname
    if not host:
        raise BlockedAddressError(f"No host in URL: {url!r}")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Let the real request produce the real DNS error — failing here
        # would report a security block for an ordinary typo.
        return url

    for info in infos:
        ip = info[4][0]
        if _is_forbidden(ip):
            raise BlockedAddressError(
                f"Refusing to fetch {url!r}: {host} resolves to {ip}, which "
                f"is a loopback, private, or link-local address. On a cloud "
                f"runtime 169.254.169.254 serves the instance's service "
                f"account token, so outbound requests from library helpers "
                f"are not allowed to reach it."
            )
    return url
