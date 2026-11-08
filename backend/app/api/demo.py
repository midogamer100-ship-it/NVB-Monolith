"""Synthetic statement-analysis workload endpoint (demo only).

Not registered at all unless NVB_DEMO_WORKLOAD_ENABLED=true, so it is absent
from the normal public route. When enabled it requires the ``demo`` role.
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.deps import AuthContext, require_demo
from app.metrics import WORKLOAD_DURATION, WORKLOAD_RUNS
from app.services.workload import WorkloadBusy, WorkloadTimeout

router = APIRouter(prefix="/api/demo", tags=["demo"])


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["standard", "heavy"] = "standard"
    months: int = Field(default=6, ge=1, le=12)
    seed: int = Field(default=42, ge=0, le=1_000_000)


@router.get("/workload")
def workload_info(request: Request, auth: AuthContext = Depends(require_demo)):
    limits = request.app.state.workload.limits
    return {
        "synthetic": True,
        "description": "Synthetic statement analysis that consumes real CPU. No customer data is used.",
        "profiles": ["standard", "heavy"],
        "months_range": [1, 12],
        "max_concurrency_per_process": limits.max_concurrency,
        "max_seconds": limits.max_seconds,
        "simulations": limits.simulations,
        "instance_id": request.app.state.settings.resolved_instance_id,
    }


@router.post("/statement-analysis")
async def statement_analysis(
    body: AnalysisRequest,
    request: Request,
    response: Response,
    auth: AuthContext = Depends(require_demo),
):
    runner = request.app.state.workload
    started = time.perf_counter()
    try:
        result = await run_in_threadpool(runner.run, body.profile, body.months, body.seed)
    except WorkloadBusy:
        WORKLOAD_RUNS.labels(outcome="busy").inc()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Workload concurrency limit reached on this instance.",
                            headers={"Retry-After": "1"})
    except WorkloadTimeout:
        WORKLOAD_RUNS.labels(outcome="timeout").inc()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Workload exceeded its execution budget.")
    WORKLOAD_RUNS.labels(outcome="ok").inc()
    WORKLOAD_DURATION.observe(time.perf_counter() - started)
    result["instance_id"] = request.app.state.settings.resolved_instance_id
    return result
