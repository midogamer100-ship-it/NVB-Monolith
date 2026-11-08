"""Transfer correctness: atomicity, funds checks, idempotency, concurrency."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.models import Account, LedgerEntry, Transfer
from app.services import transfers as transfer_service
from tests.conftest import idem, login


def balances(app) -> dict[int, int]:
    db = app.state.sessionmaker()
    out = dict(db.execute(select(Account.id, Account.balance_minor)).all())
    db.close()
    return out


def total_money(app) -> int:
    return sum(balances(app).values())


def setup_pair(client: TestClient) -> tuple[dict, dict]:
    src = client.get("/api/accounts").json()["accounts"][0]
    ben = client.get("/api/beneficiaries").json()["beneficiaries"][0]
    return src, ben


def post_transfer(client, src_id, ben_id, amount, key=None, description="Test transfer"):
    return client.post(
        "/api/transfers",
        json={"source_account_id": src_id, "beneficiary_id": ben_id, "amount": amount, "description": description},
        headers={"Idempotency-Key": key or idem()},
    )


def test_successful_transfer_moves_money_and_writes_ledger(app, customer_client):
    src, ben = setup_pair(customer_client)
    before = balances(app)
    total_before = sum(before.values())
    r = post_transfer(customer_client, src["id"], ben["id"], "125.50")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["reference"].startswith("NVB")
    after = balances(app)
    assert after[src["id"]] == before[src["id"]] - 12550
    assert sum(after.values()) == total_before  # money is conserved
    db = app.state.sessionmaker()
    t = db.scalar(select(Transfer).where(Transfer.reference == body["reference"]))
    entries = db.scalars(select(LedgerEntry).where(LedgerEntry.transfer_id == t.id)).all()
    assert sorted(e.direction for e in entries) == ["credit", "debit"]
    assert all(e.amount_minor == 12550 for e in entries)
    debit = next(e for e in entries if e.direction == "debit")
    assert debit.balance_after_minor == after[src["id"]]
    db.close()
    # Receipt is retrievable by reference.
    assert customer_client.get(f"/api/transfers/{body['reference']}").json()["status"] == "completed"


def test_preview_does_not_move_money(app, customer_client):
    src, ben = setup_pair(customer_client)
    before = balances(app)
    r = customer_client.post("/api/transfers/preview",
                             json={"source_account_id": src["id"], "beneficiary_id": ben["id"], "amount": "10.00"})
    assert r.status_code == 200
    assert r.json()["sufficient_funds"] is True
    assert balances(app) == before


@pytest.mark.parametrize("amount", ["0", "-5.00", "10.001", "abc", "NaN", "Infinity", "1e3000", "99999999.00"])
def test_invalid_amounts_rejected(app, customer_client, amount):
    src, ben = setup_pair(customer_client)
    before = balances(app)
    r = post_transfer(customer_client, src["id"], ben["id"], amount)
    assert r.status_code == 422, (amount, r.text)
    assert balances(app) == before


def test_float_amount_rejected(customer_client):
    src, ben = setup_pair(customer_client)
    r = customer_client.post("/api/transfers", json={"source_account_id": src["id"], "beneficiary_id": ben["id"],
                                                     "amount": 10.5}, headers={"Idempotency-Key": idem()})
    assert r.status_code == 422


def test_same_account_rejected(customer_client):
    src = customer_client.get("/api/accounts").json()["accounts"][0]
    r = customer_client.post("/api/transfers", json={"source_account_id": src["id"], "destination_account_id": src["id"],
                                                     "amount": "1.00"}, headers={"Idempotency-Key": idem()})
    assert r.status_code == 422


def test_insufficient_funds_moves_nothing_and_is_persisted(app, customer_client):
    src, ben = setup_pair(customer_client)
    before = balances(app)
    too_much = src["balance_minor"] + 1
    amount = f"{too_much // 100}.{too_much % 100:02d}"
    key = idem()
    r = post_transfer(customer_client, src["id"], ben["id"], amount, key=key)
    assert r.status_code == 422
    assert r.json()["status"] == "failed"
    assert r.json()["failure_reason"] == "insufficient_funds"
    assert balances(app) == before
    db = app.state.sessionmaker()
    t = db.scalar(select(Transfer).where(Transfer.idempotency_key == key))
    assert t.status == "failed"
    assert db.scalar(select(func.count()).select_from(LedgerEntry).where(LedgerEntry.transfer_id == t.id)) == 0
    db.close()
    # Retrying the same failed request replays the same outcome.
    again = post_transfer(customer_client, src["id"], ben["id"], amount, key=key)
    assert again.json()["reference"] == r.json()["reference"]


def test_exact_balance_transfer_allowed_to_zero(app, customer_client):
    src, ben = setup_pair(customer_client)
    amt = src["balance_minor"]
    r = post_transfer(customer_client, src["id"], ben["id"], f"{amt // 100}.{amt % 100:02d}")
    assert r.status_code == 201
    assert balances(app)[src["id"]] == 0


def test_idempotency_key_required(customer_client):
    src, ben = setup_pair(customer_client)
    r = customer_client.post("/api/transfers", json={"source_account_id": src["id"], "beneficiary_id": ben["id"],
                                                     "amount": "1.00"})
    assert r.status_code == 400
    r = customer_client.post("/api/transfers", json={"source_account_id": src["id"], "beneficiary_id": ben["id"],
                                                     "amount": "1.00"}, headers={"Idempotency-Key": "short"})
    assert r.status_code == 400


def test_idempotent_retry_does_not_double_debit(app, customer_client):
    src, ben = setup_pair(customer_client)
    before = balances(app)[src["id"]]
    key = idem()
    first = post_transfer(customer_client, src["id"], ben["id"], "50.00", key=key)
    second = post_transfer(customer_client, src["id"], ben["id"], "50.00", key=key)
    assert first.status_code == 201 and second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert first.json()["reference"] == second.json()["reference"]
    assert balances(app)[src["id"]] == before - 5000


def test_idempotency_key_reuse_with_different_payload_conflicts(app, customer_client):
    src, ben = setup_pair(customer_client)
    key = idem()
    assert post_transfer(customer_client, src["id"], ben["id"], "5.00", key=key).status_code == 201
    before = balances(app)
    r = post_transfer(customer_client, src["id"], ben["id"], "6.00", key=key)
    assert r.status_code == 409
    assert balances(app) == before


def test_transfer_is_atomic_when_credit_fails(app, customer_client, monkeypatch):
    src, ben = setup_pair(customer_client)
    before = balances(app)

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated crash between debit and credit")

    monkeypatch.setattr(transfer_service, "_post_credit", boom)
    r = post_transfer(customer_client, src["id"], ben["id"], "20.00")
    assert r.status_code == 500
    assert "simulated" not in r.text  # internals are not leaked to the client
    assert balances(app) == before
    db = app.state.sessionmaker()
    assert db.scalar(select(func.count()).select_from(Transfer)) == 0
    assert db.scalar(select(func.count()).select_from(LedgerEntry).where(LedgerEntry.transfer_id.is_not(None))) == 0
    db.close()


def test_concurrent_transfers_never_overdraw(app):
    """Many parallel transfers from one account: never negative, money conserved."""
    c = TestClient(app)
    login(c, "loadtest001")
    src, ben = setup_pair(c)
    # Set a known small balance first: exactly 100.00 EGP.
    db = app.state.sessionmaker()
    db.execute(update(Account).where(Account.id == src["id"]).values(balance_minor=10000))
    db.commit()
    db.close()
    total_before = total_money(app)

    def attempt(_):
        cl = TestClient(app)
        cl.cookies.update(c.cookies)
        cl.headers["X-CSRF-Token"] = c.headers["X-CSRF-Token"]
        return post_transfer(cl, src["id"], ben["id"], "30.00").status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(attempt, range(10)))
    assert codes.count(201) == 3  # 3 x 30 = 90 <= 100; the 4th would overdraw
    assert codes.count(422) == 7
    final = balances(app)
    assert final[src["id"]] == 1000
    assert min(final.values()) >= 0
    assert total_money(app) == total_before


def test_concurrent_duplicate_requests_execute_once(app):
    c = TestClient(app)
    login(c, "loadtest002")
    src, ben = setup_pair(c)
    before = balances(app)[src["id"]]
    key = idem()

    def attempt(_):
        cl = TestClient(app)
        cl.cookies.update(c.cookies)
        cl.headers["X-CSRF-Token"] = c.headers["X-CSRF-Token"]
        r = post_transfer(cl, src["id"], ben["id"], "77.00", key=key)
        return r.status_code, r.json()["reference"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert len({ref for _, ref in results}) == 1
    assert sorted(code for code, _ in results).count(201) == 1
    assert balances(app)[src["id"]] == before - 7700
    db = app.state.sessionmaker()
    assert db.scalar(select(func.count()).select_from(Transfer).where(Transfer.idempotency_key == key)) == 1
    db.close()


def test_opposite_direction_concurrent_transfers_do_not_deadlock(app):
    a, b = TestClient(app), TestClient(app)
    login(a, "loadtest001")
    login(b, "loadtest003")  # loadtest003's beneficiary ring wraps to loadtest001
    src_a, ben_a = setup_pair(a)
    src_b, ben_b = setup_pair(b)
    total_before = total_money(app)

    def run(args):
        client, src, ben = args
        return post_transfer(client, src["id"], ben["id"], "1.00").status_code

    jobs = [(a, src_a, ben_a), (b, src_b, ben_b)] * 5
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(run, jobs))
    assert all(code == 201 for code in codes)
    assert total_money(app) == total_before
