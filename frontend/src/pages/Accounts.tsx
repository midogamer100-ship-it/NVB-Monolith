import { Link } from "react-router-dom";
import { Badge, EmptyState, ErrorState, PageHeader, SkeletonRows } from "../components/ui";
import { formatDate, formatDecimal, formatMinor, titleCase } from "../lib/format";
import type { Account } from "../lib/types";
import { useApi } from "../lib/useApi";

export default function Accounts() {
  const { data, error, loading, reload } = useApi<{ accounts: Account[]; total_balance: string; currency: string }>("/api/accounts");

  return (
    <div>
      <PageHeader
        title="Accounts"
        subtitle={data ? `Total available balance ${formatDecimal(data.total_balance)}` : "Your Nova Valley Bank accounts"}
        actions={
          <Link to="/transfer" className="btn-accent">
            New transfer
          </Link>
        }
      />
      {loading && !data && (
        <div className="card">
          <SkeletonRows rows={3} />
        </div>
      )}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && data.accounts.length === 0 && (
        <div className="card">
          <EmptyState title="No accounts" message="You don't have any accounts yet." />
        </div>
      )}
      {data && data.accounts.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {data.accounts.map((a) => (
            <article key={a.id} className="card flex flex-col p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-navy-900">{a.nickname}</h2>
                  <p className="text-sm text-slate-500">
                    {titleCase(a.type)} account · <span className="font-mono">{a.masked_number}</span>
                  </p>
                </div>
                <Badge tone={a.status === "active" ? "teal" : "amber"}>{titleCase(a.status)}</Badge>
              </div>
              <p className="mt-5 text-xs font-medium uppercase tracking-wide text-slate-500">Current balance</p>
              <p className="text-3xl font-bold tabular-nums text-navy-900">{formatMinor(a.balance_minor)}</p>
              <p className="mt-1 text-xs text-slate-500">Opened {formatDate(a.opened_at)}</p>
              <div className="mt-5 flex gap-2">
                <Link to={`/accounts/${a.id}`} className="btn-primary">
                  Details &amp; history
                </Link>
                <Link to={`/transfer?from=${a.id}`} className="btn-secondary">
                  Transfer from
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
