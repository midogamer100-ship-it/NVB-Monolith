import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.workload import WorkloadBusy, WorkloadLimits, WorkloadRunner
from tests.conftest import login, make_settings


def test_workload_not_exposed_when_disabled(app):
    c = TestClient(app)
    login(c, "demoload01")
    assert c.post("/api/demo/statement-analysis", json={}).status_code == 404
    assert c.get("/api/demo/workload").status_code == 404


@pytest.fixture
def enabled_app(app, db_url):
    return create_app(make_settings(db_url, demo_workload_enabled=True, demo_workload_simulations=20))


def test_workload_requires_demo_role(enabled_app):
    anon = TestClient(enabled_app)
    assert anon.post("/api/demo/statement-analysis", json={}).status_code == 401
    for user in ("customer001", "opsadmin"):
        c = TestClient(enabled_app)
        login(c, user)
        assert c.post("/api/demo/statement-analysis", json={}).status_code == 403


def test_workload_runs_bounded_and_labelled_synthetic(enabled_app):
    c = TestClient(enabled_app)
    login(c, "demoload01")
    r = c.post("/api/demo/statement-analysis", json={"profile": "standard", "months": 2, "seed": 7})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["synthetic"] is True
    assert body["simulations"] == 20
    assert body["compute_ms"] > 0
    # Deterministic for the same seed.
    again = c.post("/api/demo/statement-analysis", json={"profile": "standard", "months": 2, "seed": 7}).json()
    assert again["projection_minor"] == body["projection_minor"]


@pytest.mark.parametrize("payload", [
    {"months": 0}, {"months": 13}, {"profile": "extreme"}, {"seed": -1},
    {"simulations": 10_000_000}, {"code": "import os"},
])
def test_workload_rejects_unbounded_or_unknown_inputs(enabled_app, payload):
    c = TestClient(enabled_app)
    login(c, "demoload01")
    assert c.post("/api/demo/statement-analysis", json=payload).status_code == 422


def test_concurrency_limit_enforced():
    runner = WorkloadRunner(WorkloadLimits(max_concurrency=1, queue_timeout_seconds=0, max_seconds=5, simulations=10))
    runner._sem.acquire()  # occupy the only slot
    try:
        with pytest.raises(WorkloadBusy):
            runner.run("standard", 1, 1)
    finally:
        runner._sem.release()
