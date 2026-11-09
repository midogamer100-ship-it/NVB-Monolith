"""Prometheus metrics.

Labels are deliberately low-cardinality: HTTP method, *route template* (not the
raw path), and status class. No customer, account or transaction identifiers.

When the VM runs several uvicorn worker processes, set PROMETHEUS_MULTIPROC_DIR
to an empty writable directory so that /metrics aggregates all workers.
"""

from __future__ import annotations

import os
import threading
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

MULTIPROC = bool(os.environ.get("PROMETHEUS_MULTIPROC_DIR"))

HTTP_REQUESTS = Counter(
    "nvb_http_requests_total", "HTTP requests handled", ["method", "route", "status_class"]
)
HTTP_DURATION = Histogram(
    "nvb_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
HTTP_ERRORS = Counter("nvb_http_errors_total", "HTTP responses with status >= 500", ["route"])
HTTP_IN_FLIGHT = Gauge(
    "nvb_http_requests_in_flight", "Requests currently being processed", multiprocess_mode="livesum"
)
TRANSFERS = Counter("nvb_transfers_total", "Transfer attempts by outcome", ["outcome"])
LOGINS = Counter("nvb_logins_total", "Login attempts by outcome", ["outcome"])
DB_POOL_CHECKED_OUT = Gauge(
    "nvb_db_pool_checked_out", "DB connections currently checked out", multiprocess_mode="livesum"
)
DB_POOL_SIZE = Gauge("nvb_db_pool_size", "Configured DB pool size", multiprocess_mode="livesum")
DB_POOL_OVERFLOW = Gauge(
    "nvb_db_pool_overflow", "DB overflow connections in use", multiprocess_mode="livesum"
)
WORKLOAD_RUNS = Counter("nvb_demo_workload_runs_total", "Synthetic workload executions", ["outcome"])
WORKLOAD_DURATION = Histogram(
    "nvb_demo_workload_duration_seconds",
    "Synthetic workload compute time",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)


class LocalStats:
    """In-process counters for the operations page ("this instance since start")."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.requests = 0
        self.errors = 0
        self.total_duration = 0.0
        self._recent: list[tuple[float, float, bool]] = []  # (ts, duration, is_error)

    def observe(self, duration: float, is_error: bool) -> None:
        now = time.time()
        with self._lock:
            self.requests += 1
            self.errors += int(is_error)
            self.total_duration += duration
            self._recent.append((now, duration, is_error))
            cutoff = now - 60
            if len(self._recent) > 5000 or (self._recent and self._recent[0][0] < cutoff):
                self._recent = [r for r in self._recent if r[0] >= cutoff][-5000:]

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            recent = [r for r in self._recent if r[0] >= now - 60]
            durations = sorted(r[1] for r in recent)
            p95 = durations[int(0.95 * (len(durations) - 1))] if durations else None
            window = min(60.0, max(1.0, now - self.started_at))
            return {
                "uptime_seconds": round(now - self.started_at, 1),
                "requests_total": self.requests,
                "errors_total": self.errors,
                "last_minute": {
                    "requests": len(recent),
                    "request_rate_per_second": round(len(recent) / window, 3),
                    "error_rate": round(sum(1 for r in recent if r[2]) / len(recent), 4) if recent else None,
                    "p95_latency_ms": round(p95 * 1000, 1) if p95 is not None else None,
                },
            }


def render_metrics() -> tuple[bytes, str]:
    if MULTIPROC:
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST


def update_pool_metrics(engine) -> None:
    pool = engine.pool
    try:
        DB_POOL_CHECKED_OUT.set(pool.checkedout())
        DB_POOL_SIZE.set(pool.size())
        DB_POOL_OVERFLOW.set(max(pool.overflow(), 0))
    except AttributeError:
        # Non-QueuePool (e.g. SQLite in tests) does not expose these.
        pass

CASH_OPERATIONS = Counter("nvb_cash_operations_total", "Deposits and withdrawals by outcome", ["kind", "outcome"])
