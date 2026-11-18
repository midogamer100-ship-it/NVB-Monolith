"""Statement dataset consistency (contract statement-v2).

The manifest carries a SHA-256 over every entry of the period, computed in one snapshot.
These tests prove that a caller who recomputes that digest rejects datasets that changed
between the manifest and the pages, including changes that keep count and totals equal.
PostgreSQL-only tests (snapshot isolation, read-only transaction, concurrent commits) are
skipped on SQLite: SQLite cannot demonstrate them.
"""

import hashlib
import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, insert, text, update

from app.db import utcnow
from app.models import Account, Customer, LedgerEntry
from app.services import integration_exports as ix
from tests.conftest import idem, make_settings
from tests.integration_support import ALL_SCOPES, bearer, first_account_id, new_token, user_row, write_clients

TOKEN = new_token()
T0 = datetime(2019, 3, 1, tzinfo=UTC)
T1 = T0 + timedelta(days=31)


@pytest.fixture
def settings(db_url, tmp_path):
    path = tmp_path / "integration-clients.json"
    write_clients(path, {"adapter": ([TOKEN], ALL_SCOPES)})
    return make_settings(db_url, integration_enabled=True, integration_clients_file=str(path),
                         integration_settle_seconds=0, integration_max_statement_entries=500)


def iso(dt):
    return dt.astimezone(UTC).isoformat()


def ctx(app, username="customer001"):
    return ix.subject_for(user_row(app, username)), first_account_id(app, username)


def params(subject, start=T0, end=T1, **extra):
    return {"subject": subject, "period_start": iso(start), "period_end": iso(end), **extra}


def get_manifest(client, subject, acct, start=T0, end=T1):
    r = client.get(f"/internal/v1/accounts/{acct}/statement-manifest", headers=bearer(TOKEN),
                   params=params(subject, start, end))
    assert r.status_code == 200, r.text
    return r.json()


def page(client, subject, acct, cursor=None, limit=4, start=T0, end=T1):
    extra = {"limit": limit, **({"cursor": cursor} if cursor else {})}
    r = client.get(f"/internal/v1/accounts/{acct}/statement-entries", headers=bearer(TOKEN),
                   params=params(subject, start, end, **extra))
    assert r.status_code == 200, r.text
    return r.json()


def caller_digest(entries) -> str:
    """What a caller computes from the JSON it received (same canonical encoding)."""
    h = hashlib.sha256()
    for e in entries:
        h.update(ix.canonical_entry_line(
            entry_id=e["entry_id"], posted_at_us=e["posted_at_us"], direction=e["direction"],
            amount_minor=e["amount_minor"], balance_after_minor=e["balance_after_minor"],
            reference=e["reference"], txn_type=e["type"], category=e["category"],
            description=e["description"], counterparty=e["counterparty"]))
    return h.hexdigest()


def add_entries(app, acct, rows):
    """rows: (offset_seconds, direction, amount_minor, description). Keeps the balance reconciled."""
    db = app.state.sessionmaker()
    delta = 0
    for i, (offset, direction, amount, description) in enumerate(rows):
        db.execute(insert(LedgerEntry).values(
            account_id=acct, reference=f"CONS{offset:07d}{i:03d}", direction=direction, txn_type="deposit",
            category="Test", amount_minor=amount, balance_after_minor=0, description=description,
            counterparty="", posted_at=T0 + timedelta(seconds=offset)))
        delta += amount if direction == "credit" else -amount
    db.execute(update(Account).where(Account.id == acct).values(balance_minor=Account.balance_minor + delta))
    db.commit()
    db.close()


def seed_period(app, acct, n=10):
    add_entries(app, acct, [(i * 60, "credit" if i % 3 else "debit", 100 + i, f"row {i}") for i in range(n)])


def all_pages(client, subject, acct, limit=4):
    items, cursor = [], None
    while True:
        p = page(client, subject, acct, cursor, limit)
        items += p["items"]
        if not p["has_more"]:
            return items
        cursor = p["next_cursor"]


# --- Digest covers every entry ------------------------------------------------------------


def test_caller_digest_reproduces_manifest(app, client):
    subject, acct = ctx(app)
    seed_period(app, acct)
    m = get_manifest(client, subject, acct)
    assert m["dataset_version"] == "statement-v2" and len(m["entries_sha256"]) == 64
    items = all_pages(client, subject, acct)
    assert len(items) == m["entry_count"] == 10
    assert caller_digest(items) == m["entries_sha256"]
    assert caller_digest(items[:-1]) != m["entries_sha256"]            # a missing row is detected
    assert caller_digest(list(reversed(items))) != m["entries_sha256"]  # so is a different order


def test_empty_period_has_stable_empty_digest(app, client):
    subject, acct = ctx(app)
    m = get_manifest(client, subject, acct)
    assert m["entry_count"] == 0 and m["first_entry_id"] is None
    assert m["entries_sha256"] == hashlib.sha256(b"").hexdigest()
    assert m["opening_balance_minor"] == m["closing_balance_minor"]


def test_non_ascii_text_is_hashed_consistently(app, client):
    subject, acct = ctx(app)
    add_entries(app, acct, [(10, "credit", 500, "تحويل راتب – café ✓"), (10, "debit", 200, 'quote " and \\ slash')])
    m = get_manifest(client, subject, acct)
    assert caller_digest(all_pages(client, subject, acct)) == m["entries_sha256"]


def test_backdated_entry_committed_between_manifest_and_pages_is_detected(app, client):
    """The core permits a row to become visible with an older posted_at (posted_at is taken
    before the row lock; the seed also back-dates). Count/sum/max-id checks cannot see where
    it landed; the content digest does."""
    subject, acct = ctx(app)
    seed_period(app, acct)
    m1 = get_manifest(client, subject, acct)
    first = page(client, subject, acct, limit=4)
    # Lands BEFORE the rows already paged (offset 30 s < first page) - a keyset cursor skips it.
    add_entries(app, acct, [(30, "credit", 777, "back-dated")])
    rest, cursor = [], first["next_cursor"]
    while cursor:
        p = page(client, subject, acct, cursor, 4)
        rest += p["items"]
        cursor = p["next_cursor"] if p["has_more"] else None
    received = first["items"] + rest
    assert len(received) == m1["entry_count"]              # the row count alone still "matches"
    assert caller_digest(received) == m1["entries_sha256"]  # paged set == manifest snapshot
    m2 = get_manifest(client, subject, acct)
    assert m2["dataset_id"] != m1["dataset_id"]             # ...and the re-read rejects the dataset
    assert m2["entry_count"] == m1["entry_count"] + 1


def test_backdated_entry_after_paged_position_changes_digest(app, client):
    subject, acct = ctx(app)
    seed_period(app, acct)
    m1 = get_manifest(client, subject, acct)
    first = page(client, subject, acct, limit=4)
    add_entries(app, acct, [(500, "credit", 5, "lands in a later page")])
    rest, cursor = [], first["next_cursor"]
    while cursor:
        p = page(client, subject, acct, cursor, 4)
        rest += p["items"]
        cursor = p["next_cursor"] if p["has_more"] else None
    assert caller_digest(first["items"] + rest) != m1["entries_sha256"]


def test_content_change_with_identical_count_and_totals_is_detected(app, client):
    """v1 hashed count/totals/first/last id only. An in-place edit or a swap of two amounts
    keeps all of those equal; v2 must still produce a different dataset."""
    subject, acct = ctx(app)
    seed_period(app, acct)
    m1 = get_manifest(client, subject, acct)
    items = all_pages(client, subject, acct)
    a, b = items[4], items[5]                       # both credits (i % 3 != 0)
    assert a["direction"] == b["direction"] == "credit"
    db = app.state.sessionmaker()
    db.execute(update(LedgerEntry).where(LedgerEntry.id == a["entry_id"]).values(amount_minor=b["amount_minor"]))
    db.execute(update(LedgerEntry).where(LedgerEntry.id == b["entry_id"]).values(amount_minor=a["amount_minor"]))
    db.execute(update(LedgerEntry).where(LedgerEntry.id == items[0]["entry_id"]).values(description="edited"))
    db.commit()
    db.close()
    m2 = get_manifest(client, subject, acct)
    for key in ("entry_count", "credit_total_minor", "debit_total_minor", "opening_balance_minor",
                "closing_balance_minor", "first_entry_id", "last_entry_id"):
        assert m2[key] == m1[key]
    assert m2["entries_sha256"] != m1["entries_sha256"] and m2["dataset_id"] != m1["dataset_id"]
    assert caller_digest(items) != m2["entries_sha256"]


def test_delete_and_reinsert_same_amount_is_detected(app, client):
    subject, acct = ctx(app)
    seed_period(app, acct)
    m1 = get_manifest(client, subject, acct)
    victim = all_pages(client, subject, acct)[5]
    db = app.state.sessionmaker()
    db.execute(delete(LedgerEntry).where(LedgerEntry.id == victim["entry_id"]))
    db.execute(insert(LedgerEntry).values(
        account_id=acct, reference="REPLACED", direction=victim["direction"], txn_type="deposit",
        category="Test", amount_minor=victim["amount_minor"], balance_after_minor=0, description="replacement",
        counterparty="", posted_at=datetime.fromisoformat(victim["posted_at"])))
    db.commit()
    db.close()
    m2 = get_manifest(client, subject, acct)
    assert m2["entry_count"] == m1["entry_count"] and m2["credit_total_minor"] == m1["credit_total_minor"]
    assert m2["dataset_id"] != m1["dataset_id"]


def test_change_before_period_changes_opening_and_dataset_id(app, client):
    subject, acct = ctx(app)
    seed_period(app, acct)
    m1 = get_manifest(client, subject, acct)
    add_entries(app, acct, [(-3600, "credit", 900, "before the period")])
    m2 = get_manifest(client, subject, acct)
    assert m2["entries_sha256"] == m1["entries_sha256"]
    assert m2["opening_balance_minor"] == m1["opening_balance_minor"] + 900
    assert m2["dataset_id"] != m1["dataset_id"]


def test_manifest_above_entry_limit_is_rejected_not_truncated(app, client):
    subject, acct = ctx(app)
    add_entries(app, acct, [(i, "credit", 1, "bulk") for i in range(501)])
    r = client.get(f"/internal/v1/accounts/{acct}/statement-manifest", headers=bearer(TOKEN),
                   params=params(subject))
    assert r.status_code == 422 and r.json()["error"]["code"] == "dataset_too_large"


def test_tied_timestamps_are_digested_in_id_order(app, client):
    subject, acct = ctx(app)
    add_entries(app, acct, [(5, "credit", 10 + i, f"tie {i}") for i in range(7)])
    m = get_manifest(client, subject, acct)
    items = all_pages(client, subject, acct, limit=2)
    assert [e["entry_id"] for e in items] == sorted(e["entry_id"] for e in items)
    assert len({e["posted_at_us"] for e in items}) == 1
    assert caller_digest(items) == m["entries_sha256"]


# --- PostgreSQL only: snapshot semantics ---------------------------------------------------


def _pg(app):
    if app.state.engine.dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL (snapshot isolation cannot be shown on SQLite)")


def test_pg_manifest_transaction_is_repeatable_read_and_read_only(app):
    _pg(app)
    db = app.state.sessionmaker()
    try:
        ix.begin_snapshot(db)
        assert db.execute(text("SHOW transaction_isolation")).scalar() == "repeatable read"
        assert db.execute(text("SHOW transaction_read_only")).scalar() == "on"
        with pytest.raises(Exception, match="read-only"):
            db.execute(text("UPDATE accounts SET balance_minor = balance_minor"))
    finally:
        db.rollback()
        db.close()


def test_pg_manifest_ignores_commits_made_after_its_snapshot_started(app):
    """A posting that commits while the manifest is being computed must not appear in only
    some of its queries (count vs. digest pass vs. balance reconciliation)."""
    _pg(app)
    subject, acct = ctx(app)
    seed_period(app, acct)
    db = app.state.sessionmaker()
    try:
        ix.begin_snapshot(db)
        user, customer = ix.customer_for_subject(db, subject)   # first statement fixes the snapshot
        account = ix.owned_account(db, customer, acct)
        add_entries(app, acct, [(120, "credit", 4242, "committed mid-manifest")])  # other connection, committed
        inside = ix.statement_manifest(db, customer, account, ix.Period(T0, T1), now=utcnow())
        assert inside["entry_count"] == 10            # snapshot: consistent, no reconciliation error
    finally:
        db.rollback()
        db.close()
    db = app.state.sessionmaker()
    try:
        ix.begin_snapshot(db)
        user, customer = ix.customer_for_subject(db, subject)
        after = ix.statement_manifest(db, customer, ix.owned_account(db, customer, acct), ix.Period(T0, T1),
                                      now=utcnow())
    finally:
        db.rollback()
        db.close()
    assert after["entry_count"] == 11 and after["dataset_id"] != inside["dataset_id"]
    assert isinstance(customer, Customer)


def test_pg_concurrent_postings_never_yield_an_accepted_inconsistent_dataset(app, client, customer_client):
    """Real deposits commit from another thread while datasets are exported. Every export that
    passes the caller-side verification must be internally exact; the rest are rejected."""
    _pg(app)
    subject, acct = ctx(app)
    stop = threading.Event()
    posted = []

    def poster():
        while not stop.is_set():
            r = customer_client.post(f"/api/accounts/{acct}/deposit", headers={"Idempotency-Key": idem()},
                                     json={"amount": "1.00", "description": "concurrent"})
            posted.append(r.status_code)

    t = threading.Thread(target=poster, daemon=True)
    t.start()
    accepted = rejected = 0
    try:
        for _ in range(25):
            end = utcnow()
            start = end - timedelta(minutes=10)
            m1 = get_manifest(client, subject, acct, start, end)
            if m1["entry_count"] > 400:
                break
            items, cursor = [], None
            while True:
                p = page(client, subject, acct, cursor, 7, start, end)
                items += p["items"]
                if not p["has_more"]:
                    break
                cursor = p["next_cursor"]
            m2 = get_manifest(client, subject, acct, start, end)
            if caller_digest(items) == m1["entries_sha256"] and m2["dataset_id"] == m1["dataset_id"]:
                accepted += 1
                credits = sum(e["amount_minor"] for e in items if e["direction"] == "credit")
                debits = sum(e["amount_minor"] for e in items if e["direction"] == "debit")
                assert len(items) == m1["entry_count"]
                assert (credits, debits) == (m1["credit_total_minor"], m1["debit_total_minor"])
                assert m1["opening_balance_minor"] + credits - debits == m1["closing_balance_minor"]
            else:
                rejected += 1
    finally:
        stop.set()
        t.join(timeout=30)
    assert posted and set(posted) == {201}
    # Postings made after ``end`` carry a later posted_at and stay outside the period, so
    # most exports are accepted; an export is rejected only when a posting was in flight at
    # ``end``. Either way no accepted dataset may be inexact (asserted above). Deterministic
    # rejection is covered by the back-dated tests.
    assert accepted >= 1 and accepted + rejected >= 1
