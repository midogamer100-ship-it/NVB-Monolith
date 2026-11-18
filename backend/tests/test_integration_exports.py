"""Statement dataset contract: correctness, isolation, completeness and core protection."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update

from app.db import utcnow
from app.models import Account, AuditEvent, Customer, LedgerEntry, User
from app.services.integration_exports import subject_for
from tests.conftest import idem, login, make_settings
from tests.integration_support import ALL_SCOPES, bearer, first_account_id, new_token, user_row, write_clients

TOKEN = new_token()
SUMMARY = new_token()
DISCOVER_ONLY = new_token()


@pytest.fixture
def settings(db_url, tmp_path):
    path = tmp_path / "integration-clients.json"
    write_clients(path, {
        "adapter": ([TOKEN], ALL_SCOPES),
        "loans": ([SUMMARY], ["summaries:read"]),
        "discover": ([DISCOVER_ONLY], ["accounts:discover"]),
    })
    return make_settings(db_url, integration_enabled=True, integration_clients_file=str(path),
                         integration_settle_seconds=0, integration_max_concurrent_exports=1,
                         integration_export_queue_timeout_seconds=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def ctx(app, username="customer001"):
    return subject_for(user_row(app, username)), first_account_id(app, username)


def manifest(client, subject, account_id, start, end, token=TOKEN):
    return client.get(f"/internal/v1/accounts/{account_id}/statement-manifest", headers=bearer(token),
                      params={"subject": subject, "period_start": iso(start), "period_end": iso(end)})


def all_entries(client, subject, account_id, start, end, limit=50):
    items, cursor, pages = [], None, 0
    while True:
        params = {"subject": subject, "period_start": iso(start), "period_end": iso(end), "limit": limit}
        if cursor:
            params["cursor"] = cursor
        resp = client.get(f"/internal/v1/accounts/{account_id}/statement-entries", headers=bearer(TOKEN),
                          params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        items += body["items"]
        pages += 1
        if not body["has_more"]:
            return items, pages
        cursor = body["next_cursor"]


def db_signed_sum(app, account_id, before=None, start=None, end=None):
    db = app.state.sessionmaker()
    rows = db.scalars(select(LedgerEntry).where(LedgerEntry.account_id == account_id)).all()
    db.close()
    from app.db import as_utc
    total = 0
    for e in rows:
        p = as_utc(e.posted_at)
        if before is not None and not p < before:
            continue
        if start is not None and not (start <= p < end):
            continue
        total += e.amount_minor if e.direction == "credit" else -e.amount_minor
    return total


NOW = None


def window():
    end = utcnow().replace(microsecond=0) - timedelta(minutes=1)
    return end - timedelta(days=60), end


# --- Correctness -------------------------------------------------------------------------


def test_opening_and_closing_balances_match_ledger(app, client):
    subject, acct = ctx(app)
    start, end = window()
    body = manifest(client, subject, acct, start, end).json()
    assert body["opening_balance_minor"] == db_signed_sum(app, acct, before=start)
    assert body["closing_balance_minor"] == body["opening_balance_minor"] + db_signed_sum(app, acct, start=start, end=end)
    assert body["closing_balance_minor"] == (body["opening_balance_minor"] + body["credit_total_minor"]
                                             - body["debit_total_minor"])
    assert body["boundary"] == "[start,end) UTC"
    assert body["account"]["masked_number"].startswith("•••• ")
    assert "account_number" not in body["account"]
    assert body["account"]["holder_name"]


def test_closing_is_historical_not_current_balance(app, client, customer_client):
    subject, acct = ctx(app)
    start, end = window()
    before = manifest(client, subject, acct, start, end).json()
    resp = customer_client.post(f"/api/accounts/{acct}/deposit", headers={"Idempotency-Key": idem()},
                                json={"amount": "123.45", "description": "after period"})
    assert resp.status_code == 201, resp.text
    after = manifest(client, subject, acct, start, end).json()
    assert after["closing_balance_minor"] == before["closing_balance_minor"]
    assert after["dataset_id"] == before["dataset_id"]


def test_consecutive_periods_chain(app, client):
    subject, acct = ctx(app)
    start, end = window()
    mid = start + timedelta(days=17, hours=5)
    a = manifest(client, subject, acct, start, mid).json()
    b = manifest(client, subject, acct, mid, end).json()
    whole = manifest(client, subject, acct, start, end).json()
    assert a["closing_balance_minor"] == b["opening_balance_minor"]
    assert a["entry_count"] + b["entry_count"] == whole["entry_count"]
    assert b["closing_balance_minor"] == whole["closing_balance_minor"]


def test_empty_period_before_account_opened(app, client):
    subject, acct = ctx(app)
    start = datetime(2001, 1, 1, tzinfo=UTC)
    body = manifest(client, subject, acct, start, start + timedelta(days=31)).json()
    assert body["entry_count"] == 0
    assert body["opening_balance_minor"] == body["closing_balance_minor"] == 0
    assert body["account_opened_after_period"] is True


def test_account_opened_during_period(app, client):
    subject, acct = ctx(app)
    db = app.state.sessionmaker()
    opened = db.scalar(select(Account.opened_at).where(Account.id == acct))
    db.close()
    from app.db import as_utc
    opened = as_utc(opened)
    body = manifest(client, subject, acct, opened - timedelta(days=5), opened + timedelta(days=5)).json()
    assert body["account_opened_in_period"] is True
    assert body["opening_balance_minor"] == 0


def test_entries_reproduce_manifest_with_stable_order(app, client):
    subject, acct = ctx(app)
    start, end = window()
    m = manifest(client, subject, acct, start, end).json()
    items, pages = all_entries(client, subject, acct, start, end, limit=7)
    assert pages > 1
    assert len(items) == m["entry_count"]
    assert len({i["entry_id"] for i in items}) == len(items)
    keys = [(i["posted_at"], i["entry_id"]) for i in items]
    assert keys == sorted(keys)
    credits = sum(i["amount_minor"] for i in items if i["direction"] == "credit")
    debits = sum(i["amount_minor"] for i in items if i["direction"] == "debit")
    assert (credits, debits) == (m["credit_total_minor"], m["debit_total_minor"])
    assert all(isinstance(i["amount_minor"], int) for i in items)


def test_period_boundaries_are_half_open_utc(app, client):
    subject, acct = ctx(app)
    t = datetime(2020, 6, 30, 21, 0, 0, tzinfo=UTC)  # 2020-07-01 00:00 Africa/Cairo (UTC+3 in summer)
    db = app.state.sessionmaker()
    db.execute(insert(LedgerEntry), [
        dict(account_id=acct, reference="BOUNDARY1", direction="credit", txn_type="deposit", category="Test",
             amount_minor=100, balance_after_minor=0, description="at start", counterparty="", posted_at=t),
        dict(account_id=acct, reference="BOUNDARY2", direction="credit", txn_type="deposit", category="Test",
             amount_minor=200, balance_after_minor=0, description="just before end", counterparty="",
             posted_at=t + timedelta(days=1) - timedelta(microseconds=1)),
        dict(account_id=acct, reference="BOUNDARY3", direction="credit", txn_type="deposit", category="Test",
             amount_minor=400, balance_after_minor=0, description="at end", counterparty="",
             posted_at=t + timedelta(days=1)),
    ])
    db.execute(update(Account).where(Account.id == acct).values(balance_minor=Account.balance_minor + 700))
    db.commit()
    db.close()
    body = manifest(client, subject, acct, t, t + timedelta(days=1)).json()
    assert body["entry_count"] == 2
    assert body["credit_total_minor"] == 300
    items, _ = all_entries(client, subject, acct, t, t + timedelta(days=1))
    assert [i["reference"] for i in items] == ["BOUNDARY1", "BOUNDARY2"]


def test_tied_timestamps_order_by_id(app, client):
    subject, acct = ctx(app)
    t = datetime(2019, 3, 1, 12, 0, tzinfo=UTC)
    db = app.state.sessionmaker()
    db.execute(insert(LedgerEntry), [
        dict(account_id=acct, reference=f"TIE{n}", direction="credit", txn_type="deposit", category="Test",
             amount_minor=10 + n, balance_after_minor=0, description="tie", counterparty="", posted_at=t)
        for n in range(5)
    ])
    db.execute(update(Account).where(Account.id == acct).values(balance_minor=Account.balance_minor + 60))
    db.commit()
    db.close()
    items, _ = all_entries(client, subject, acct, t, t + timedelta(seconds=1), limit=2)
    assert [i["reference"] for i in items] == [f"TIE{n}" for n in range(5)]
    ids = [i["entry_id"] for i in items]
    assert ids == sorted(ids)


def test_more_than_ten_thousand_entries_without_truncation(app, client):
    subject, acct = ctx(app)
    t0 = datetime(2018, 1, 1, tzinfo=UTC)
    n = 10_050
    rows = [dict(account_id=acct, reference=f"BULK{i:06d}", direction="credit", txn_type="deposit",
                 category="Test", amount_minor=1, balance_after_minor=0, description="bulk", counterparty="",
                 posted_at=t0 + timedelta(seconds=i // 3)) for i in range(n)]
    db = app.state.sessionmaker()
    for i in range(0, n, 2000):
        db.execute(insert(LedgerEntry), rows[i:i + 2000])
    db.execute(update(Account).where(Account.id == acct).values(balance_minor=Account.balance_minor + n))
    db.commit()
    db.close()
    end = t0 + timedelta(days=1)
    m = manifest(client, subject, acct, t0, end).json()
    assert m["entry_count"] == n
    items, pages = all_entries(client, subject, acct, t0, end, limit=1000)
    assert len(items) == n and pages == 11
    assert len({i["entry_id"] for i in items}) == n


def test_concurrent_posting_between_pages_does_not_change_closed_period(app, client, customer_client):
    subject, acct = ctx(app)
    start, end = window()
    m1 = manifest(client, subject, acct, start, end).json()
    first = client.get(f"/internal/v1/accounts/{acct}/statement-entries", headers=bearer(TOKEN),
                       params={"subject": subject, "period_start": iso(start), "period_end": iso(end), "limit": 5}).json()
    customer_client.post(f"/api/accounts/{acct}/deposit", headers={"Idempotency-Key": idem()},
                         json={"amount": "10.00", "description": "concurrent"})
    rest, _ = all_entries(client, subject, acct, start, end, limit=5)
    m2 = manifest(client, subject, acct, start, end).json()
    assert m1["dataset_id"] == m2["dataset_id"]
    assert first["items"] == rest[:5]
    assert len(rest) == m1["entry_count"]


# --- Isolation -------------------------------------------------------------------------


def test_other_customers_account_is_not_found(app, client):
    subject, _ = ctx(app, "customer001")
    _, other_acct = ctx(app, "customer002")
    start, end = window()
    resp = manifest(client, subject, other_acct, start, end)
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "account_not_found"
    resp = client.get(f"/internal/v1/accounts/{other_acct}/statement-entries", headers=bearer(TOKEN),
                      params={"subject": subject, "period_start": iso(start), "period_end": iso(end)})
    assert resp.status_code == 404
    assert manifest(client, subject, 999_999, start, end).status_code == 404


def test_tampered_or_reused_subject_is_rejected(app, client):
    user = user_row(app, "customer001")
    _, acct = ctx(app)
    start, end = window()
    for bad in (f"nvb-user:{user.id}:1", "nvb-user:999999:1"):
        assert manifest(client, bad, acct, start, end).status_code == 404
    assert manifest(client, "customer001", acct, start, end).status_code == 422


def test_suspended_subject_is_rejected(app, client):
    subject, acct = ctx(app)
    db = app.state.sessionmaker()
    db.execute(update(User).where(User.username == "customer001").values(is_active=False))
    db.commit()
    db.close()
    start, end = window()
    assert manifest(client, subject, acct, start, end).status_code == 404


def test_summary_scope_reads_manifest_but_not_entries(app, client):
    subject, acct = ctx(app)
    start, end = window()
    assert manifest(client, subject, acct, start, end, token=SUMMARY).status_code == 200
    resp = client.get(f"/internal/v1/accounts/{acct}/statement-entries", headers=bearer(SUMMARY),
                      params={"subject": subject, "period_start": iso(start), "period_end": iso(end)})
    assert resp.status_code == 403


# --- Validation and core protection ------------------------------------------------------


def test_period_not_settled_is_rejected(db_url, app, tmp_path):
    path = tmp_path / "c.json"
    write_clients(path, {"adapter": ([TOKEN], ALL_SCOPES)})
    strict = TestClient(__import__("app.main", fromlist=["create_app"]).create_app(
        make_settings(db_url, integration_enabled=True, integration_clients_file=str(path),
                      integration_settle_seconds=300)))
    subject, acct = ctx(app)
    now = utcnow()
    resp = manifest(strict, subject, acct, now - timedelta(days=3), now - timedelta(seconds=60))
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "period_not_settled"
    assert manifest(strict, subject, acct, now - timedelta(days=3), now - timedelta(seconds=600)).status_code == 200


def test_invalid_periods(app, client):
    subject, acct = ctx(app)
    start, end = window()
    assert manifest(client, subject, acct, end, start).status_code == 422
    assert manifest(client, subject, acct, end - timedelta(days=500), end).status_code == 422
    resp = client.get(f"/internal/v1/accounts/{acct}/statement-manifest", headers=bearer(TOKEN),
                      params={"subject": subject, "period_start": "2026-01-01T00:00:00",
                              "period_end": "2026-02-01T00:00:00"})
    assert resp.status_code == 422


def test_invalid_cursor(app, client):
    subject, acct = ctx(app)
    start, end = window()
    resp = client.get(f"/internal/v1/accounts/{acct}/statement-entries", headers=bearer(TOKEN),
                      params={"subject": subject, "period_start": iso(start), "period_end": iso(end),
                              "cursor": "@@not-a-cursor"})
    assert resp.status_code == 422


def test_page_size_is_capped(app, client):
    subject, acct = ctx(app)
    start, end = window()
    body = client.get(f"/internal/v1/accounts/{acct}/statement-entries", headers=bearer(TOKEN),
                      params={"subject": subject, "period_start": iso(start), "period_end": iso(end),
                              "limit": 1_000_000}).json()
    assert len(body["items"]) <= 1000


def test_export_capacity_returns_429(app, client):
    subject, acct = ctx(app)
    start, end = window()
    sem = app.state.integration.exports
    assert sem.acquire(timeout=1)
    try:
        resp = manifest(client, subject, acct, start, end)
        assert resp.status_code == 429 and resp.headers["Retry-After"]
    finally:
        sem.release()
    assert manifest(client, subject, acct, start, end).status_code == 200


def test_reconciliation_failure_fails_closed(app, client):
    subject, acct = ctx(app)
    db = app.state.sessionmaker()
    db.execute(update(Account).where(Account.id == acct).values(balance_minor=Account.balance_minor + 1))
    db.commit()
    db.close()
    start, end = window()
    resp = manifest(client, subject, acct, start, end)
    assert resp.status_code == 500 and resp.json()["error"]["code"] == "ledger_reconciliation_failed"


def test_manifest_is_audited_without_sensitive_data(app, client):
    subject, acct = ctx(app)
    start, end = window()
    manifest(client, subject, acct, start, end)
    db = app.state.sessionmaker()
    ev = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "integration.statement_manifest"))
    number = db.scalar(select(Account.account_number).where(Account.id == acct))
    db.close()
    assert ev is not None and ev.details["client_id"] == "adapter"
    assert number not in str(ev.details)


# --- Discovery -----------------------------------------------------------------------


def test_discovery_paginates_and_excludes_ineligible(app, client):
    db = app.state.sessionmaker()
    db.execute(update(User).where(User.username == "customer002").values(is_active=False))
    db.commit()
    expected = set(db.scalars(
        select(Account.id).join(Customer).join(User)
        .where(User.is_active.is_(True), User.is_load_test.is_(False), User.role == "customer",
               Account.status == "active")).all())
    db.close()
    seen, after = [], 0
    while True:
        body = client.get("/internal/v1/discovery/statement-accounts", headers=bearer(DISCOVER_ONLY),
                          params={"after_account_id": after, "limit": 2}).json()
        seen += body["items"]
        if not body["has_more"]:
            break
        after = body["next_after_account_id"]
    assert {i["account_id"] for i in seen} == expected
    assert all(i["subject"].startswith("nvb-user:") for i in seen)
    assert all("account_number" not in i for i in seen)


def test_discovery_requires_scope(app, client):
    assert client.get("/internal/v1/discovery/statement-accounts", headers=bearer(SUMMARY)).status_code == 403
