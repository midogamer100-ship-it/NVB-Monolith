"""Integration API authentication, scopes, session introspection and the disabled default."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.api import integration as integration_api
from app.db import utcnow
from app.main import create_app
from app.models import User, UserSession
from app.services.integration_exports import subject_for
from tests.conftest import login, make_settings
from tests.integration_support import ALL_SCOPES, bearer, new_token, user_row, write_clients

TOKEN = new_token()
LIMITED = new_token()


@pytest.fixture
def clients_file(tmp_path):
    path = tmp_path / "integration-clients.json"
    write_clients(path, {"adapter": ([TOKEN], ALL_SCOPES), "limited": ([LIMITED], ["identity:introspect"])})
    return path


@pytest.fixture
def settings(db_url, clients_file):
    return make_settings(db_url, integration_enabled=True, integration_clients_file=str(clients_file),
                         integration_settle_seconds=0)


@pytest.fixture(autouse=True)
def fast_reload(monkeypatch):
    monkeypatch.setattr(integration_api, "RELOAD_CHECK_SECONDS", 0)


def _session(app, username="customer001"):
    c = TestClient(app)
    body = login(c, username)
    return c, c.cookies.get("nvb_session"), body["csrf_token"]


def _introspect(client, token, session_token, **extra):
    return client.post("/internal/v1/sessions/introspect", headers=bearer(token),
                       json={"session_token": session_token, **extra})


# --- Disabled by default -----------------------------------------------------------------


def test_integration_disabled_by_default_registers_nothing(db_url, clients_file):
    from app.db import Base
    from app.services.seed import seed_database
    from tests.conftest import PASSWORDS

    settings = make_settings(db_url)  # integration_enabled defaults to False
    assert settings.integration_enabled is False
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    db = app.state.sessionmaker()
    seed_database(db, app.state.passwords, PASSWORDS, customer_count=2, loadtest_count=0, demo_count=0)
    db.close()
    c = TestClient(app)
    assert not any(getattr(r, "path", "").startswith("/internal") for r in app.routes)
    resp = c.post("/internal/v1/sessions/introspect", headers=bearer(TOKEN), json={"session_token": "x"})
    assert resp.status_code in (404, 405)
    # Existing behaviour preserved
    login(c, "customer001")
    assert c.get("/api/accounts").status_code == 200
    app.state.engine.dispose()


# --- Client authentication -----------------------------------------------------------


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"},
                                     {"Authorization": "Bearer short"}, bearer(new_token())])
def test_invalid_client_credentials_fail_closed(client, headers):
    resp = client.post("/internal/v1/sessions/introspect", headers=headers, json={"session_token": "abc"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_client"
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_missing_scope_is_forbidden(client):
    resp = client.get("/internal/v1/discovery/statement-accounts", headers=bearer(LIMITED))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "insufficient_scope"


def test_no_clients_file_fails_closed(db_url, app):
    other = create_app(make_settings(db_url, integration_enabled=True, integration_clients_file=None))
    resp = TestClient(other).post("/internal/v1/sessions/introspect", headers=bearer(TOKEN),
                                  json={"session_token": "abc"})
    assert resp.status_code == 401


def test_corrupt_clients_file_fails_closed(db_url, app, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    other = create_app(make_settings(db_url, integration_enabled=True, integration_clients_file=str(bad)))
    resp = TestClient(other).post("/internal/v1/sessions/introspect", headers=bearer(TOKEN),
                                  json={"session_token": "abc"})
    assert resp.status_code == 401


def test_unknown_scope_in_file_fails_closed(db_url, app, tmp_path):
    path = tmp_path / "scopes.json"
    write_clients(path, {"adapter": ([TOKEN], ["identity:introspect", "admin:everything"])})
    other = create_app(make_settings(db_url, integration_enabled=True, integration_clients_file=str(path)))
    resp = TestClient(other).post("/internal/v1/sessions/introspect", headers=bearer(TOKEN),
                                  json={"session_token": "abc"})
    assert resp.status_code == 401


def test_credential_rotation_without_restart(client, clients_file):
    import os
    import time

    rotated = new_token()
    write_clients(clients_file, {"adapter": ([TOKEN, rotated], ALL_SCOPES)})
    st = os.stat(clients_file)
    os.utime(clients_file, (st.st_atime, st.st_mtime + 5))
    assert _introspect(client, rotated, "abc").status_code == 200
    assert _introspect(client, TOKEN, "abc").status_code == 200  # overlap period
    write_clients(clients_file, {"adapter": ([rotated], ALL_SCOPES)})
    os.utime(clients_file, (time.time() + 20, time.time() + 20))
    assert _introspect(client, TOKEN, "abc").status_code == 401
    assert _introspect(client, rotated, "abc").status_code == 200


def test_client_token_does_not_grant_customer_api_access(client):
    assert client.get("/api/accounts", headers=bearer(TOKEN)).status_code == 401


def test_unknown_internal_path_is_404(client):
    assert client.get("/internal/v1/nope", headers=bearer(TOKEN)).status_code == 404


# --- Session introspection -------------------------------------------------------------


def test_introspect_active_session_returns_stable_subject(app, client):
    _c, cookie, _csrf = _session(app)
    body = _introspect(client, TOKEN, cookie).json()
    user = user_row(app, "customer001")
    assert body["active"] is True
    assert body["subject"] == subject_for(user)
    assert body["role"] == "customer"
    assert body["customer_number"]
    assert body["csrf_valid"] is None
    assert "csrf_token" not in body  # the CSRF secret is never disclosed to services
    assert "accounts" not in body


def test_introspect_unknown_token_inactive(client):
    assert _introspect(client, TOKEN, "not-a-real-session-token").json() == {"active": False}


def test_introspect_checks_csrf(app, client):
    _c, cookie, csrf = _session(app)
    assert _introspect(client, TOKEN, cookie, csrf_token=csrf).json()["csrf_valid"] is True
    assert _introspect(client, TOKEN, cookie, csrf_token="forged").json()["csrf_valid"] is False
    assert _introspect(client, TOKEN, cookie, csrf_token="").json()["csrf_valid"] is False


def test_csrf_of_another_session_is_invalid(app, client):
    _c1, cookie1, _ = _session(app, "customer001")
    _c2, _cookie2, csrf2 = _session(app, "customer002")
    assert _introspect(client, TOKEN, cookie1, csrf_token=csrf2).json()["csrf_valid"] is False


def test_introspect_after_logout_is_inactive(app, client):
    c, cookie, _ = _session(app)
    assert c.post("/api/auth/logout").status_code == 200
    assert _introspect(client, TOKEN, cookie).json() == {"active": False}


@pytest.mark.parametrize("column", ["expires_at", "absolute_expires_at"])
def test_introspect_expired_session_is_inactive(app, client, column):
    _c, cookie, _ = _session(app)
    db = app.state.sessionmaker()
    db.execute(update(UserSession).values({column: utcnow() - timedelta(seconds=1)}))
    db.commit()
    db.close()
    assert _introspect(client, TOKEN, cookie).json() == {"active": False}


def test_introspect_suspended_user_is_inactive(app, client):
    _c, cookie, _ = _session(app)
    db = app.state.sessionmaker()
    db.execute(update(User).where(User.username == "customer001").values(is_active=False))
    db.commit()
    db.close()
    assert _introspect(client, TOKEN, cookie).json() == {"active": False}


def test_forged_identity_headers_are_ignored(app, client):
    _c, cookie, _ = _session(app, "customer001")
    resp = client.post("/internal/v1/sessions/introspect",
                       headers={**bearer(TOKEN), "X-User": "opsadmin", "X-Role": "admin",
                                "X-Customer-Number": "C000002", "X-Subject": "nvb-user:1:1"},
                       json={"session_token": cookie})
    body = resp.json()
    assert body["subject"] == subject_for(user_row(app, "customer001"))
    assert body["role"] == "customer"


def test_include_accounts_lists_only_own_accounts(app, client):
    _c, cookie, _ = _session(app, "customer001")
    body = _introspect(client, TOKEN, cookie, include_accounts=True).json()
    own = {a["id"] for a in _c.get("/api/accounts").json()["accounts"]}
    assert {a["account_id"] for a in body["accounts"]} == own
    for a in body["accounts"]:
        assert a["masked_number"].startswith("•••• ")
        assert "account_number" not in a


def test_include_accounts_requires_accounts_scope(app, client):
    _c, cookie, _ = _session(app)
    resp = _introspect(client, LIMITED, cookie, include_accounts=True)
    assert resp.status_code == 403


def test_admin_session_is_not_a_customer(app, client):
    _c, cookie, _ = _session(app, "opsadmin")
    body = _introspect(client, TOKEN, cookie, include_accounts=True).json()
    assert body["role"] == "admin"
    assert body["accounts"] == []
    assert body["customer_number"] is None
