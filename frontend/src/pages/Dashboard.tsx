import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import TxnDetailModal from "../components/TxnDetailModal";
import TxnList from "../components/TxnList";
import { EmptyState, ErrorState, PageHeader, SkeletonRows } from "../components/ui";
import { formatMinor, formatMinorCompact, monthLabel, titleCase } from "../lib/format";
import type { Dashboard as DashboardData } from "../lib/types";
import { useApi } from "../lib/useApi";

const CATEGORY_COLORS = ["#0f766e", "#1c386a", "#14b8a6", "#4d77bf", "#5eead4", "#7c9fd6", "#0d9488", "#2f5aa3"];

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export default function Dashboard() {
  const { data, error, loading, reload } = useApi<DashboardData>("/api/dashboard");
  const [selected, setSelected] = useState<number | null>(null);

  if (loading && !data) {
    return (
      <div>
        <div className="mb-6 h-8 w-64 animate-pulse rounded bg-slate-200" />
        <div className="grid gap-4 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card h-32 animate-pulse bg-slate-100" />
          ))}
        </div>
        <div className="card mt-6">
          <SkeletonRows rows={5} />
        </div>
      </div>
    );
  }
  if (error || !data) return <ErrorState error={error} onRetry={reload} title="We couldn't load your dashboard" />;

  const monthly = data.monthly.map((m) => ({ month: monthLabel(m.month), Income: m.income_minor / 100, Spending: m.spending_minor / 100 }));
  const current = data.monthly[data.monthly.length - 1];
  const categories = data.spending_by_category.map((c) => ({ name: c.category, value: c.amount_minor / 100, minor: c.amount_minor }));

  return (
    <div>
      <PageHeader
        title={`${greeting()}, ${data.greeting_name}`}
        subtitle={`Customer ${data.customer_number} · Here's your financial overview`}
        actions={
          <>
            <Link to="/accounts" className="btn-secondary">
              View accounts
            </Link>
            <Link to="/cash" className="btn-secondary">
              Deposit / withdraw
            </Link>
            <Link to="/transfer" className="btn-accent">
              New transfer
            </Link>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="relative overflow-hidden rounded-xl bg-navy-900 p-6 text-white shadow-card">
          <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-teal-500/15" aria-hidden="true" />
          <p className="text-sm font-medium text-navy-200">Total available balance</p>
          <p className="mt-2 break-words text-2xl font-bold tabular-nums xl:text-3xl">{formatMinor(data.total_balance_minor)}</p>
          <p className="mt-1 text-xs text-navy-300">Across {data.accounts.length} account{data.accounts.length === 1 ? "" : "s"}</p>
        </div>
        <div className="card p-6">
          <p className="text-sm font-medium text-slate-600">Income this month</p>
          <p className="mt-2 text-2xl font-bold tabular-nums text-teal-700">{formatMinor(current?.income_minor ?? 0)}</p>
          <p className="mt-1 text-xs text-slate-500">Excludes transfers between your own accounts</p>
        </div>
        <div className="card p-6">
          <p className="text-sm font-medium text-slate-600">Spending this month</p>
          <p className="mt-2 text-2xl font-bold tabular-nums text-navy-900">{formatMinor(current?.spending_minor ?? 0)}</p>
          <p className="mt-1 text-xs text-slate-500">Card, bills, cash and outgoing transfers</p>
        </div>
      </div>

      <section className="mt-6" aria-labelledby="accounts-heading">
        <h2 id="accounts-heading" className="mb-3 text-lg font-semibold text-navy-900">
          Your accounts
        </h2>
        {data.accounts.length === 0 ? (
          <div className="card">
            <EmptyState title="No accounts yet" message="Accounts opened for you will appear here." />
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.accounts.map((a) => (
              <Link key={a.id} to={`/accounts/${a.id}`} className="card group p-5 transition-shadow hover:shadow-md">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-semibold text-navy-900">{a.nickname}</p>
                    <p className="text-xs text-slate-500">
                      {titleCase(a.type)} · {a.masked_number}
                    </p>
                  </div>
                  <span className="rounded-md bg-teal-50 px-2 py-0.5 text-xs font-semibold text-teal-800">{a.currency}</span>
                </div>
                <p className="mt-4 text-2xl font-bold tabular-nums text-navy-900">{formatMinor(a.balance_minor)}</p>
                <p className="mt-1 text-xs font-medium text-teal-700 group-hover:underline">View details →</p>
              </Link>
            ))}
          </div>
        )}
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-5">
        <section className="card p-5 xl:col-span-3" aria-labelledby="cashflow-heading">
          <h2 id="cashflow-heading" className="font-semibold text-navy-900">
            Income vs spending · last 6 months
          </h2>
          <div className="mt-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={monthly} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="month" tick={{ fontSize: 12, fill: "#475569" }} axisLine={false} tickLine={false} />
                <YAxis
                  tick={{ fontSize: 11, fill: "#475569" }}
                  axisLine={false}
                  tickLine={false}
                  width={72}
                  tickFormatter={(v: number) => formatMinorCompact(Math.round(v * 100))}
                />
                <Tooltip formatter={(v: number) => formatMinor(Math.round(v * 100))} cursor={{ fill: "#eef3fb" }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="Income" fill="#0f766e" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Spending" fill="#1c386a" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="card p-5 xl:col-span-2" aria-labelledby="category-heading">
          <h2 id="category-heading" className="font-semibold text-navy-900">
            Spending by category · this month
          </h2>
          {categories.length === 0 ? (
            <EmptyState title="No spending yet this month" message="Card purchases and bill payments will be grouped here." />
          ) : (
            <div className="mt-4 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={categories} layout="vertical" margin={{ top: 0, right: 12, left: 0, bottom: 0 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="name" width={96} tick={{ fontSize: 12, fill: "#334155" }} axisLine={false} tickLine={false} />
                  <Tooltip formatter={(v: number) => formatMinor(Math.round(v * 100))} cursor={{ fill: "#eef3fb" }} />
                  <Bar dataKey="value" name="Spent" radius={[0, 4, 4, 0]}>
                    {categories.map((c, i) => (
                      <Cell key={c.name} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>
      </div>

      <section className="card mt-6" aria-labelledby="recent-heading">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 id="recent-heading" className="font-semibold text-navy-900">
            Recent transactions
          </h2>
          <Link to="/transactions" className="text-sm font-semibold text-teal-700 hover:underline">
            View all
          </Link>
        </div>
        {data.recent_transactions.length === 0 ? (
          <EmptyState title="No transactions yet" />
        ) : (
          <TxnList items={data.recent_transactions} onSelect={(t) => setSelected(t.id)} />
        )}
      </section>
      <TxnDetailModal txnId={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
