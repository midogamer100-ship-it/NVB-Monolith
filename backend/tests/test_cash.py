"""Deposit and withdraw: correctness, idempotency, limits, isolation, concurrency."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.models import Account, CashOperation, Customer, LedgerEntry, User
from tests.conftest import idem, login


def balance(app, account_id: int) -> int:
    db = app.state.sessionmaker()
    value = db.scalar(select(Account.balance_minor).where(Account.id == account_id))
    db.close()
    return value


def own_account(client) -> dict:
    return client.get("/api/accounts").json()["accounts"][0]


def cash(client, account_id, kind, amount, key=None, description=""):
    path = "deposit" if kind == "deposit" else "withdraw"
    return client.post(f"/api/accounts/{account_id}/{path}", json={"amount": amount, "description": description},
                       headers={"Idempotency-Key": key or idem()})


def test_deposit_and_withdraw_update_balance_and_ledger(app, customer_client):
    acct = own_account(customer_client)
    start = acct["balance_minor"]
    d = cash(customer_client, acct["id"], "deposit", "1500.25", description="Salary top-up")
    assert d.status_code == 201, d.text
    body = d.json()
    assert body["kind"] == "deposit" and body["status"] == "completed" and body["reference"].startswith("CSH")
    assert body["account"]["balance_minor"] == start + 150025
    w = cash(customer_client, acct["id"], "withdrawal", "500.00")
    assert w.status_code == 201
    assert w.json()["description"] == "Cash withdrawal"
    assert balance(app, acct["id"]) == start + 150025 - 50000

    db = app.state.sessionmaker()
    entries = {e.reference: e for e in db.scalars(select(LedgerEntry).where(
        LedgerEntry.reference.in_([body["reference"], w.json()["reference"]]))).all()}
    db.close()
    dep, wd = entries[body["reference"]], entries[w.json()["reference"]]
    assert (dep.direction, dep.txn_type, dep.category, dep.description) == ("credit", "deposit", "Cash deposit",
                                                                            "Salary top-up")
    assert (wd.direction, wd.txn_type, wd.category) == ("debit", "withdrawal", "Cash")
    assert wd.balance_after_minor == balance(app, acct["id"])

    filtered = customer_client.get("/api/transactions?type=withdrawal").json()
    assert [i["reference"] for i in filtered["items"]] == [w.json()["reference"]]


def test_withdraw_insufficient_funds_persisted_and_replayed(app, customer_client):
    acct = own_account(customer_client)
    key = idem()
    db = app.state.sessionmaker()
    db.execute(update(Account).where(Account.id == acct["id"]).values(balance_minor=1000))
    db.commit()
    db.close()
    r = cash(customer_client, acct["id"], "withdrawal", "10.01", key=key)
    assert r.status_code == 422
    assert r.json()["status"] == "failed" and r.json()["failure_reason"] == "insufficient_funds"
    assert "No money was moved" in r.json()["message"]
    assert balance(app, acct["id"]) == 1000
    replay = cash(customer_client, acct["id"], "withdrawal", "10.01", key=key)
    assert replay.json()["reference"] == r.json()["reference"]
    db = app.state.sessionmaker()
    assert db.scalar(select(func.count()).select_from(LedgerEntry)
                     .where(LedgerEntry.reference == r.json()["reference"])) == 0
    db.close()


def test_withdraw_exact_balance_to_zero(app, customer_client):
    acct = own_account(customer_client)
    db = app.state.sessionmaker()
    db.execute(update(Account).where(Account.id == acct["id"]).values(balance_minor=12345))
    db.commit()
    db.close()
    assert cash(customer_client, acct["id"], "withdrawal", "123.45").status_code == 201
    assert balance(app, acct["id"]) == 0


@pytest.mark.parametrize("kind,amount", [
    ("deposit", "0"), ("deposit", "-1.00"), ("deposit", "1.001"), ("deposit", "abc"),
    ("deposit", "100000.01"),            # over deposit limit
    ("withdrawal", "50000.01"),          # over withdrawal limit
    ("withdrawal", "0.00"),
])
def test_invalid_amounts_and_limits(app, customer_client, kind, amount):
    acct = own_account(customer_client)
    before = balance(app, acct["id"])
    assert cash(customer_client, acct["id"], kind, amount).status_code == 422
    assert balance(app, acct["id"]) == before


def test_limits_at_boundary_allowed(app, customer_client):
    acct = own_account(customer_client)
    assert cash(customer_client, acct["id"], "deposit", "100000.00").status_code == 201
    assert cash(customer_client, acct["id"], "withdrawal", "50000.00").status_code == 201


def test_float_amount_and_unknown_fields_rejected(customer_client):
    acct = own_account(customer_client)
    r = customer_client.post(f"/api/accounts/{acct['id']}/deposit", json={"amount": 10.5},
                             headers={"Idempotency-Key": idem()})
    assert r.status_code == 422
    r = customer_client.post(f"/api/accounts/{acct['id']}/deposit", json={"amount": "1.00", "account_id": 1},
                             headers={"Idempotency-Key": idem()})
    assert r.status_code == 422


def test_cannot_use_other_customers_account(app, customer_client):
    db = app.state.sessionmaker()
    other = db.scalar(select(Account.id).join(Customer).join(User).where(User.username == "customer002"))
    db.close()
    before = balance(app, other)
    assert cash(customer_client, other, "deposit", "10.00").status_code == 404
    assert cash(customer_client, other, "withdrawal", "10.00").status_code == 404
    assert balance(app, other) == before


def test_admin_cannot_deposit(app):
    admin = TestClient(app)
    login(admin, "opsadmin")
    assert admin.post("/api/accounts/1/deposit", json={"amount": "1.00"},
                      headers={"Idempotency-Key": idem()}).status_code == 403


def test_idempotent_replay_and_conflict(app, customer_client):
    acct = own_account(customer_client)
    before = balance(app, acct["id"])
    key = idem()
    first = cash(customer_client, acct["id"], "deposit", "75.00", key=key)
    second = cash(customer_client, acct["id"], "deposit", "75.00", key=key)
    assert first.status_code == 201 and second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert first.json()["reference"] == second.json()["reference"]
    assert balance(app, acct["id"]) == before + 7500
    assert cash(customer_client, acct["id"], "deposit", "76.00", key=key).status_code == 409
    assert cash(customer_client, acct["id"], "withdrawal", "75.00", key=key).status_code == 409
    assert balance(app, acct["id"]) == before + 7500


def test_idempotency_key_and_csrf_required(customer_client):
    acct = own_account(customer_client)
    r = customer_client.post(f"/api/accounts/{acct['id']}/deposit", json={"amount": "1.00"})
    assert r.status_code == 400
    token = customer_client.headers.pop("X-CSRF-Token")
    assert cash(customer_client, acct["id"], "deposit", "1.00").status_code == 403
    customer_client.headers["X-CSRF-Token"] = token


def test_concurrent_withdrawals_never_overdraw(app):
    c = TestClient(app)
    login(c, "loadtest001")
    acct = own_account(c)
    db = app.state.sessionmaker()
    db.execute(update(Account).where(Account.id == acct["id"]).values(balance_minor=10000))
    db.commit()
    db.close()

    def attempt(_):
        cl = TestClient(app)
        cl.cookies.update(c.cookies)
        cl.headers["X-CSRF-Token"] = c.headers["X-CSRF-Token"]
        return cash(cl, acct["id"], "withdrawal", "30.00").status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(attempt, range(10)))
    assert codes.count(201) == 3 and codes.count(422) == 7
    assert balance(app, acct["id"]) == 1000


def test_concurrent_duplicate_key_executes_once(app):
    c = TestClient(app)
    login(c, "loadtest002")
    acct = own_account(c)
    before = balance(app, acct["id"])
    key = idem()

    def attempt(_):
        cl = TestClient(app)
        cl.cookies.update(c.cookies)
        cl.headers["X-CSRF-Token"] = c.headers["X-CSRF-Token"]
        r = cash(cl, acct["id"], "deposit", "40.00", key=key)
        return r.status_code, r.json()["reference"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert len({ref for _, ref in results}) == 1
    assert [code for code, _ in results].count(201) == 1
    assert balance(app, acct["id"]) == before + 4000
    db = app.state.sessionmaker()
    assert db.scalar(select(func.count()).select_from(CashOperation).where(CashOperation.idempotency_key == key)) == 1
    db.close()


def test_deposit_counts_as_income_on_dashboard(customer_client):
    acct = own_account(customer_client)
    before = customer_client.get("/api/dashboard").json()["monthly"][-1]["income_minor"]
    cash(customer_client, acct["id"], "deposit", "200.00")
    after = customer_client.get("/api/dashboard").json()["monthly"][-1]["income_minor"]
    assert after == before + 20000
