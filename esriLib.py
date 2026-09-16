"""
ArcGIS / Esri REST services client for geeViz. **DEPRECATED.**

.. deprecated::
   Use :mod:`georest` instead. This module now delegates to it and will
   be removed in a future release.

   ``georest`` is the maintained implementation of everything here that
   talks to an Esri REST endpoint, it is stdlib-only (no runtime
   dependencies), and it does considerably more than this module ever
   did — ``exportImage``, ``identifyPixelValue``, ``getSamples``,
   ``computeStatisticsHistograms``, ``queryBoundary``, and a full client
   for the USFS Enterprise Data Warehouse.

   The move, function by function::

       geeViz.esriLib.searchPortal        -> georest.restesri.portal.searchPortal
       geeViz.esriLib.getServiceMetadata  -> georest.restesri.portal.getServiceMetadata

   The signatures match, so the change is the import line.

   The ``addEsri*Service`` functions are NOT going to georest: they add
   layers to a geeViz ``Map``, which is geeViz's concern, not a REST
   client's. They stay available here (and as ``Map.addEsri*``) and now
   do their REST work through georest.

Bridges three Esri service types into the existing geeViz viewer with no
JavaScript changes required.  The viewer already supports both
``tileMapService`` (for raster tiles) and ``geoJSONVector`` (for vector
features) layer types.

======================================  ==================================================================================
Service type                            Mechanism
======================================  ==================================================================================
Image Service                           ``Map.addTileLayer("<url>/tile/{z}/{y}/{x}")``
Map Service (cached)                    ``Map.addTileLayer(...)`` — same tile path
Feature Service (≤ ``max_features``)    Fetch ``<url>/query?f=geojson`` → ``Map.addLayer(geojson_dict)``
Feature Service (> ``max_features``)    ``ValueError`` with remediation message
======================================  ==================================================================================

**Public API** — 7 functions + 1 constant::

    import geeViz.esriLib as el

    # Discover data on any ArcGIS Portal
    results = el.searchPortal("naip 2023")                  # IIPP (default)
    results = el.searchPortal("naip 2023", portal="agol")   # ArcGIS Online
    results = el.searchPortal("naip 2023",
                              portal="https://myagency.gov/portal")

    # Available portals
    el.PORTALS.keys()   # iipp, agol, usgs, noaa, usfs, nasa

    # Inspect any service
    meta = el.getServiceMetadata("https://.../ImageServer")

    # Add to the geeViz map (auto-dispatches by service type)
    el.addEsriService(result_or_url)

    # Or call the typed helpers directly
    el.addEsriImageService("https://.../ImageServer", name="NAIP 2023")
    el.addEsriFeatureService("https://.../FeatureServer/0",
                             max_features=2000, where="STATE='UT'")
    el.addEsriMapService("https://.../MapServer")

Token-gated portals::

    # Obtain a token first:
    #   POST <portal>/sharing/rest/generateToken
    #     username=...&password=...&client=requestip&expiration=60&f=json
    token = "..."
    el.searchPortal("classified data", token=token)
    el.addEsriFeatureService(url, token=token)

Copyright 2026 Ian Housman

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
"""

from __future__ import annotations

import json
import warnings
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from geeViz._ssrf import check_url as _check_url  # noqa: E402

# ---------------------------------------------------------------------------
# Known public portals
# ---------------------------------------------------------------------------

PORTALS: dict[str, str] = {
    "iipp": "https://imagery.geoplatform.gov/iipp",
    "agol": "https://www.arcgis.com",
    "usgs": "https://www.sciencebase.gov/sciencebase",
    "noaa": "https://coastalatlas.noaa.gov",
    "usfs": "https://data.fs.usda.gov/geodata",
    "nasa": "https://nasa.maps.arcgis.com",
}
"""Module-level dict mapping short names to portal base URLs.

Add your own at runtime::

    from geeViz.esriLib import PORTALS
    PORTALS["myagency"] = "https://gis.myagency.gov/portal"
"""

# Non-data item types that clutter portal search results.  Applied when
# data_only=True (the default).  This mirrors the exclusion list used by
# the IIPP search UI.
_DATA_ONLY_EXCLUSIONS: list[str] = [
    "Style",
    "Layer",
    "Map Document",
    "Map Package",
    "Basemap",
    "Mobile Basemap Package",
    "Web Scene",
    "CityEngine Web Scene",
    "Pro Map",
    "Project Package",
    "Task File",
    "Operations Dashboard Add In",
    "Application",
    "Web Mapping Application",
    "Mobile Application",
    "Code Sample",
    "Symbol Set",
    "Color Set",
    "Windows Viewer Add In",
    "Windows Viewer Configuration",
    "Map Area",
    "Insights Workbook",
    "Insights Page",
    "Insights Model",
    "Hub Initiative",
    "Hub Site Application",
    "Hub Page",
    "Hub Project",
    "Experience Builder Widget",
    "Dashboard",
    "StoryMap",
    "Survey123 Add In",
    "Compact Tile Package",
]

# ---------------------------------------------------------------------------
# HTTP helpers (no third-party dependencies — stdlib only)
# ---------------------------------------------------------------------------

_TIMEOUT = 30  # seconds


#: Functions already warned about, so a loop calling one does not emit
#: the same notice a thousand times. A deprecation is a message to the
#: person reading the code, not a running cost.
_WARNED: set[str] = set()


def _deprecated(name: str, replacement: str) -> None:
    """Warn once that ``name`` has moved to ``replacement``.

    ``DeprecationWarning`` is hidden by default in scripts, which is
    right: this must not spam a notebook that happens to call a geeViz
    map helper. Anyone running with ``-W default`` or pytest sees it.
    """
    if name in _WARNED:
        return
    _WARNED.add(name)
    warnings.warn(
        f"geeViz.esriLib.{name} is deprecated and now delegates to "
        f"{replacement}. geeViz.esriLib will be removed in a future "
        f"release; import georest directly.",
        DeprecationWarning,
        stacklevel=3,
    )


def _fetch_json(url: str, params: dict | None = None) -> dict:
    """GET a URL and return parsed JSON, via :mod:`georest`.

    The body that used to live here — urlopen, the three-attempt retry
    on transient statuses, the JSON decode with the response body in the
    error — is now georest's, and georest is the maintained copy. This
    is the same code path the retry patch of 2026-09-01 added, kept
    working for the ``addEsri*`` callers below while they still exist.

    Raises the same things it always did: ``urllib.error.URLError`` on
    network failure, ``ValueError`` on a non-JSON response.
    """
    from georest.restesri import _http as _gh

    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    # _check_url stays on this side: it is geeViz's SSRF guard, and the
    # url is fully built by the time it runs.
    _check_url(url)
    try:
        return _gh.fetch_json(url)
    except ValueError:
        # A non-JSON body. Same meaning on both sides — pass it through
        # rather than flattening it into the network case.
        raise
    except RuntimeError as exc:
        # georest reports an unreachable host or a bad HTTP status as
        # RuntimeError; this module has always documented and raised
        # ConnectionError, and callers catch that. Delegation must not
        # silently change which exception a caller has to handle, so
        # translate at the boundary rather than rewriting the contract
        # of a module people already depend on.
        raise ConnectionError(str(exc)) from exc
    except urllib.error.URLError as exc:
        raise ConnectionError(str(exc)) from exc


def _build_params(base: dict, token: str | None) -> dict:
    """Merge ``token`` into a params dict if supplied. Delegates."""
    from georest.restesri import _http as _gh
    return _gh.build_params(base, token)


def _resolve_portal(portal: str) -> str:
    """Resolve a portal argument to a base URL.

    Args:
        portal (str): Either a short name from :data:`PORTALS` (e.g.
            ``"iipp"``, ``"agol"``) or a full URL
            (e.g. ``"https://gis.myagency.gov/portal"``).

    Returns:
        str: Portal base URL with no trailing slash.

    Raises:
        KeyError: If a short name is given but not found in :data:`PORTALS`.
    """
    if portal.startswith("http://") or portal.startswith("https://"):
        return portal.rstrip("/")
    if portal in PORTALS:
        return PORTALS[portal].rstrip("/")
    known = ", ".join(f'"{k}"' for k in PORTALS)
    raise KeyError(
        f"Unknown portal short name {portal!r}.  Known names: {known}.  "
        f"Pass a full URL or add your portal to PORTALS first: "
        f'PORTALS["{portal}"] = "https://..."'
    )


# ---------------------------------------------------------------------------
# Portal search
# ---------------------------------------------------------------------------

def searchPortal(
    query: str,
    portal: str = "iipp",
    limit: int = 20,
    data_only: bool = True,
    raw_q: str | None = None,
    token: str | None = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    """Search any ArcGIS Portal for hosted services.

    Uses the standard ``/sharing/rest/search`` endpoint present on ArcGIS
    Online, IIPP, and any ArcGIS Enterprise install.

    Args:
        query (str): Free-text search query (e.g. ``"naip 2023"``,
            ``"fire perimeter"``).
        portal (str, optional): Either a short name from :data:`PORTALS`
            (``"iipp"``, ``"agol"``, ``"usgs"``, ``"noaa"``, ``"usfs"``,
            ``"nasa"``) or a full portal base URL.  Defaults to ``"iipp"``.
        limit (int, optional): Maximum results to return (1–100).
            Defaults to 20.
        data_only (bool, optional): When ``True`` (default), appends a
            bundled exclusion list that filters out non-data items (styles,
            web apps, dashboards, etc.) so results are datasets only.
            Set to ``False`` to search without restrictions.
        raw_q (str, optional): If supplied, overrides the assembled query
            string entirely — ignores ``query``, ``data_only``, and
            ``filters``.  Use for portal query DSL power users.
        token (str, optional): ArcGIS token for secured portals.  Omit for
            public services.  Obtain via
            ``POST <portal>/sharing/rest/generateToken``.
        **filters: Extra ArcGIS search filters forwarded verbatim as query
            params (e.g. ``sortField="title"``, ``sortOrder="asc"``,
            ``bbox="-120,35,-110,42"``).

    Returns:
        list of dict: Parsed portal items.  Each dict includes:

        - ``id`` (str): Item ID.
        - ``title`` (str): Item title.
        - ``type`` (str): Esri item type (e.g. ``"Image Service"``,
          ``"Feature Service"``).
        - ``snippet`` (str): Short description.
        - ``tags`` (list of str): Associated tags.
        - ``url`` (str): Service endpoint URL (may be ``""`` if not set).
        - ``owner`` (str): Portal username of the owner.
        - ``created`` (int): Unix timestamp (ms) of item creation.
        - ``modified`` (int): Unix timestamp (ms) of last modification.
        - ``thumbnail`` (str or None): Thumbnail URL, or ``None`` if absent.
        - ``_raw`` (dict): Full raw portal item dict for advanced access.

    Example::

        import geeViz.esriLib as el

        # Search IIPP for NAIP imagery (default portal)
        results = el.searchPortal("naip 2023", limit=10)
        for r in results:
            print(r["title"], r["type"], r["url"])

        # ArcGIS Online
        results = el.searchPortal("wildfire perimeter", portal="agol")

        # Custom Enterprise portal
        results = el.searchPortal("hydrology",
                                  portal="https://gis.mystate.gov/portal")

        # Raw portal query DSL (bypasses data_only and filters)
        results = el.searchPortal("", raw_q='type:"Feature Service" owner:USGS')
    """
    _deprecated("searchPortal", "georest.restesri.portal.searchPortal")
    from georest.restesri import portal as _gp
    return _gp.searchPortal(
        query, portal=portal, limit=limit, data_only=data_only,
        raw_q=raw_q, token=token, **filters)


def getServiceMetadata(url: str, token: str | None = None) -> dict[str, Any]:
    """Fetch and return the JSON metadata for any ArcGIS REST service.

    Appends ``?f=json`` to the URL and returns the parsed response.  Works
    for ImageServer, FeatureServer, MapServer, and any sub-layer URL
    (e.g. ``/FeatureServer/0``).

    Args:
        url (str): ArcGIS service endpoint, e.g.::

            "https://naip.services.arcgis.com/.../ImageServer"
            "https://services.arcgis.com/.../FeatureServer/0"
            "https://server.arcgisonline.com/.../MapServer"

        token (str, optional): ArcGIS token for secured services.

    Returns:
        dict: Parsed service metadata.  Common keys vary by service type:

        - ``name`` (str): Service name.
        - ``type`` (str): Layer geometry type (Feature Services).
        - ``fields`` (list): Schema fields (Feature Services).
        - ``extent`` (dict): Spatial extent.
        - ``spatialReference`` (dict): Spatial reference info.
        - ``minScale``, ``maxScale`` (int): Scale range.
        - ``capabilities`` (str): Comma-separated capabilities string.

    Raises:
        ConnectionError: If the URL is unreachable.
        ValueError: If the response is not valid JSON.

    Example::

        import geeViz.esriLib as el

        meta = el.getServiceMetadata("https://.../ImageServer")
        print(meta["name"])
        print(meta["extent"])

        # FeatureServer layer 0
        meta = el.getServiceMetadata("https://.../FeatureServer/0")
        print([f["name"] for f in meta.get("fields", [])])
    """
    _deprecated("getServiceMetadata",
                "georest.restesri.portal.getServiceMetadata")
    from georest.restesri import portal as _gp
    _check_url(url)
    try:
        return _gp.getServiceMetadata(url, token=token)
    except (RuntimeError, urllib.error.URLError) as exc:
        # Same translation as _fetch_json, and for the same reason: this
        # function has always raised ConnectionError for an unreachable
        # service, and delegating must not change what a caller catches.
        raise ConnectionError(str(exc)) from exc


def _detect_service_type(url: str, meta: dict | None = None) -> str:
    """Return the service type string for *url*.

    Detection order:
    1. URL path segments (fast, no HTTP call needed for clear cases).
    2. ``meta["type"]`` or ``meta["serviceDataType"]`` if caller already
       fetched metadata.
    3. Fetch ``?f=json`` and inspect the response.

    Returns one of: ``"ImageServer"``, ``"FeatureServer"``, ``"MapServer"``,
    or ``"Unknown"``.
    """
    # Normalise
    clean = url.rstrip("/").lower()

    # Canonical spellings: match URL segment (case-insensitive), return
    # the correctly-cased ArcGIS type name.
    _stype_map = {
        "imageserver": "ImageServer",
        "featureserver": "FeatureServer",
        "mapserver": "MapServer",
    }
    for lower, canonical in _stype_map.items():
        if f"/{lower}" in clean or clean.endswith(lower):
            return canonical

    # Fall back to metadata inspection
    if meta is None:
        try:
            meta = getServiceMetadata(url)
        except Exception:
            return "Unknown"

    # ArcGIS REST items carry a "type" key on the item record,
    # but service endpoint JSON uses serviceDataType or serviceType.
    for key in ("serviceDataType", "serviceType", "type"):
        val = meta.get(key, "")
        if isinstance(val, str):
            v = val.lower()
            if "image" in v:
                return "ImageServer"
            if "feature" in v:
                return "FeatureServer"
            if "map" in v:
                return "MapServer"

    # Check for fields[] → likely a FeatureServer layer
    if "fields" in meta:
        return "FeatureServer"
    # Check for bandCount → ImageServer
    if "bandCount" in meta or "pixelType" in meta:
        return "ImageServer"

    return "Unknown"


def _resolve_url(url_or_result: str | dict) -> str:
    """Extract a service URL from either a raw URL string or a
    :func:`searchPortal` result dict."""
    if isinstance(url_or_result, str):
        return url_or_result.rstrip("/")
    if isinstance(url_or_result, dict):
        # searchPortal result has a "url" key; fall back to id-based lookup
        service_url = url_or_result.get("url", "")
        if service_url:
            return service_url.rstrip("/")
        raise ValueError(
            "Portal result dict has no 'url' key.  Either the item is not a "
            "hosted service, or the portal did not return a URL for it.  "
            "Check url_or_result['_raw'] for the full item record."
        )
    raise TypeError(
        f"url_or_result must be a URL string or a searchPortal() result dict, "
        f"got {type(url_or_result).__name__!r}"
    )


# ---------------------------------------------------------------------------
# addEsriImageService
# ---------------------------------------------------------------------------

def addEsriImageService(
    url_or_result: str | dict,
    viz_params: dict | None = None,
    name: str | None = None,
    token: str | None = None,
    target_map=None
) -> None:
    """Add an ArcGIS Image Service as an XYZ tile layer to the geeViz map.

    Constructs the ArcGIS tile URL pattern
    ``<service_url>/tile/{z}/{y}/{x}`` and calls
    ``geeViz.geeView.Map.addTileLayer``.

    .. note::
        ArcGIS tile URLs use ``{z}/{y}/{x}`` order (y before x), not the
        XYZ standard ``{z}/{x}/{y}``.  This function emits the correct
        ArcGIS order automatically.

    Args:
        url_or_result (str or dict): Either:

            - A bare service URL, e.g.
              ``"https://naip.services.arcgis.com/.../ImageServer"``
            - A :func:`searchPortal` result dict (the ``"url"`` key is used).

        viz_params (dict, optional): Forwarded to ``addTileLayer`` as
            keyword arguments.  Supported keys: ``opacity`` (float),
            ``visible`` (bool), ``max_zoom`` (int).
        name (str, optional): Layer name shown in the geeViz layer list.
            Defaults to the last segment of the service URL.
        token (str, optional): ArcGIS token appended to tile requests as
            ``?token=<>``.

    Example::

        import geeViz.esriLib as el
        import geeViz.geeView as gv

        el.addEsriImageService(
            "https://naip.services.arcgis.com/.../ImageServer",
            name="NAIP 2022",
            viz_params={"opacity": 0.85},
        )
        gv.Map.centerObject(gv.ee.Geometry.Point([-111.89, 40.77]), 12)
        gv.Map.view()
    """
    import geeViz.geeView as gv

    url = _resolve_url(url_or_result)
    if name is None:
        name = url.rstrip("/").split("/")[-2] if url.endswith(("ImageServer", "imageserver")) else url.rstrip("/").split("/")[-1]

    # ArcGIS Image/Map Server tile endpoint: /tile/{z}/{y}/{x}
    # Note: ArcGIS uses y then x (not the XYZ standard x then y).
    tile_url = f"{url}/tile/{{z}}/{{y}}/{{x}}"
    if token:
        tile_url = f"{tile_url}?token={urllib.parse.quote(token, safe='')}"

    kw: dict[str, Any] = {}
    if viz_params:
        if "opacity" in viz_params:
            kw["opacity"] = float(viz_params["opacity"])
        if "visible" in viz_params:
            kw["visible"] = bool(viz_params["visible"])
        if "max_zoom" in viz_params:
            kw["max_zoom"] = int(viz_params["max_zoom"])

    print(f"Adding Esri Image Service: {name}")
    (target_map or gv.Map).addTileLayer(tile_url, name=name, **kw)


# ---------------------------------------------------------------------------
# addEsriMapService
# ---------------------------------------------------------------------------

def addEsriMapService(
    url_or_result: str | dict,
    name: str | None = None,
    token: str | None = None,
    viz_params: dict | None = None,
    target_map=None,
) -> None:
    """Add a cached ArcGIS Map Service as an XYZ tile layer to the geeViz map.

    Cached Map Services expose the same ``/tile/{z}/{y}/{x}`` tile endpoint
    as Image Services and are handled identically.  Dynamic (non-cached) Map
    Services do not serve tiles this way; for those, use
    :func:`addEsriFeatureService` on the individual sub-layer.

    Args:
        url_or_result (str or dict): Service URL or :func:`searchPortal`
            result dict.
        name (str, optional): Layer name.  Defaults to last URL segment.
        token (str, optional): ArcGIS token for secured services.
        viz_params (dict, optional): ``opacity``, ``visible``, ``max_zoom``.

    Example::

        import geeViz.esriLib as el

        el.addEsriMapService(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer",
            name="ESRI World Imagery",
        )
    """
    # ── Preflight: cached or dynamic? Route accordingly. ──
    # CACHED MapServers (``singleFusedMapCache: true``) expose
    # ``/tile/{z}/{y}/{x}`` — same shape as an ImageServer, handled by
    # addEsriImageService below.
    # DYNAMIC MapServers (``singleFusedMapCache: false``) don't serve
    # pre-rendered tiles; they respond to ``/export?bbox=…&f=image``.
    # Route those through ``gv.Map.addDynamicMapService``, which
    # bridges to the viewer's ``addDynamicToMap`` code path (Google
    # Maps GroundOverlay per viewport). Real incident 2026-07-30: FEMA
    # NFHL is dynamic; passing it to addEsriMapService without this
    # branch broke the map silently.
    import geeViz.geeView as _gv
    url = _resolve_url(url_or_result)
    try:
        _meta = getServiceMetadata(url, token=token)
    except Exception as _meta_err:
        # Metadata fetch failed — could be a bad URL, an auth wall, or
        # a transient network hiccup. Print a warning so the agent (and
        # `testLayers` output) sees WHY we can't detect cached-vs-dynamic
        # and can suggest a fix; still fall through to the tile path in
        # case the caller knows the service IS cached.
        print(
            f"WARNING: addEsriMapService could not fetch service metadata for "
            f"{url!r} ({_meta_err}). Proceeding as if cached; if the layer "
            f"fails to render, verify the URL (a common issue is a wrong "
            f"prefix like '/gis/...' vs '/arcgis/rest/services/...')."
        )
        _meta = None
    if _meta is not None and _meta.get("singleFusedMapCache") is False:
        _name = name or url.rstrip("/").split("/")[-2]
        print(f"Adding Dynamic Esri Map Service: {_name}  ({url})")
        (target_map or _gv.Map).addDynamicMapService(
            url,
            name=_name,
            visible=(viz_params or {}).get("visible", True),
            token=token,
        )
        return
    # Cached — same tile URL shape as ImageServer
    addEsriImageService(url_or_result, viz_params=viz_params, name=name, token=token, target_map=target_map)


# ---------------------------------------------------------------------------
# addEsriFeatureService
# ---------------------------------------------------------------------------

_FEATURE_QUERY_SUFFIX = "/query"


def addEsriFeatureService(
    url_or_result: str | dict,
    viz_params: dict | None = None,
    name: str | None = None,
    max_features: int = 1000,
    where: str = "1=1",
    bbox: str | None = None,
    token: str | None = None,
    target_map=None
) -> None:
    """Fetch and add an ArcGIS Feature Service layer as a GeoJSON vector layer.

    Hits ``<url>/query?f=geojson&where=<where>&outSR=4326`` and passes the
    returned GeoJSON directly to ``geeViz.geeView.Map.addLayer``.

    .. warning::
        Always performs a ``returnCountOnly=true`` pre-flight before fetching
        geometry.  If the result count exceeds *max_features*, a
        :class:`ValueError` is raised with a concrete remediation message.

    Args:
        url_or_result (str or dict): Feature Service or sub-layer URL
            (e.g. ``".../FeatureServer/0"``), or a :func:`searchPortal`
            result dict.  If the URL points to the FeatureServer root rather
            than a specific layer, ``/0`` is appended automatically.
        viz_params (dict, optional): Passed to ``Map.addLayer`` as the ``viz``
            dict.  Supports all geeViz vector viz keys (``"color"``,
            ``"strokeColor"``, ``"fillColor"``, ``"opacity"``,
            ``"strokeWidth"``, ``"layerType"``, etc.).
        name (str, optional): Layer name.  Defaults to last URL segment.
        max_features (int, optional): Hard cap on feature count.  If the
            service has more than this many features matching *where*, a
            :class:`ValueError` is raised.  Defaults to 1000.  Increase
            with care — very large GeoJSON payloads can slow the viewer.
        where (str, optional): SQL WHERE clause sent to the service for
            server-side filtering.  Defaults to ``"1=1"`` (all features).
            Example: ``where="STATE_FIPS='06'"`` (California only).
        token (str, optional): ArcGIS token for secured services.

    Raises:
        ValueError: If the feature count exceeds *max_features*.
        ConnectionError: If the service URL is unreachable.

    Example::

        import geeViz.esriLib as el
        import geeViz.geeView as gv

        # Simple fetch — all features up to default cap
        el.addEsriFeatureService(
            "https://services.arcgis.com/.../FeatureServer/0",
            name="Wildfire Perimeters",
        )

        # Filter server-side to stay under the cap
        el.addEsriFeatureService(
            "https://services.arcgis.com/.../FeatureServer/0",
            where="YEAR_=2023 AND GIS_ACRES > 10000",
            name="Large 2023 Fires",
            max_features=500,
        )

        gv.Map.view()
    """
    import geeViz.geeView as gv

    url = _resolve_url(url_or_result)

    # Ensure we're pointing at a layer (e.g. /0), not the FeatureServer root.
    # The root URL ends in "FeatureServer" (case-insensitive); sub-layers end
    # in a digit.
    if url.lower().endswith("featureserver"):
        url = f"{url}/0"

    if name is None:
        name = url.rstrip("/").split("/")[-1]
        # If name is just "0", walk up for a more descriptive label
        if name.isdigit():
            parts = url.rstrip("/").split("/")
            name = f"{parts[-2]} ({name})" if len(parts) >= 2 else name

    # ---- Pre-flight: count only ----
    count_params: dict[str, Any] = {
        "where": where,
        "returnCountOnly": "true",
        "f": "json",
    }
    # LOCAL PATCH (2026-08-28): area filter. Applied to the COUNT as well as
    # the fetch, so max_features guards the area asked about rather than the
    # whole layer - FEMA NFHL is 5.8M features nationally, 52 in a 2 km box.
    _bbox_params = {}
    if bbox:
        _bbox_params = {
            "geometry": bbox,
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        }
        count_params.update(_bbox_params)
    if token:
        count_params["token"] = token

    count_url = f"{url}{_FEATURE_QUERY_SUFFIX}"
    try:
        count_resp = _fetch_json(count_url, count_params)
    except urllib.error.URLError as exc:
        raise ConnectionError(
            f"Could not reach Feature Service at {count_url!r}: {exc}"
        ) from exc

    # Esri may return {"count": N} or {"error": {...}}
    if "error" in count_resp:
        err = count_resp["error"]
        raise ValueError(
            f"Feature Service returned an error: "
            f"{err.get('code')} — {err.get('message', str(err))}"
        )

    feature_count = count_resp.get("count", 0)

    if feature_count > max_features:
        raise ValueError(
            f"Feature service has {feature_count:,} features "
            f"(max_features={max_features:,}).\n"
            f"Increase max_features OR pass a `where` clause to filter, "
            f"e.g. where=\"STATE_FIPS='06'\", "
            f"OR set chunk_size= to paginate (future extension)."
        )

    # ---- Fetch GeoJSON ----
    query_params: dict[str, Any] = {
        "where": where,
        "outFields": "*",
        "outSR": "4326",           # always WGS84 so the viewer renders it natively
        "f": "geojson",
    }
    query_params.update(_bbox_params)
    if token:
        query_params["token"] = token

    try:
        geojson = _fetch_json(count_url, query_params)
    except urllib.error.URLError as exc:
        raise ConnectionError(
            f"Could not fetch features from {count_url!r}: {exc}"
        ) from exc

    if "error" in geojson:
        err = geojson["error"]
        raise ValueError(
            f"Feature Service query returned an error: "
            f"{err.get('code')} — {err.get('message', str(err))}"
        )

    actual = len(geojson.get("features", []))
    print(f"Adding Esri Feature Service: {name} ({actual:,} features)")

    viz = dict(viz_params or {})
    # The viewer needs layerType=geoJSONVector; addLayer sets it automatically
    # when passed a dict, but be explicit so callers can mix it with other keys.
    viz.setdefault("layerType", "geoJSONVector")

    (target_map or gv.Map).addLayer(geojson, viz, name)


# ---------------------------------------------------------------------------
# addEsriService — auto-dispatch
# ---------------------------------------------------------------------------

def addEsriService(
    url_or_result: str | dict,
    viz_params: dict | None = None,
    name: str | None = None,
    token: str | None = None,
    max_features: int = 1000,
    where: str = "1=1",
    target_map=None
) -> None:
    """Auto-detect the Esri service type and call the appropriate add helper.

    Inspects the URL path (and falls back to the service metadata) to
    determine whether *url_or_result* is an Image Service, Feature Service,
    or Map Service, then delegates to :func:`addEsriImageService`,
    :func:`addEsriFeatureService`, or :func:`addEsriMapService`.

    Args:
        url_or_result (str or dict): Service URL or :func:`searchPortal`
            result dict.
        viz_params (dict, optional): Visualization parameters forwarded to
            the typed helper.
        name (str, optional): Layer name.
        token (str, optional): ArcGIS token.
        max_features (int, optional): Forwarded to :func:`addEsriFeatureService`.
        where (str, optional): SQL WHERE clause forwarded to
            :func:`addEsriFeatureService`.

    Raises:
        ValueError: If the service type cannot be determined.

    Example::

        import geeViz.esriLib as el

        results = el.searchPortal("naip 2023", limit=5)
        for r in results:
            el.addEsriService(r)  # dispatches by type automatically
    """
    url = _resolve_url(url_or_result)
    stype = _detect_service_type(url)

    # Pass the original url_or_result so name resolution works with dicts too
    if stype == "ImageServer":
        addEsriImageService(url_or_result, viz_params=viz_params, name=name, token=token, target_map=target_map)
    elif stype == "FeatureServer":
        addEsriFeatureService(
            url_or_result,
            viz_params=viz_params,
            name=name,
            max_features=max_features,
            where=where,
            token=token,
        )
    elif stype == "MapServer":
        addEsriMapService(url_or_result, name=name, token=token, viz_params=viz_params, target_map=target_map)
    else:
        raise ValueError(
            f"Could not determine service type for URL {url!r}.  "
            f"Use addEsriImageService / addEsriFeatureService / "
            f"addEsriMapService directly, or inspect the service manually "
            f"with getServiceMetadata()."
        )
