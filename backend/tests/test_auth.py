from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.db import utcnow
from app.main import create_app
from app.models import AuditEvent, UserSession
from tests.conftest import PASSWORDS, login, make_settings


def test_login_success_sets_httponly_cookie(client):
    r = client.post("/api/auth/login", json={"username": "customer001", "password": PASSWORDS["customer"]})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "customer"
    assert body["csrf_token"]
    cookie = r.headers["set-cookie"].lower()
    assert "nvb_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert PASSWORDS["customer"] not in r.text


def test_secure_cookie_flag_when_enabled(db_url, app):
    secure_app = create_app(make_settings(db_url, cookie_secure=True))
    c = TestClient(secure_app, base_url="https://testserver")
    r = c.post("/api/auth/login", json={"username": "customer001", "password": PASSWORDS["customer"]})
    assert r.status_code == 200
    assert "secure" in r.headers["set-cookie"].lower()
    assert "strict-transport-security" in r.headers


def test_generic_error_for_wrong_password_and_unknown_user(client):
    wrong = client.post("/api/auth/login", json={"username": "customer001", "password": "nope-nope-nope"})
    unknown = client.post("/api/auth/login", json={"username": "no-such-user", "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid username or password."}


def test_protected_endpoints_require_session(client):
    for path in ("/api/dashboard", "/api/accounts", "/api/transactions", "/api/profile", "/api/ops/status",
                 "/api/auth/me", "/api/beneficiaries"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/transfers", json={}).status_code in (401, 422)


def test_csrf_required_for_state_changing_requests(customer_client):
    token = customer_client.headers.pop("X-CSRF-Token")
    r = customer_client.patch("/api/profile", json={"city": "Giza"})
    assert r.status_code == 403
    r = customer_client.patch("/api/profile", json={"city": "Giza"}, headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    r = customer_client.patch("/api/profile", json={"city": "Giza"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 200


def test_logout_invalidates_session(customer_client):
    assert customer_client.get("/api/auth/me").status_code == 200
    assert customer_client.post("/api/auth/logout").status_code == 200
    assert customer_client.get("/api/auth/me").status_code == 401


def test_stolen_cookie_unusable_after_logout(app):
    c = TestClient(app)
    login(c, "customer001")
    cookie = c.cookies.get("nvb_session")
    c.post("/api/auth/logout")
    other = TestClient(app)
    other.cookies.set("nvb_session", cookie)
    assert other.get("/api/auth/me").status_code == 401


def test_session_idle_expiry(app, customer_client):
    db = app.state.sessionmaker()
    db.execute(update(UserSession).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    db.close()
    assert customer_client.get("/api/auth/me").status_code == 401


def test_session_absolute_expiry(app, customer_client):
    db = app.state.sessionmaker()
    db.execute(update(UserSession).values(absolute_expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    db.close()
    assert customer_client.get("/api/dashboard").status_code == 401


def test_login_throttling_is_identical_for_existing_and_unknown_users(app, db_url):
    settings = make_settings(db_url, login_max_failures_per_user=3)
    c = TestClient(create_app(settings))
    for user in ("customer002", "ghost-user"):
        for _ in range(3):
            assert c.post("/api/auth/login", json={"username": user, "password": "wrong-password"}).status_code == 401
        blocked = c.post("/api/auth/login", json={"username": user, "password": "wrong-password"})
        assert blocked.status_code == 429
    # Even the correct password is refused while throttled.
    r = c.post("/api/auth/login", json={"username": "customer002", "password": PASSWORDS["customer"]})
    assert r.status_code == 429


def test_throttle_is_shared_across_instances(app, db_url):
    settings = make_settings(db_url, login_max_failures_per_user=2)
    a, b = TestClient(create_app(settings)), TestClient(create_app(settings))
    a.post("/api/auth/login", json={"username": "customer003", "password": "wrong-password"})
    b.post("/api/auth/login", json={"username": "customer003", "password": "wrong-password"})
    assert a.post("/api/auth/login", json={"username": "customer003", "password": "wrong-password"}).status_code == 429


def test_role_enforcement(app):
    admin = TestClient(app)
    login(admin, "opsadmin")
    assert admin.get("/api/ops/status").status_code == 200
    assert admin.get("/api/accounts").status_code == 403  # admin has no customer data access

    cust = TestClient(app)
    login(cust, "customer001")
    assert cust.get("/api/ops/status").status_code == 403
    assert cust.get("/api/ops/audit").status_code == 403


def test_auth_events_are_audited_without_secrets(app, client):
    client.post("/api/auth/login", json={"username": "customer001", "password": "bad-password-1"})
    login(client, "customer001")
    db = app.state.sessionmaker()
    events = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "auth.login")).all()
    outcomes = {e.outcome for e in events}
    assert {"failure", "success"} <= outcomes
    for e in events:
        assert "password" not in str(e.details).lower()
    db.close()


def test_admin_unlock_is_audited(app):
    admin = TestClient(app)
    login(admin, "opsadmin")
    r = admin.post("/api/ops/users/customer004/unlock")
    assert r.status_code == 200
    db = app.state.sessionmaker()
    assert db.scalar(select(AuditEvent).where(AuditEvent.event_type == "admin.unlock_user")) is not None
    db.close()
