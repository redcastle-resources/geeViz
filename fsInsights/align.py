"""Putting LCMS and FIA side by side, without pretending they agree.

The two answer complementary halves of one question over overlapping
geography, and almost nobody joins them because the APIs look nothing
alike. That is the opportunity. The hazard is that joining them invites
a comparison that is easy to make and easy to get wrong.

======================  ==========================  =========================
                        LCMS                        FIA
======================  ==========================  =========================
Nature                  Wall-to-wall classified map Probability sample
Resolution              30 m, annual, 1985-2025     Plots, multi-year panels
Answers                 What changed, and where     What is there, +/- error
Uncertainty             Map accuracy                Design-based std. error
======================  ==========================  =========================

**Map-derived area is not a design-based area estimate.** Comparing them
conflates map accuracy with sampling error, and the two can differ
substantially without either being wrong — different definitions of
"forest", different minimum mapping units, different reference dates.

So nothing here returns a blended number. Every row carries the
``source`` and ``estimator`` that produced it, and the comparison
helpers report a difference *alongside* the caveat rather than instead
of it. The goal is to make the comparison easy to look at and hard to
misread.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .fia import estimate
from .lcms import lcms_summary

logger = logging.getLogger(__name__)

#: LCMS land-cover classes that carry tree cover. Used to build a
#: "treed area" figure that is *comparable in spirit* to FIA forest
#: land — not equal to it. FIA's definition is about land use and
#: stocking potential, not present canopy, so a recently harvested
#: stand stays forest land in FIA while LCMS may map it as grass or
#: barren in the same year. That divergence is real signal, and it is
#: exactly what a naive join would hide.
TREE_CLASSES = (
    "Trees",
    "Tall Shrubs & Trees Mix",
    "Shrubs & Trees Mix",
    "Grass/Forb/Herb & Trees Mix",
    "Barren & Trees Mix",
)

#: FIA attribute 2 — "Area of forest land, in acres".
FOREST_AREA_SNUM = 2


def lcms_tree_area(state: str = "", county: str = "", *,
                   region: str = "", forest: str = "", district: str = "",
                   year: Optional[int] = None,
                   tree_classes: Optional[tuple] = None,
                   release: str = "") -> "Any":
    """LCMS area in tree-bearing land cover classes, by year.

    Args:
        tree_classes: Override which classes count as treed. The default
            includes the mixed classes, which matters: excluding them
            understates treed area in exactly the transitional stands
            where LCMS and FIA are most likely to disagree.

    Returns:
        ``pandas.DataFrame`` with ``year``, ``acres``, ``classes_used``,
        ``source``, ``estimator``.
    """
    classes = tuple(tree_classes or TREE_CLASSES)
    df = lcms_summary("Land_Cover", state=state, county=county,
                      region=region, forest=forest, district=district,
                      year=year, release=release)
    if not hasattr(df, "empty"):
        return df

    treed = df[df["class_name"].isin(classes)]
    if treed.empty:
        logger.warning(
            "fsInsights.align: no LCMS classes matched %s — available: %s",
            classes, sorted(df["class_name"].unique()),
        )

    out = (treed.groupby("year", as_index=False)["acres"].sum()
           if not treed.empty else treed.assign(acres=0.0))
    out["classes_used"] = ", ".join(classes)
    out["source"] = "lcms"
    out["estimator"] = "wall-to-wall map (map accuracy)"
    return out


def fia_forest_area(wc: int, *, rselected: str = "",
                    snum: int = FOREST_AREA_SNUM, **kwargs) -> "Any":
    """FIA forest-land area with its sampling error.

    Thin wrapper over :func:`~geeViz.fsInsights.estimate` that stamps the
    estimator label, so a frame from here and a frame from
    :func:`lcms_tree_area` can be concatenated without losing track of
    which is which.
    """
    df = estimate(wc, snum, rselected=rselected, **kwargs)
    if hasattr(df, "assign"):
        df = df.assign(source="fia",
                       estimator="probability sample (design-based SE)")
    return df


def compare_area(*, wc: int, state: str = "", county: str = "",
                 year: Optional[int] = None,
                 tree_classes: Optional[tuple] = None,
                 release: str = "") -> Dict[str, Any]:
    """Put an LCMS treed area and an FIA forest-land estimate side by side.

    Returns a dict rather than a single frame, because the two halves are
    not rows of one table — they are two different estimators of two
    related-but-distinct quantities, and stacking them would imply a
    comparability that does not exist.

    Keys:
        ``lcms``: per-year treed area frame.
        ``fia``: forest-land estimate with ``se_pct`` and ``plots``.
        ``comparison``: a small dict with both figures, their absolute
            and percentage difference, and ``caveats`` — a list of the
            reasons they can legitimately disagree.

    The difference is offered as an observation, never as an error term.
    A 15% gap between these does not mean either is 15% wrong.
    """
    lc = lcms_tree_area(state=state, county=county, year=year,
                        tree_classes=tree_classes, release=release)
    fi = fia_forest_area(wc)

    lcms_acres = None
    try:
        lcms_acres = float(lc["acres"].iloc[-1]) if len(lc) else None
    except Exception:
        pass

    fia_acres = fia_se = fia_plots = None
    try:
        tot = fi[(fi["row"] == "Total")]
        if len(tot):
            fia_acres = float(tot["estimate"].iloc[0])
            fia_se = float(tot["se_pct"].iloc[0])
            fia_plots = int(tot["plots"].iloc[0])
    except Exception:
        pass

    diff = pct = None
    if lcms_acres is not None and fia_acres:
        diff = lcms_acres - fia_acres
        pct = 100.0 * diff / fia_acres

    return {
        "lcms": lc,
        "fia": fi,
        "comparison": {
            "lcms_treed_acres": lcms_acres,
            "fia_forest_acres": fia_acres,
            "fia_se_pct": fia_se,
            "fia_plots": fia_plots,
            "difference_acres": diff,
            "difference_pct_of_fia": pct,
            "caveats": [
                "LCMS area is map-derived; FIA area is a design-based "
                "estimate. The difference mixes map accuracy with "
                "sampling error and is not an error term for either.",
                "FIA 'forest land' is a land-use definition based on "
                "stocking and potential; LCMS land cover describes "
                "present canopy. A recently harvested stand stays "
                "forest land in FIA while LCMS may map it as grass or "
                "barren the same year.",
                "Reference periods differ: an FIA evaluation spans "
                "several years of panels, while an LCMS year is a "
                "single annual map.",
                "Minimum mapping unit and edge handling differ, which "
                "matters most in fragmented landscapes.",
            ],
        },
    }


def summarize_comparison(result: Dict[str, Any]) -> str:
    """One readable paragraph from :func:`compare_area`, caveats included.

    Written to be pasted into a report. The caveat is part of the
    sentence rather than a footnote, because a number this easy to
    quote is a number that travels without its footnotes.
    """
    c = result.get("comparison", {})
    lc, fi = c.get("lcms_treed_acres"), c.get("fia_forest_acres")
    if lc is None or fi is None:
        return "Not enough data to compare (one of the two sources returned nothing)."

    se, plots = c.get("fia_se_pct"), c.get("fia_plots")
    pct = c.get("difference_pct_of_fia")
    return (
        f"LCMS maps {lc:,.0f} acres of tree-bearing land cover. FIA "
        f"estimates {fi:,.0f} acres of forest land"
        + (f" (SE {se:.1f}%, {plots:,} plots)" if se is not None else "")
        + f", a difference of {pct:+.1f}%. These are different estimators "
        f"of related but distinct quantities - map-derived cover versus a "
        f"design-based land-use estimate - so the gap is not an error in "
        f"either. FIA counts recently harvested stands as forest land; "
        f"LCMS maps present canopy."
    )
