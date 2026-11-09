import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import TxnDetailModal from "../components/TxnDetailModal";
import TxnList from "../components/TxnList";
import { Badge, EmptyState, ErrorState, LoadingBlock, Pagination, SkeletonRows } from "../components/ui";
import { ApiError, toQuery } from "../lib/api";
import { formatDate, formatMinor, titleCase } from "../lib/format";
import type { Account, TxnPage } from "../lib/types";
import { useApi } from "../lib/useApi";

export default function AccountDetail() {
  const { id } = useParams();
  const accountId = Number(id);
  const valid = Number.isInteger(accountId) && accountId > 0;
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number | null>(null);
  const acct = useApi<Account>(valid ? `/api/accounts/${accountId}` : null);
  const txns = useApi<TxnPage>(valid ? `/api/transactions${toQuery({ account_id: accountId, page, page_size: 15 })}` : null);

  if (!valid || (acct.error instanceof ApiError && acct.error.status === 404)) {
    return (
      <div className="card">
        <EmptyState
          title="Account not found"
          message="This account doesn't exist or isn't one of yours."
          action={
            <Link to="/accounts" className="btn-primary">
              Back to accounts
            </Link>
          }
        />
      </div>
    );
  }
  if (acct.loading && !acct.data) return <LoadingBlock label="Loading account…" />;
  if (acct.error || !acct.data) return <ErrorState error={acct.error} onRetry={acct.reload} />;
  const a = acct.data;

  return (
    <div>
      <Link to="/accounts" className="text-sm font-semibold text-teal-700 hover:underline">
        ← All accounts
      </Link>
      <div className="mt-3 rounded-xl bg-navy-900 p-6 text-white shadow-card">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-2xl font-bold">{a.nickname}</h1>
            <p className="mt-1 text-sm text-navy-200">
              {titleCase(a.type)} account · <span className="font-mono">{a.masked_number}</span> · Opened {formatDate(a.opened_at)}
            </p>
          </div>
          <Badge tone={a.status === "active" ? "teal" : "amber"}>{titleCase(a.status)}</Badge>
        </div>
        <p className="mt-6 text-sm text-navy-200">Current balance</p>
        <p className="text-4xl font-bold tabular-nums">{formatMinor(a.balance_minor)}</p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Link to={`/transfer?from=${a.id}`} className="btn bg-teal-600 text-white hover:bg-teal-500">
            Transfer from this account
          </Link>
          {a.status === "active" && (
            <>
              <Link to={`/cash?account=${a.id}&kind=deposit`} className="btn bg-white text-navy-900 hover:bg-navy-50">
                Deposit
              </Link>
              <Link to={`/cash?account=${a.id}&kind=withdraw`} className="btn bg-white text-navy-900 hover:bg-navy-50">
                Withdraw
              </Link>
            </>
          )}
          <Link to={`/transactions?account_id=${a.id}`} className="btn bg-white/10 text-white hover:bg-white/20">
            Search &amp; export
          </Link>
        </div>
      </div>

      <section className="card mt-6" aria-labelledby="history-heading">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 id="history-heading" className="font-semibold text-navy-900">
            Transaction history
          </h2>
          {txns.loading && txns.data && <span className="text-xs text-slate-500">Updating…</span>}
        </div>
        {txns.loading && !txns.data && <SkeletonRows rows={6} />}
        {txns.error && (
          <div className="p-4">
            <ErrorState error={txns.error} onRetry={txns.reload} />
          </div>
        )}
        {txns.data && txns.data.items.length === 0 && <EmptyState title="No transactions on this account" />}
        {txns.data && txns.data.items.length > 0 && (
          <>
            <TxnList items={txns.data.items} onSelect={(t) => setSelected(t.id)} showBalance />
            <Pagination page={txns.data.page} pages={txns.data.pages} total={txns.data.total} onPage={setPage} disabled={txns.loading} />
          </>
        )}
      </section>
      <TxnDetailModal txnId={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
