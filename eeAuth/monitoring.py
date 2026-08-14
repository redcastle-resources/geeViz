"""Earth Engine usage monitoring — Cloud Monitoring poller.

Reads the ``earthengine.googleapis.com/project/cpu/usage_time`` metric
from Cloud Monitoring, aggregates at a caller-chosen bucket size
(``grouping_seconds``, default 3600 = hourly), and returns
per-``workload_tag`` rows. **Attribution is not this module's concern**
— it returns the raw tag string; the caller joins it to whatever
storage they maintain (tag → parts mapping table, users table, etc.)
to recover human-readable identity.

Design constraint:  reversible tag encoding within EE's 63-char
workload_tag limit turns out to be infeasible for realistic
attribution tuples (see comments in geeViz/eeAuth/tags.py). Rather than
half-solve the reversibility problem, this module cleanly stops at "here
are the tags and their EECU consumption" — everything upstream (mint the
tag from parts + store the mapping) and everything downstream (join back
for display, feed a billing ledger) stays with the caller.

Typical wiring::

    from geeViz.eeAuth.monitoring import EEUsageMonitor

    monitor = EEUsageMonitor(project="my-gcp-project",
                              cost_per_eecu_hour=0.40)
    rows = monitor.poll(start_time=..., end_time=...)
    # rows: [{workload_tag, bucket_start, eecu_seconds,
    #         eecu_hours, cost_usd}, ...]
    for row in rows:
        parts = my_tag_store.lookup(row["workload_tag"])
        my_db.upsert_ee_bucket(**row, **parts)

Cost model:  ``cost_per_eecu_hour`` × ``eecu_hours``. Google's public
commercial rate is $0.40/EECU-hour; non-commercial projects bill at 0.
The monitor is agnostic — pass whatever your billing agreement says.
"""
from __future__ import annotations

import datetime
import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Module-level lazy singleton for the Cloud Monitoring client. Recreating
# the client on every call costs ~200-500ms (gRPC channel setup + ADC
# lookup); pullers typically fire every 60s so the savings compound.
# Thread-safe via double-checked locking. Deliberately lazy so importing
# this module doesn't fire the auth stack (useful for tooling that just
# walks the geeViz import tree).
_METRIC_CLIENT: Any = None
_METRIC_CLIENT_LOCK = threading.Lock()


def _get_metric_client():
    """Lazy singleton for ``monitoring_v3.MetricServiceClient``. Thread-
    safe. Callers should NOT construct their own client — reuse this one
    to keep the puller loop fast.

    Raises RuntimeError if the ``google-cloud-monitoring`` library isn't
    installed.
    """
    global _METRIC_CLIENT
    if _METRIC_CLIENT is None:
        with _METRIC_CLIENT_LOCK:
            if _METRIC_CLIENT is None:
                try:
                    from google.cloud import monitoring_v3
                except ImportError as e:
                    raise RuntimeError(
                        "google-cloud-monitoring is required for "
                        "EEUsageMonitor — install via "
                        "`pip install google-cloud-monitoring`"
                    ) from e
                _METRIC_CLIENT = monitoring_v3.MetricServiceClient()
    return _METRIC_CLIENT


def _snap_to_period(
    dt: datetime.datetime, period_seconds: int, *, ceil: bool = False
) -> datetime.datetime:
    """Snap a UTC-aware datetime to a multiple of ``period_seconds`` from
    the Unix epoch. Floor by default; ceil rounds up to the next
    boundary. Raises if input is naive or ``period_seconds`` <= 0.

    Because Unix epoch (1970-01-01T00:00:00Z) is itself midnight UTC,
    common calendar periods align naturally:
      * 60      -> minute boundaries
      * 3600    -> hour boundaries
      * 86400   -> UTC midnight (day)
      * 604800  -> weekly (from epoch, i.e. Thursday-anchored)
    Non-standard periods (e.g. 900 for 15 min) snap to stable in-hour
    marks (:00, :15, :30, :45).
    """
    if dt.tzinfo is None:
        raise ValueError("_snap_to_period requires timezone-aware datetime")
    if period_seconds <= 0:
        raise ValueError("period_seconds must be positive")
    dt_utc = dt.astimezone(datetime.timezone.utc)
    epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    sec = int((dt_utc - epoch).total_seconds())
    if ceil:
        snapped = ((sec + period_seconds - 1) // period_seconds) * period_seconds
    else:
        snapped = (sec // period_seconds) * period_seconds
    return epoch + datetime.timedelta(seconds=snapped)


class EEUsageMonitor:
    """Cloud Monitoring poller for EE workload consumption.

    One instance per GCP project. Thread-safe (the underlying
    ``MetricServiceClient`` is a shared singleton and gRPC channels are
    concurrent-safe). Cheap to construct — no I/O until ``poll()``.

    Args:
        project: GCP project id holding the EE metrics (the project
            billed for EE usage). Typically the ``GEE_PROJECT`` /
            ``GOOGLE_CLOUD_PROJECT`` your tenant runs against.
        cost_per_eecu_hour: USD per EECU-hour applied to every returned
            row. Default $0.40 (Google commercial rate). Set to 0 for
            noncommercial projects.
        metric_type: full Cloud Monitoring metric path. Default is the
            current EE CPU metric; override if Google renames it or you
            want to poll a different measurement.
    """

    DEFAULT_METRIC = "earthengine.googleapis.com/project/cpu/usage_time"

    def __init__(
        self,
        project: str,
        cost_per_eecu_hour: float = 0.40,
        metric_type: str = DEFAULT_METRIC,
    ):
        if not project:
            raise ValueError("EEUsageMonitor: project is required")
        self.project = project.strip()
        self.cost_per_eecu_hour = float(cost_per_eecu_hour)
        self.metric_type = metric_type

    def poll(
        self,
        start_time: datetime.datetime,
        end_time: Optional[datetime.datetime] = None,
        grouping_seconds: int = 3600,
        snap_to: bool = True,
    ) -> list[dict]:
        """Query Cloud Monitoring for the configured metric between
        ``start_time`` and ``end_time`` (defaults to NOW), grouped by
        ``metric.workload_tag`` at ``grouping_seconds`` granularity.

        Args:
            start_time: timezone-aware datetime — lower bound.
            end_time: timezone-aware datetime — upper bound. Defaults to
                ``now(UTC)`` if omitted.
            grouping_seconds: bucket size in seconds. Common values:
                ``60`` (minute), ``3600`` (hour, default), ``86400`` (day),
                ``604800`` (week). Any positive int is accepted.
            snap_to: if True (default), ``start_time`` is floored and
                ``end_time`` is ceiled to the nearest multiple of
                ``grouping_seconds`` from the Unix epoch. This keeps
                bucket boundaries stable across repeated polls (e.g. two
                pulls of the same window return the same rows) — highly
                recommended. Pass False to query the raw sub-bucket
                window (useful for ad-hoc slicing).

        Returns one dict per (workload_tag, bucket_start)::

            {
                "workload_tag":  "wl_abc123...",
                "bucket_start":  datetime(2026, 8, 12, 14, 0, tzinfo=UTC),
                "eecu_seconds":  12.34,
                "eecu_hours":    0.003428,
                "cost_usd":      0.001371,
            }

        Rows with negative or missing values are floored to 0. Untagged
        points are skipped — attribution is impossible without a tag.

        Returns an empty list on any Cloud Monitoring error (the error is
        logged). Callers should treat "no rows" as "no usage in window"
        rather than a hard failure.
        """
        if end_time is None:
            end_time = datetime.datetime.now(datetime.timezone.utc)
        if start_time.tzinfo is None:
            raise ValueError("start_time must be timezone-aware")
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=datetime.timezone.utc)
        if grouping_seconds <= 0:
            raise ValueError("grouping_seconds must be positive")

        if snap_to:
            snapped_start = _snap_to_period(start_time, grouping_seconds, ceil=False)
            snapped_end = _snap_to_period(end_time, grouping_seconds, ceil=True)
        else:
            snapped_start = start_time.astimezone(datetime.timezone.utc)
            snapped_end = end_time.astimezone(datetime.timezone.utc)

        try:
            from google.cloud import monitoring_v3
        except ImportError as e:
            raise RuntimeError(
                "google-cloud-monitoring is required for EEUsageMonitor"
            ) from e

        client = _get_metric_client()
        project_name = f"projects/{self.project}"

        request = monitoring_v3.ListTimeSeriesRequest(
            name=project_name,
            filter=f'metric.type = "{self.metric_type}"',
            interval=monitoring_v3.TimeInterval({
                "start_time": snapped_start,
                "end_time":   snapped_end,
            }),
            view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            aggregation=monitoring_v3.Aggregation({
                "alignment_period": {"seconds": grouping_seconds},
                "per_series_aligner": monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
                "cross_series_reducer": monitoring_v3.Aggregation.Reducer.REDUCE_SUM,
                "group_by_fields": ["metric.workload_tag"],
            }),
        )

        try:
            results = client.list_time_series(request=request)
        except Exception:
            logger.exception(
                "EEUsageMonitor: list_time_series failed for project=%s",
                self.project,
            )
            return []

        out: list[dict] = []
        for series in results:
            tag = ""
            try:
                tag = series.metric.labels.get("workload_tag", "") if series.metric else ""
            except Exception:
                pass
            if not tag:
                continue

            for point in series.points:
                eecu_seconds = float(point.value.double_value or 0.0)
                if eecu_seconds < 0:
                    eecu_seconds = 0.0
                eecu_hours = round(eecu_seconds / 3600.0, 6)
                cost = round(eecu_hours * self.cost_per_eecu_hour, 6)

                iv = point.interval
                if not iv or not iv.start_time:
                    continue
                bucket = iv.start_time
                if bucket.tzinfo is None:
                    bucket = bucket.replace(tzinfo=datetime.timezone.utc)
                bucket = bucket.astimezone(datetime.timezone.utc)

                out.append({
                    "workload_tag": tag,
                    "bucket_start": bucket,
                    "eecu_seconds": eecu_seconds,
                    "eecu_hours":   eecu_hours,
                    "cost_usd":     cost,
                })
        return out
