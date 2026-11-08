"""Shared fixtures.

By default tests run against a temporary SQLite file (no external services).
Set NVB_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host/db_for_tests to
run the same suite against PostgreSQL - recommended before every demo, because
row locking (SELECT ... FOR UPDATE) is only truly exercised on PostgreSQL.
The PostgreSQL test database is wiped by the suite: never point it at real data.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.db import Base
from app.main import create_app
from app.services.seed import seed_database

PASSWORDS = {
    "customer": "customer-pass-123",
    "loadtest": "loadtest-pass-123",
    "demo": "demo-pass-123456",
    "admin": "admin-pass-123456",
}


def make_settings(db_url: str, **overrides) -> Settings:
    base = dict(
        database_url=db_url,
        cookie_secure=False,  # TestClient talks plain http
        argon2_time_cost=1,
        argon2_memory_cost_kib=1024,
        log_level="WARNING",
        environment_label="Test",
        metrics_token="test-metrics-token",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def db_url(tmp_path) -> str:
    pg = os.environ.get("NVB_TEST_DATABASE_URL")
    if pg:
        return pg
    return f"sqlite:///{tmp_path / 'nvb-test.db'}"


@pytest.fixture
def settings(db_url) -> Settings:
    return make_settings(db_url)


@pytest.fixture
def app(settings):
    application = create_app(settings)
    engine = application.state.engine
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    Base.metadata.create_all(engine)
    db = application.state.sessionmaker()
    seed_database(db, application.state.passwords, PASSWORDS, customer_count=4, loadtest_count=3, demo_count=1)
    db.close()
    yield application
    engine.dispose()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def login(client: TestClient, username: str, password: str | None = None) -> dict:
    if password is None:
        group = "customer" if username.startswith("customer") else "loadtest" if username.startswith("loadtest") \
            else "demo" if username.startswith("demoload") else "admin"
        password = PASSWORDS[group]
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return body


def idem() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def customer_client(app) -> TestClient:
    c = TestClient(app)
    login(c, "customer001")
    return c
