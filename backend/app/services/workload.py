"""Synthetic statement-analysis workload - a DEMO-ONLY CPU generator.

Purpose: create real, reproducible, application-level CPU pressure for the
scaling demonstration. It does NOT sleep, inject failures or fake slowness.

Safety bounds
-------------
* Disabled unless NVB_DEMO_WORKLOAD_ENABLED=true (route returns 404 otherwise).
* Only users with the ``demo`` role may call it.
* Inputs are an enum profile and a small integer range - no code, no commands,
  no unbounded sizes. The amount of work per profile is fixed server-side.
* A per-process semaphore caps concurrent executions; callers wait at most
  ``demo_workload_queue_timeout_seconds`` and then receive HTTP 429.
* Each run is cut off after ``demo_workload_max_seconds`` of compute.

The computation analyses a deterministic synthetic statement (generated from
a seeded PRNG - no customer data) and runs a Monte-Carlo cash-flow projection
in pure Python, so it consumes one CPU core per running request.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

PROFILES = {
    # profile: (transactions per month, simulation multiplier)
    "standard": (120, 1.0),
    "heavy": (240, 2.0),
}
CATEGORIES = ("Groceries", "Dining", "Transport", "Utilities", "Shopping", "Health", "Education", "Entertainment")


class WorkloadBusy(Exception):
    pass


class WorkloadTimeout(Exception):
    pass


@dataclass
class WorkloadLimits:
    max_concurrency: int
    queue_timeout_seconds: float
    max_seconds: float
    simulations: int


class WorkloadRunner:
    def __init__(self, limits: WorkloadLimits) -> None:
        self.limits = limits
        self._sem = threading.BoundedSemaphore(limits.max_concurrency)

    def run(self, profile: str, months: int, seed: int) -> dict:
        if profile not in PROFILES:
            raise ValueError("unknown profile")
        if not 1 <= months <= 12:
            raise ValueError("months out of range")
        if not self._sem.acquire(timeout=self.limits.queue_timeout_seconds):
            raise WorkloadBusy()
        try:
            return _analyse(profile, months, seed, self.limits)
        finally:
            self._sem.release()


def _analyse(profile: str, months: int, seed: int, limits: WorkloadLimits) -> dict:
    start = time.perf_counter()
    deadline = start + limits.max_seconds
    per_month, sim_mult = PROFILES[profile]
    rng = random.Random(seed)

    # 1. Generate a synthetic statement.
    txns = []
    for m in range(months):
        income = rng.randint(1_500_000, 4_000_000)  # piastres
        txns.append((m, "Salary", income))
        for _ in range(per_month):
            txns.append((m, rng.choice(CATEGORIES), -rng.randint(2_000, 30_000)))

    # 2. Categorise and aggregate.
    by_cat: dict[str, int] = {}
    monthly_net = [0] * months
    for m, cat, amt in txns:
        monthly_net[m] += amt
        if amt < 0:
            by_cat[cat] = by_cat.get(cat, 0) - amt

    # 3. Monte-Carlo projection of 12 months of net cash flow (pure-Python CPU work).
    simulations = int(limits.simulations * sim_mult)
    mean_net = sum(monthly_net) / months
    spread = (max(monthly_net) - min(monthly_net)) / 2 or 1
    outcomes = []
    for i in range(simulations):
        bal = 0.0
        for _ in range(12):
            bal += rng.gauss(mean_net, spread)
            for _ in range(20):  # inner smoothing loop; fixed size
                bal = bal * 0.9999 + rng.random()
        outcomes.append(bal)
        if (i & 31) == 0 and time.perf_counter() > deadline:
            raise WorkloadTimeout()
    outcomes.sort()

    def pct(p: float) -> int:
        return int(outcomes[int(p * (len(outcomes) - 1))])

    return {
        "synthetic": True,
        "profile": profile,
        "months": months,
        "transactions_analysed": len(txns),
        "simulations": simulations,
        "top_categories": sorted(by_cat.items(), key=lambda kv: -kv[1])[:5],
        "projection_minor": {"p10": pct(0.10), "p50": pct(0.50), "p90": pct(0.90)},
        "compute_ms": round((time.perf_counter() - start) * 1000, 1),
    }
