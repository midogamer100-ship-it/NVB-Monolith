import { useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import TxnDetailModal from "../components/TxnDetailModal";
import TxnList from "../components/TxnList";
import { EmptyState, ErrorState, PageHeader, Pagination, SkeletonRows } from "../components/ui";
import { toQuery } from "../lib/api";
import { titleCase } from "../lib/format";
import type { Account, TxnPage } from "../lib/types";
import { useApi } from "../lib/useApi";

const TYPES = ["salary", "deposit", "transfer_in", "transfer_out", "card_purchase", "bill_payment", "atm_withdrawal"];
const FILTER_KEYS = ["account_id", "type", "direction", "q", "date_from", "date_to"] as const;
type FilterKey = (typeof FILTER_KEYS)[number];
type Filters = Record<FilterKey, string>;

function readFilters(params: URLSearchParams): Filters {
  return Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ""])) as Filters;
}

export default function Transactions() {
  const [params, setParams] = useSearchParams();
  const applied = readFilters(params);
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const [draft, setDraft] = useState<Filters>(applied);
  const [selected, setSelected] = useState<number | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const accounts = useApi<{ accounts: Account[] }>("/api/accounts");
  const filterQuery = toQuery({ ...applied });
  const listPath = `/api/transactions${toQuery({ ...applied, page, page_size: 20 })}`;
  const { data, error, loading, reload } = useApi<TxnPage>(listPath);
  const exportHref = `/api/transactions/export.csv${filterQuery}`;

  const activeCount = useMemo(() => FILTER_KEYS.filter((k) => applied[k]).length, [applied]);

  function apply(e: FormEvent) {
    e.preventDefault();
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
      setLocalError("The 'from' date must be on or before the 'to' date.");
      return;
    }
    setLocalError(null);
    const next = new URLSearchParams();
    for (const k of FILTER_KEYS) if (draft[k].trim()) next.set(k, draft[k].trim());
    setParams(next);
  }

  function clear() {
    const empty = Object.fromEntries(FILTER_KEYS.map((k) => [k, ""])) as Filters;
    setDraft(empty);
    setLocalError(null);
    setParams(new URLSearchParams());
  }

  function goToPage(p: number) {
    const next = new URLSearchParams(params);
    next.set("page", String(p));
    setParams(next);
  }

  const set = (k: FilterKey) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [k]: e.target.value }));

  return (
    <div>
      <PageHeader
        title="Transactions"
        subtitle="Search, filter and export your transaction history."
        actions={
          <a href={exportHref} className="btn-secondary" download>
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M12 4v11m0 0l-4-4m4 4l4-4M5 20h14" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Export CSV{activeCount ? " (filtered)" : ""}
          </a>
        }
      />

      <form className="card mb-6 grid gap-4 p-4 sm:grid-cols-2 xl:grid-cols-4" onSubmit={apply}>
        <div className="sm:col-span-2">
          <label htmlFor="q" className="label">
            Search
          </label>
          <input id="q" className="input" placeholder="Description, merchant or reference" maxLength={60} value={draft.q} onChange={set("q")} />
        </div>
        <div>
          <label htmlFor="account" className="label">
            Account
          </label>
          <select id="account" className="input" value={draft.account_id} onChange={set("account_id")}>
            <option value="">All accounts</option>
            {(accounts.data?.accounts ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.nickname} ({a.masked_number})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="type" className="label">
            Type
          </label>
          <select id="type" className="input" value={draft.type} onChange={set("type")}>
            <option value="">All types</option>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {titleCase(t)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="direction" className="label">
            Direction
          </label>
          <select id="direction" className="input" value={draft.direction} onChange={set("direction")}>
            <option value="">Money in &amp; out</option>
            <option value="credit">Money in</option>
            <option value="debit">Money out</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:col-span-2">
          <div>
            <label htmlFor="date_from" className="label">
              From
            </label>
            <input id="date_from" type="date" className="input" value={draft.date_from} onChange={set("date_from")} />
          </div>
          <div>
            <label htmlFor="date_to" className="label">
              To
            </label>
            <input id="date_to" type="date" className="input" value={draft.date_to} onChange={set("date_to")} />
          </div>
        </div>
        <div className="col-span-full flex flex-wrap items-center gap-2">
          <button type="submit" className="btn-primary">
            Apply filters
          </button>
          <button type="button" className="btn-ghost" onClick={clear} disabled={activeCount === 0}>
            Clear all
          </button>
          {localError && <p className="text-sm text-red-700">{localError}</p>}
        </div>
      </form>

      <section className="card" aria-label="Transaction results">
        {loading && !data && <SkeletonRows rows={8} />}
        {error && (
          <div className="p-4">
            <ErrorState error={error} onRetry={reload} />
          </div>
        )}
        {data && !error && data.items.length === 0 && (
          <EmptyState
            title="No matching transactions"
            message={activeCount ? "Try widening the date range or clearing filters." : "Your transactions will appear here."}
            action={
              activeCount ? (
                <button type="button" className="btn-secondary" onClick={clear}>
                  Clear filters
                </button>
              ) : undefined
            }
          />
        )}
        {data && !error && data.items.length > 0 && (
          <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
            <TxnList items={data.items} onSelect={(t) => setSelected(t.id)} showBalance />
            <Pagination page={data.page} pages={data.pages} total={data.total} onPage={goToPage} disabled={loading} />
          </div>
        )}
      </section>
      <TxnDetailModal txnId={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
