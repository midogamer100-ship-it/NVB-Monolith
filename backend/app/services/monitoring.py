"""Optional, read-only Prometheus / Thanos Querier integration.

Used only by the admin operations page to show cluster-wide request rate,
latency, error rate and the *actual* available replica count. When not
configured, every value is reported as "not_configured" - nothing is faked.

On OpenShift the recommended endpoint is the Thanos Querier tenancy port
(https://thanos-querier.openshift-monitoring.svc:9092) which enforces a
``namespace`` query parameter and accepts a ServiceAccount token that has
view access to that namespace. The app never calls the Kubernetes API.
"""

from __future__ import annotations

import logging
import math

import httpx

from app.config import Settings

log = logging.getLogger("nvb.monitoring")


def _queries(s: Settings) -> dict[str, str]:
    ns = s.prometheus_namespace or ""
    dep = s.prometheus_deployment
    sel = f'namespace="{ns}"' if ns else ""
    return {
        "request_rate_per_second": f"sum(rate(nvb_http_requests_total{{{sel}}}[2m]))",
        "p95_latency_seconds": (
            f"histogram_quantile(0.95, sum by (le) (rate(nvb_http_request_duration_seconds_bucket{{{sel}}}[2m])))"
        ),
        "error_rate": (
            f'sum(rate(nvb_http_requests_total{{{sel}{"," if sel else ""}status_class="5xx"}}[2m]))'
            f" / clamp_min(sum(rate(nvb_http_requests_total{{{sel}}}[2m])), 1e-9)"
        ),
        "available_replicas": f'kube_deployment_status_replicas_available{{{sel}{"," if sel else ""}deployment="{dep}"}}',
        "desired_replicas": f'kube_deployment_spec_replicas{{{sel}{"," if sel else ""}deployment="{dep}"}}',
    }


def cluster_metrics(s: Settings) -> dict:
    if not s.prometheus_url:
        return {"status": "not_configured"}
    headers = {}
    if s.prometheus_token_file:
        try:
            with open(s.prometheus_token_file, encoding="utf-8") as fh:
                headers["Authorization"] = "Bearer " + fh.read().strip()
        except OSError:
            log.warning("prometheus token file unreadable")
            return {"status": "error", "message": "Monitoring token unavailable."}
    verify: bool | str = s.prometheus_ca_file or True
    results: dict = {"status": "ok", "source": "prometheus"}
    try:
        with httpx.Client(timeout=s.prometheus_timeout_seconds, verify=verify, headers=headers) as client:
            for name, query in _queries(s).items():
                params = {"query": query}
                if s.prometheus_namespace:
                    params["namespace"] = s.prometheus_namespace
                resp = client.get(s.prometheus_url.rstrip("/") + "/api/v1/query", params=params)
                resp.raise_for_status()
                data = resp.json().get("data", {}).get("result", [])
                value = None
                if data:
                    raw = float(data[0]["value"][1])
                    value = None if math.isnan(raw) or math.isinf(raw) else raw
                results[name] = value
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning("prometheus query failed", extra={"error": type(exc).__name__})
        return {"status": "error", "message": "Monitoring query failed."}
    return results
