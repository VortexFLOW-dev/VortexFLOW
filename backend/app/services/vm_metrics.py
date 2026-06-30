# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""VictoriaMetrics query helpers."""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Key Vector internal metrics exposed via prometheus_remote_write
_QUERY_EVENTS_IN = "sum by (host) (rate(vector_component_received_events_total[5m]))"
_QUERY_EVENTS_OUT = "sum by (host) (rate(vector_component_sent_events_total[5m]))"
_QUERY_ERRORS = "sum by (host) (rate(vector_component_errors_total[5m]))"
# Ingest (source-received) vs egress (sink-sent) bytes → volume reduction %.
_QUERY_BYTES_IN = 'sum by (host) (rate(vector_component_received_bytes_total{component_kind="source"}[5m]))'
_QUERY_BYTES_OUT = (
    'sum by (host) (rate(vector_component_sent_bytes_total{component_kind="sink"}[5m]))'
)
# Instance-health (P2) signals: data loss, backpressure, sink delivery failures.
_QUERY_DISCARDED = "sum by (host) (rate(vector_component_discarded_events_total[5m]))"
_QUERY_BUFFER = "max by (host) (vector_buffer_events)"
_QUERY_SINK_FAILED = (
    'sum by (host) (rate(vector_http_client_responses_total{status=~"4..|5.."}[5m]))'
)


async def query_instant(promql: str) -> dict[str, float]:
    """
    Run an instant PromQL query against VictoriaMetrics.
    Returns {host_label: value} mapping.  Returns {} on any error.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"{settings.vm_url}/api/v1/query",
                params={"query": promql},
            )
            if resp.status_code != 200:
                return {}
            data = resp.json()
            result: dict[str, float] = {}
            for item in data.get("data", {}).get("result", []):
                host = item.get("metric", {}).get("host", "unknown")
                value = item.get("value", [None, "0"])
                try:
                    result[host] = round(float(value[1]), 2)
                except (IndexError, ValueError, TypeError):
                    result[host] = 0.0
            return result
    except Exception:
        return {}


# Throughput series metric: events/sec vs bytes/sec (chart toggle).
_SERIES_METRIC = {
    "events": "vector_component_sent_events_total",
    "bytes": "vector_component_sent_bytes_total",
}


async def fetch_fleet_throughput_series(
    host_to_fleet: dict[str, str],
    minutes: int = 60,
    step: str = "5m",
    metric: str = "events",
) -> dict[str, list[float]]:
    """Per-fleet throughput over the last ``minutes``, for the stacked dashboard
    hero. ``metric`` selects events/sec (default) or bytes/sec. Queries the
    per-host sent-rate over a range and folds each host into its fleet. Metrics
    are tagged by ``host`` (not fleet), so the host→fleet map (built from instance
    api_urls) does the grouping — same mapping the instant `fetch_fleet_metrics`
    relies on. Returns ``{fleet_id: [points oldest→newest]}`` with every list
    aligned to one shared timestamp grid; ``{}`` on any error."""
    if not host_to_fleet:
        return {}
    import time

    metric_name = _SERIES_METRIC.get(metric, _SERIES_METRIC["events"])
    now = int(time.time())
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                f"{settings.vm_url}/api/v1/query_range",
                params={
                    "query": f"sum by (host) (rate({metric_name}[5m]))",
                    "start": now - minutes * 60,
                    "end": now,
                    "step": step,
                },
            )
            if resp.status_code != 200:
                return {}
            result = resp.json().get("data", {}).get("result", [])
    except Exception:
        return {}

    # Collect per-host points keyed by timestamp, then fold onto one shared grid
    # (the union of all timestamps) so every fleet series has equal length and a
    # common x-axis — required for stacking on the frontend.
    ts_set: set[int] = set()
    parsed: list[tuple[str, dict[int, float]]] = []
    for series in result:
        host = series.get("metric", {}).get("host")
        if host not in host_to_fleet:
            continue
        pts: dict[int, float] = {}
        for ts, val in series.get("values", []):
            try:
                pts[int(float(ts))] = float(val)
            except (ValueError, TypeError):
                continue
        if pts:
            ts_set.update(pts.keys())
            parsed.append((host, pts))

    if not ts_set:
        return {}
    grid = sorted(ts_set)
    fleet_series: dict[str, list[float]] = {}
    for host, pts in parsed:
        fid = host_to_fleet[host]
        arr = fleet_series.setdefault(fid, [0.0] * len(grid))
        for idx, t in enumerate(grid):
            arr[idx] = round(arr[idx] + pts.get(t, 0.0), 2)
    return fleet_series


_LEADER = 'host="vortexflow-leader"'


async def fetch_leader_metrics() -> dict | None:
    """Fetch the VortexFlow leader's own host metrics (shipped by the bundled
    vector-leader). Returns {load1, mem_pct} or None when unavailable."""
    import asyncio

    load, mem = await asyncio.gather(
        query_instant(f"host_load1{{{_LEADER}}}"),
        query_instant(
            f"100 * host_memory_used_bytes{{{_LEADER}}}"
            f" / host_memory_total_bytes{{{_LEADER}}}"
        ),
    )
    if not load and not mem:
        return None
    return {
        "load1": next(iter(load.values()), None) if load else None,
        "mem_pct": round(next(iter(mem.values())), 1) if mem else None,
    }


async def fetch_fleet_metrics(hostnames: list[str]) -> dict[str, dict]:
    """
    Fetch events_in/out, bytes_in/out, and errors per hostname.
    bytes_in/out are source-received vs sink-sent → volume reduction.
    Falls back gracefully when VM is unavailable.
    """
    if not hostnames:
        return {}

    try:
        import asyncio

        (
            events_in,
            events_out,
            errors,
            bytes_in,
            bytes_out,
            discarded,
            buffer,
            sink_failed,
        ) = await asyncio.gather(
            query_instant(_QUERY_EVENTS_IN),
            query_instant(_QUERY_EVENTS_OUT),
            query_instant(_QUERY_ERRORS),
            query_instant(_QUERY_BYTES_IN),
            query_instant(_QUERY_BYTES_OUT),
            query_instant(_QUERY_DISCARDED),
            query_instant(_QUERY_BUFFER),
            query_instant(_QUERY_SINK_FAILED),
        )
    except Exception:
        logger.warning("VM metrics fetch failed; returning empty metrics")
        events_in, events_out, errors, bytes_in, bytes_out = {}, {}, {}, {}, {}
        discarded, buffer, sink_failed = {}, {}, {}

    result: dict[str, dict] = {}
    for h in hostnames:
        result[h] = {
            "events_in_per_sec": events_in.get(h, 0.0),
            "events_out_per_sec": events_out.get(h, 0.0),
            "errors_per_sec": errors.get(h, 0.0),
            "bytes_in_per_sec": bytes_in.get(h, 0.0),
            "bytes_out_per_sec": bytes_out.get(h, 0.0),
            "discarded_per_sec": discarded.get(h, 0.0),
            "buffer_events": buffer.get(h, 0.0),
            "sink_failed_per_sec": sink_failed.get(h, 0.0),
        }
    return result
