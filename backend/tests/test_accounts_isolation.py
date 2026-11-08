"""Customers must never see or act on another customer's data."""

import csv
import io

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Account, Customer, LedgerEntry, User
from tests.conftest import idem, login


def _other_account_id(app, username="customer002") -> int:
    db = app.state.sessionmaker()
    acct_id = db.scalar(
        select(Account.id).join(Customer).join(User).where(User.username == username).order_by(Account.id)
    )
    db.close()
    return acct_id


def _other_entry_id(app, username="customer002") -> int:
    db = app.state.sessionmaker()
    entry_id = db.scalar(
        select(LedgerEntry.id).join(Account).join(Customer).join(User).where(User.username == username)
    )
    db.close()
    return entry_id


def test_account_list_only_contains_own_accounts(app, customer_client):
    body = customer_client.get("/api/accounts").json()
    db = app.state.sessionmaker()
    own = set(db.scalars(select(Account.id).join(Customer).join(User).where(User.username == "customer001")).all())
    db.close()
    assert {a["id"] for a in body["accounts"]} == own
    for a in body["accounts"]:
        assert a["masked_number"].startswith("•••• ")
        assert "account_number" not in a


def test_cannot_read_other_customers_account(app, customer_client):
    other = _other_account_id(app)
    assert customer_client.get(f"/api/accounts/{other}").status_code == 404
    assert customer_client.get(f"/api/transactions?account_id={other}").status_code == 404
    assert customer_client.get(f"/api/transactions/export.csv?account_id={other}").status_code == 404


def test_cannot_read_other_customers_transaction(app, customer_client):
    assert customer_client.get(f"/api/transactions/{_other_entry_id(app)}").status_code == 404


def test_cannot_debit_other_customers_account(app, customer_client):
    other = _other_account_id(app)
    own = customer_client.get("/api/accounts").json()["accounts"][0]["id"]
    r = customer_client.post(
        "/api/transfers",
        json={"source_account_id": other, "destination_account_id": own, "amount": "10.00"},
        headers={"Idempotency-Key": idem()},
    )
    assert r.status_code == 404
    db = app.state.sessionmaker()
    assert db.scalar(select(LedgerEntry).where(LedgerEntry.txn_type == "transfer_out")) is None
    db.close()


def test_cannot_use_other_customers_beneficiary(app):
    c2 = TestClient(app)
    login(c2, "customer002")
    ben_id = c2.get("/api/beneficiaries").json()["beneficiaries"][0]["id"]
    c1 = TestClient(app)
    login(c1, "customer001")
    own = c1.get("/api/accounts").json()["accounts"][0]["id"]
    r = c1.post("/api/transfers/preview", json={"source_account_id": own, "beneficiary_id": ben_id, "amount": "5.00"})
    assert r.status_code == 404


def test_transaction_history_pagination_and_filters(customer_client):
    page1 = customer_client.get("/api/transactions?page=1&page_size=5").json()
    assert len(page1["items"]) <= 5
    assert page1["total"] >= len(page1["items"])
    if page1["pages"] > 1:
        page2 = customer_client.get("/api/transactions?page=2&page_size=5").json()
        assert {i["id"] for i in page1["items"]}.isdisjoint({i["id"] for i in page2["items"]})
    salaries = customer_client.get("/api/transactions?type=salary&page_size=100").json()
    assert all(i["type"] == "salary" for i in salaries["items"])
    debits = customer_client.get("/api/transactions?direction=debit&page_size=100").json()
    assert all(i["direction"] == "debit" for i in debits["items"])
    assert customer_client.get("/api/transactions?type=bogus").status_code == 422
    assert customer_client.get("/api/transactions?date_from=2026-02-01&date_to=2026-01-01").status_code == 422
    # LIKE wildcards are treated literally.
    assert customer_client.get("/api/transactions?q=%25").status_code == 200


def test_csv_export_contains_only_own_data(app, customer_client):
    r = customer_client.get("/api/transactions/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    db = app.state.sessionmaker()
    own_refs = set(db.scalars(
        select(LedgerEntry.reference).join(Account).join(Customer).join(User).where(User.username == "customer001")
    ).all())
    db.close()
    exported = {row[1] for row in rows[1:]}
    assert exported and exported <= own_refs
    assert len(exported) == len(own_refs)


def test_profile_update_validation(customer_client):
    assert customer_client.patch("/api/profile", json={"email": "not-an-email"}).status_code == 422
    assert customer_client.patch("/api/profile", json={"phone": "12345"}).status_code == 422
    assert customer_client.patch("/api/profile", json={"city": "Atlantis"}).status_code == 422
    assert customer_client.patch("/api/profile", json={"full_name": "Hacker"}).status_code == 422  # not editable
    r = customer_client.patch("/api/profile", json={"phone": "+201012345678", "preferred_name": "Nour"})
    assert r.status_code == 200
    assert r.json()["profile"]["phone"] == "+201012345678"
    assert set(r.json()["changed"]) == {"phone", "preferred_name"}


def test_dashboard_shape(customer_client):
    d = customer_client.get("/api/dashboard").json()
    assert d["currency"] == "EGP"
    assert len(d["monthly"]) == 6
    assert int(d["total_balance_minor"]) == sum(a["balance_minor"] for a in d["accounts"] if a["status"] == "active")
