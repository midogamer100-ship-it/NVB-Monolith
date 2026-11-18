import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { EmptyState, ErrorState, PageHeader, SkeletonRows } from "../../components/ui";
import { toQuery } from "../../lib/api";
import { LOANS } from "../../lib/digital";
import { formatDateTime } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { CapabilityGate, canManageLoans, useAdminAccess } from "./access";
import { amount, LOAN_STATUSES, LoanStatus, QUEUES, RecommendationBadge, statusLabel, type LoanApp } from "./loanTypes";

function Queue() {
  const [params, setParams] = useSearchParams();
  const queue = QUEUES.some((q) => q.key === params.get("queue")) ? (params.get("queue") as string) : "pending_review";
  const status = (LOAN_STATUSES as readonly string[]).includes(params.get("status") ?? "") ? (params.get("status") as string) : "";
  const q = (params.get("q") ?? "").slice(0, 80);
  const [search, setSearch] = useState(q);
  useEffect(() => setSearch(q), [q]);

  const list = useApi<{ items: LoanApp[] }>(`${LOANS}/review/applications${toQuery({ queue, status, q })}`);

  function update(next: Record<string, string>) {
    const merged = { queue, status, q, ...next };
    const clean: Record<string, string> = {};
    for (const [k, v] of Object.entries(merged)) if (v) clean[k] = v;
    setParams(clean, { replace: true });
  }

  function onSearch(e: FormEvent) {
    e.preventDefault();
    update({ q: search.trim() });
  }

  const items = list.data?.items ?? [];
  return (
    <div>
      <PageHeader
        title="Loan management"
        subtitle="Review applications, record a recommendation, then take the final decision. Decisions never disburse money."
        actions={
          <button type="button" className="btn-secondary" onClick={list.reload} disabled={list.loading}>
            Refresh
          </button>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2" role="tablist" aria-label="Queues">
        {QUEUES.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={queue === t.key}
            className={queue === t.key ? "btn-primary" : "btn-secondary"}
            onClick={() => update({ queue: t.key, status: t.key === "all" ? status : "" })}
          >
            {t.label}
          </button>
        ))}
      </div>

      <form className="card mb-4 grid gap-3 p-4 sm:grid-cols-3" onSubmit={onSearch}>
        <div>
          <label htmlFor="loan-status" className="label">
            Status
          </label>
          <select id="loan-status" className="input" value={status} onChange={(e) => update({ status: e.target.value })}>
            <option value="">Any status in this queue</option>
            {LOAN_STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        </div>
        <div className="sm:col-span-2">
          <label htmlFor="loan-search" className="label">
            Search applicant, account ending or application ID
          </label>
          <div className="flex gap-2">
            <input id="loan-search" className="input" maxLength={80} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="e.g. customer007 or 4821" />
            <button type="submit" className="btn-primary">
              Search
            </button>
          </div>
        </div>
      </form>

      <section className="card min-w-0 overflow-hidden">
        {list.loading && !list.data && <SkeletonRows rows={5} />}
        {list.error && (
          <div className="p-4">
            <ErrorState error={list.error} onRetry={list.reload} title="Couldn't load applications" />
          </div>
        )}
        {list.data && items.length === 0 && <EmptyState title="No applications here" message="Nothing matches this queue and filter right now." />}
        {items.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {items.map((a) => (
              <li key={a.id}>
                <Link to={`/admin/loans/${encodeURIComponent(a.id)}`} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 hover:bg-slate-50">
                  <span className="min-w-0">
                    <span className="block font-medium text-navy-900">{a.owner_label || "Applicant"}</span>
                    <span className="block text-xs text-slate-500">
                      {a.account.masked_number} · {amount(a)} · {a.term_months} months
                      {a.submitted_at ? ` · submitted ${formatDateTime(a.submitted_at)}` : ""}
                    </span>
                  </span>
                  <span className="flex flex-wrap items-center gap-2">
                    <RecommendationBadge value={a.recommendation} />
                    <LoanStatus value={a.status} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      <p className="mt-2 text-xs text-slate-500">Shows the most recent matching applications (the service limits each list).</p>
    </div>
  );
}

export default function LoanQueue() {
  const { loans } = useAdminAccess();
  return (
    <CapabilityGate probe={loans} allowed={canManageLoans(loans)} service="Loans">
      <Queue />
    </CapabilityGate>
  );
}
