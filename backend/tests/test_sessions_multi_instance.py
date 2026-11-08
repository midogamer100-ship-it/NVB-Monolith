"""Sessions live in the shared database, so any replica can serve any request."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import idem, login, make_settings


def test_session_created_on_one_instance_works_on_another(app, db_url):
    replica_a = TestClient(create_app(make_settings(db_url, instance_id="replica-a")))
    replica_b = TestClient(create_app(make_settings(db_url, instance_id="replica-b")))

    body = login(replica_a, "customer001")
    replica_b.cookies.update(replica_a.cookies)
    replica_b.headers["X-CSRF-Token"] = body["csrf_token"]

    r = replica_b.get("/api/auth/me")
    assert r.status_code == 200
    assert r.headers["X-NVB-Instance"] == "replica-b"
    assert r.json()["user"]["username"] == "customer001"

    # A state-changing request (CSRF-protected) on the other replica also works.
    src = replica_b.get("/api/accounts").json()["accounts"][0]
    ben = replica_b.get("/api/beneficiaries").json()["beneficiaries"][0]
    t = replica_b.post("/api/transfers", json={"source_account_id": src["id"], "beneficiary_id": ben["id"],
                                               "amount": "1.00"}, headers={"Idempotency-Key": idem()})
    assert t.status_code == 201

    # Retrying the same idempotency key on the *other* replica replays, not re-executes.
    key = idem()
    first = replica_a.post("/api/transfers", json={"source_account_id": src["id"], "beneficiary_id": ben["id"],
                                                   "amount": "2.00"}, headers={"Idempotency-Key": key})
    retry = replica_b.post("/api/transfers", json={"source_account_id": src["id"], "beneficiary_id": ben["id"],
                                                   "amount": "2.00"}, headers={"Idempotency-Key": key})
    assert first.status_code == 201 and retry.status_code == 200
    assert first.json()["reference"] == retry.json()["reference"]

    # Logout on replica B ends the session everywhere.
    assert replica_b.post("/api/auth/logout").status_code == 200
    assert replica_a.get("/api/auth/me").status_code == 401
