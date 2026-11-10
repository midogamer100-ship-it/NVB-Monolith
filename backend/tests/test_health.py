from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def test_live_is_ok(client):
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_checks_database(client):
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["database"] == "ok"


def test_live_independent_of_database_and_ready_fails_without_it():
    # Port 1 on localhost: nothing listens, connection is refused quickly.
    settings = make_settings("postgresql+psycopg://nobody:nothing@127.0.0.1:1/none", db_connect_timeout_seconds=1)
    c = TestClient(create_app(settings))
    assert c.get("/health/live").status_code == 200
    r = c.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["database"] == "unavailable"


def test_metrics_requires_token(client):
    assert client.get("/metrics").status_code == 401
    r = client.get("/metrics", headers={"Authorization": "Bearer test-metrics-token"})
    assert r.status_code == 200
    assert "nvb_http_requests_total" in r.text
    assert "nvb_http_request_duration_seconds_bucket" in r.text


def test_metrics_disabled_without_token_configuration(db_url):
    settings = make_settings(db_url, metrics_token=None)
    c = TestClient(create_app(settings))
    assert c.get("/metrics").status_code == 403


def test_metrics_labels_use_route_templates_not_ids(customer_client):
    customer_client.get("/api/accounts/999999")
    r = customer_client.get("/metrics", headers={"Authorization": "Bearer test-metrics-token"})
    assert 'route="/api/accounts/{account_id}"' in r.text
    # Check label values only: float sample values (e.g. duration sums) may contain "999999".
    labels = [line[line.index("{"):line.index("}") + 1] for line in r.text.splitlines()
              if not line.startswith("#") and "{" in line]
    assert labels and not any("999999" in lbl for lbl in labels)


def test_request_id_and_instance_headers(client):
    r = client.get("/health/live", headers={"X-Request-ID": "demo-request-0001"})
    assert r.headers["X-Request-ID"] == "demo-request-0001"
    assert r.headers["X-NVB-Instance"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
