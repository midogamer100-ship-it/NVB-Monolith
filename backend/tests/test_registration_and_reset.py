"""Self sign-up, admin-created users, forgot/reset password and the demo mailbox."""

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.db import utcnow
from app.main import create_app
from app.models import Account, AuditEvent, Customer, OutboxMessage, PasswordResetToken, User
from tests.conftest import login, make_settings

GOOD = {"username": "nour.kamal", "password": "Valley-pass-2026", "full_name": "Nour Kamal",
        "email": "nour@example.test", "phone": "+201012345678", "city": "Cairo"}
FORGOT_BODY = {"message": "If that account exists, we've sent password reset instructions to its registered email."}


def register(client, **overrides):
    return client.post("/api/auth/register", json={**GOOD, **overrides})


def mailbox_token(app, username: str) -> str:
    db = app.state.sessionmaker()
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.username == username).order_by(OutboxMessage.id.desc()))
    db.close()
    assert msg is not None
    return re.search(r"token=([A-Za-z0-9_-]+)", msg.body).group(1)


def count(app, model, *where) -> int:
    db = app.state.sessionmaker()
    n = db.scalar(select(func.count()).select_from(model).where(*where))
    db.close()
    return n


# --- Sign-up -------------------------------------------------------------------------

def test_register_creates_customer_with_empty_current_account(app, client):
    r = register(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["username"] == "nour.kamal"
    assert re.match(r"^C\d{6}$", body["customer_number"])
    assert body["account"]["balance"] == "0.00" and body["account"]["type"] == "current"
    assert GOOD["password"] not in r.text
    assert "nvb_session" not in r.headers.get("set-cookie", "")  # no automatic sign-in

    c = TestClient(app)
    login(c, "nour.kamal", GOOD["password"])
    accounts = c.get("/api/accounts").json()["accounts"]
    assert len(accounts) == 1 and accounts[0]["balance_minor"] == 0
    assert c.get("/api/profile").json()["full_name"] == "Nour Kamal"
    assert count(app, AuditEvent, AuditEvent.event_type == "auth.register", AuditEvent.outcome == "success") == 1


def test_register_username_is_case_insensitive_and_unique(client):
    assert register(client).status_code == 201
    dup = register(client, username="Nour.Kamal", email="other@example.test")
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "username_taken"
    assert register(client, username="customer001").status_code == 409  # seeded user


@pytest.mark.parametrize("overrides", [
    {"password": "short1"},
    {"password": "onlyletterslong"},
    {"password": "1234567890123"},
    {"password": "my-nour.kamal-pass1"},          # contains the username
    {"username": "ab"},
    {"username": "1starts.with.digit"},
    {"username": "has space"},
    {"email": "not-an-email"},
    {"phone": "0101234567"},
    {"city": "Atlantis"},
    {"full_name": "X"},
    {"full_name": "R2D2 Robot"},
])
def test_register_validation(app, client, overrides):
    assert register(client, **overrides).status_code == 422
    assert count(app, User, User.username == GOOD["username"]) == 0


def test_register_rejects_unknown_fields(client):
    assert register(client, role="admin").status_code == 422


def test_registration_rate_limit_shared_across_instances(app, db_url):
    settings = make_settings(db_url, registration_max_per_ip_per_hour=3)
    a, b = TestClient(create_app(settings)), TestClient(create_app(settings))
    assert register(a, username="user.one").status_code == 201
    assert register(b, username="user.two").status_code == 201
    assert register(a, username="user.three").status_code == 201
    r = register(b, username="user.four")
    assert r.status_code == 429
    assert count(app, User, User.username == "user.four") == 0


def test_registration_can_be_disabled(db_url, app):
    c = TestClient(create_app(make_settings(db_url, self_registration_enabled=False)))
    assert register(c).status_code == 404


# --- Forgot / reset password -----------------------------------------------------------

def test_forgot_password_never_reveals_whether_user_exists(app, client):
    existing = client.post("/api/auth/password/forgot", json={"username": "customer001"})
    unknown = client.post("/api/auth/password/forgot", json={"username": "no-such-user"})
    assert existing.status_code == unknown.status_code == 202
    assert existing.json() == unknown.json() == FORGOT_BODY
    assert count(app, OutboxMessage, OutboxMessage.username == "customer001") == 1
    assert count(app, OutboxMessage, OutboxMessage.username == "no-such-user") == 0
    db = app.state.sessionmaker()
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.username == "customer001"))
    cust_email = db.scalar(select(Customer.email).join(User).where(User.username == "customer001"))
    db.close()
    assert msg.to_address == cust_email and "/reset-password?token=" in msg.body


def test_reset_flow_single_use_and_ends_sessions(app, client):
    old_session = TestClient(app)
    login(old_session, "customer002")
    assert old_session.get("/api/auth/me").status_code == 200

    client.post("/api/auth/password/forgot", json={"username": "customer002"})
    token = mailbox_token(app, "customer002")
    weak = client.post("/api/auth/password/reset", json={"token": token, "new_password": "short"})
    assert weak.status_code == 422
    ok = client.post("/api/auth/password/reset", json={"token": token, "new_password": "Brand-new-pass-77"})
    assert ok.status_code == 200, ok.text

    assert old_session.get("/api/auth/me").status_code == 401           # existing sessions ended
    again = client.post("/api/auth/password/reset", json={"token": token, "new_password": "Another-pass-88"})
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "invalid_or_expired_token"

    fresh = TestClient(app)
    assert fresh.post("/api/auth/login", json={"username": "customer002", "password": "customer-pass-123"}).status_code == 401
    login(fresh, "customer002", "Brand-new-pass-77")


def test_new_token_invalidates_previous_one(app, client):
    client.post("/api/auth/password/forgot", json={"username": "customer003"})
    first = mailbox_token(app, "customer003")
    client.post("/api/auth/password/forgot", json={"username": "customer003"})
    second = mailbox_token(app, "customer003")
    assert first != second
    assert client.post("/api/auth/password/reset",
                       json={"token": first, "new_password": "Brand-new-pass-77"}).status_code == 400
    assert client.post("/api/auth/password/reset",
                       json={"token": second, "new_password": "Brand-new-pass-77"}).status_code == 200


def test_expired_token_rejected(app, client):
    client.post("/api/auth/password/forgot", json={"username": "customer004"})
    token = mailbox_token(app, "customer004")
    db = app.state.sessionmaker()
    db.execute(update(PasswordResetToken).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    db.close()
    r = client.post("/api/auth/password/reset", json={"token": token, "new_password": "Brand-new-pass-77"})
    assert r.status_code == 400


def test_unknown_token_rejected(client):
    r = client.post("/api/auth/password/reset", json={"token": "x" * 43, "new_password": "Brand-new-pass-77"})
    assert r.status_code == 400


def test_forgot_password_throttle_is_silent(app, client):
    for _ in range(5):
        r = client.post("/api/auth/password/forgot", json={"username": "customer001"})
        assert r.status_code == 202 and r.json() == FORGOT_BODY
    assert count(app, OutboxMessage, OutboxMessage.username == "customer001") == 3
    assert count(app, AuditEvent, AuditEvent.event_type == "auth.password_reset_requested",
                 AuditEvent.outcome == "throttled") == 2


def test_reset_clears_login_lockout(app, db_url):
    c = TestClient(create_app(make_settings(db_url, login_max_failures_per_user=2)))
    for _ in range(2):
        c.post("/api/auth/login", json={"username": "customer001", "password": "wrong-password"})
    assert c.post("/api/auth/login", json={"username": "customer001", "password": "wrong-password"}).status_code == 429
    c.post("/api/auth/password/forgot", json={"username": "customer001"})
    c.post("/api/auth/password/reset", json={"token": mailbox_token(app, "customer001"),
                                             "new_password": "Brand-new-pass-77"})
    assert c.post("/api/auth/login", json={"username": "customer001",
                                           "password": "Brand-new-pass-77"}).status_code == 200


# --- Admin creates users, mailbox --------------------------------------------------------

NEW_USER = {"username": "sara.admin.made", "full_name": "Sara Fouad", "email": "sara@example.test",
            "phone": "+201112345678", "city": "Giza"}


def test_admin_create_user_and_setup_link(app):
    admin = TestClient(app)
    login(admin, "opsadmin")
    r = admin.post("/api/ops/users", json=NEW_USER)
    assert r.status_code == 201, r.text
    assert r.json()["account"]["balance"] == "0.00"
    assert "demo mailbox" in r.json()["message"]
    assert admin.post("/api/ops/users", json=NEW_USER).status_code == 409

    # Mailbox shows the setup message; the user cannot sign in until the link is used.
    box = admin.get("/api/ops/mailbox").json()
    assert box["demo_only"] is True
    msg = box["items"][0]
    assert msg["username"] == "sara.admin.made" and msg["kind"] == "account_setup" and msg["to"] == "sara@example.test"
    token = re.search(r"token=([A-Za-z0-9_-]+)", msg["body"]).group(1)

    anon = TestClient(app)
    r = anon.post("/api/auth/password/reset", json={"token": token, "new_password": "Sara-chosen-2026"})
    assert r.status_code == 200
    login(anon, "sara.admin.made", "Sara-chosen-2026")
    assert len(anon.get("/api/accounts").json()["accounts"]) == 1
    assert count(app, AuditEvent, AuditEvent.event_type == "admin.create_user") == 1


def test_admin_create_user_requires_admin_and_csrf(app):
    for user in ("customer001", "demoload01"):
        c = TestClient(app)
        login(c, user)
        assert c.post("/api/ops/users", json=NEW_USER).status_code == 403
        assert c.get("/api/ops/mailbox").status_code == 403
    admin = TestClient(app)
    login(admin, "opsadmin")
    admin.headers.pop("X-CSRF-Token")
    assert admin.post("/api/ops/users", json=NEW_USER).status_code == 403
    assert TestClient(app).get("/api/ops/mailbox").status_code == 401


def test_admin_create_user_validation(app):
    admin = TestClient(app)
    login(admin, "opsadmin")
    assert admin.post("/api/ops/users", json={**NEW_USER, "email": "bad"}).status_code == 422
    assert admin.post("/api/ops/users", json={**NEW_USER, "password": "Nope-1234567"}).status_code == 422
    assert count(app, Account, Account.customer_id.in_(
        select(Customer.id).join(User).where(User.username == NEW_USER["username"]))) == 0
