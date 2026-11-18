import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Alert, Badge, EmptyState, ErrorState, LoadingBlock, PageHeader, SkeletonRows } from "../../components/ui";
import { api, describeError, toQuery } from "../../lib/api";
import { STATEMENTS } from "../../lib/digital";
import { formatDateTime } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { CapabilityGate, canOperateStatements, useAdminAccess } from "./access";
import { count, statusLabel } from "./loanTypes";

/** Rows may use the ops shape (flat) or the customer request shape (nested); read both. */
interface OpsRequest {
  id: string;
  status?: string;
  purpose?: string;
  period?: string | { label?: string };
  period_label?: string;
  account_masked?: string;
  account?: { masked_number?: string };
  error_code?: string | null;
  error?: { code?: string | null } | null;
  attempts?: number;
  created_at?: string | null;
  completed_at?: string | null;
}

interface Batch {
  id: string;
  kind?: string;
  status: string;
  trigger?: string;
  period?: { label?: string } | string;
  progress?: Record<string, unknown>;
  retry_rounds?: number;
  error_code?: string | null;
  created_at?: string | null;
  finished_at?: string | null;
}

export interface StatementsOpsSummary {
  by_status?: Record<string, number>;
  by_purpose?: Record<string, number>;
  recent_failures?: OpsRequest[];
  batches?: Batch[];
}

const STATUSES = ["queued", "running", "completed", "failed", "cancelled"];
const PURPOSES = ["customer_request", "batch"];

const periodOf = (r: { period?: string | { label?: string }; period_label?: string }) =>
  typeof r.period === "string" ? r.period : r.period?.label ?? r.period_label ?? "—";
const accountOf = (r: OpsRequest) => r.account_masked ?? r.account?.masked_number ?? "—";
const errorOf = (r: OpsRequest) => r.error_code ?? r.error?.code ?? null;

function StatusBadge({ value }: { value?: string }) {
  if (!value) return <span>—</span>;
  const tone = value === "completed" ? "teal" : value === "failed" ? "red" : value === "cancelled" ? "slate" : value.includes("failures") ? "amber" : "navy";
  return <Badge tone={tone}>{statusLabel(value)}</Badge>;
}

function progressText(p?: Record<string, unknown>): string {
  if (!p) return "—";
  const parts = Object.entries(p).filter(([, v]) => typeof v === "number").map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`);
  return parts.length ? parts.join(" · ") : "—";
}

function Counts({ title, data, keys }: { title: string; data?: Record<string, number>; keys: string[] }) {
  return (
    <div className="card p-4">
      <h2 className="mb-3 font-semibold text-navy-900">{title}</h2>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {keys.map((k) => {
          const v = count(data?.[k]);
          return (
            <div key={k}>
              <dt className="text-xs uppercase tracking-wide text-slate-500">{statusLabel(k)}</dt>
              <dd className="text-xl font-bold tabular-nums text-navy-900">{v === null ? "Unavailable" : v.toLocaleString("en-US")}</dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

function Batches({ batches, canOperate, onChanged }: { batches: Batch[]; canOperate: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  async function run(b: Batch, action: "resume" | "retry-failed") {
    setBusy(b.id + action);
    setResult(null);
    try {
      await api(`${STATEMENTS}/batches/${encodeURIComponent(b.id)}/${action}`, { method: "POST" });
      setResult({ kind: "success", text: action === "resume" ? "Batch resumed. Work continues in the background." : "Failed items re-queued. Work continues in the background." });
    } catch (e) {
      setResult({ kind: "error", text: describeError(e) });
    } finally {
      setBusy(null);
      onChanged();
    }
  }

  return (
    <section className="card min-w-0 overflow-x-auto">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="font-semibold text-navy-900">Monthly statement batches</h2>
        <p className="text-xs text-slate-500">
          {canOperate ? "Resume or retry existing batches. New batches are created by the scheduled job." : "Read-only. Batch actions require the batch operator role."}
        </p>
      </div>
      {result && (
        <div className="p-4">
          <Alert kind={result.kind}>{result.text}</Alert>
        </div>
      )}
      {batches.length === 0 ? (
        <EmptyState title="No batches yet" />
      ) : (
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2">Period</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Progress</th>
              <th className="px-4 py-2">Created</th>
              {canOperate && <th className="px-4 py-2">Actions</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {batches.map((b) => (
              <tr key={b.id}>
                <td className="px-4 py-2">{periodOf(b)}</td>
                <td className="px-4 py-2">
                  <StatusBadge value={b.status} />
                  {b.error_code && <span className="ml-2 font-mono text-xs text-red-700">{b.error_code}</span>}
                </td>
                <td className="px-4 py-2 text-xs text-slate-600">{progressText(b.progress)}</td>
                <td className="whitespace-nowrap px-4 py-2 text-slate-600">{b.created_at ? formatDateTime(b.created_at) : "—"}</td>
                {canOperate && (
                  <td className="space-x-2 whitespace-nowrap px-4 py-2">
                    {["freezing", "releasing", "running"].includes(b.status) && (
                      <button type="button" className="btn-secondary px-2 py-1 text-xs" disabled={busy !== null} onClick={() => void run(b, "resume")}>
                        Resume
                      </button>
                    )}
                    {["running", "completed_with_failures"].includes(b.status) && (
                      <button type="button" className="btn-secondary px-2 py-1 text-xs" disabled={busy !== null} onClick={() => void run(b, "retry-failed")}>
                        Retry failed
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function RequestTable({ rows }: { rows: OpsRequest[] }) {
  return (
    <table className="min-w-full text-sm">
      <thead>
        <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
          <th className="px-4 py-2">Period</th>
          <th className="px-4 py-2">Account</th>
          <th className="px-4 py-2">Type</th>
          <th className="px-4 py-2">Status</th>
          <th className="px-4 py-2">Created</th>
          <th className="px-4 py-2">Completed</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {rows.map((r) => (
          <tr key={r.id}>
            <td className="px-4 py-2">{periodOf(r)}</td>
            <td className="px-4 py-2">{accountOf(r)}</td>
            <td className="px-4 py-2">{r.purpose === "batch" ? "Monthly batch" : r.purpose === "customer_request" ? "Customer request" : r.purpose ?? "—"}</td>
            <td className="px-4 py-2">
              <StatusBadge value={r.status} />
              {errorOf(r) && <span className="ml-2 font-mono text-xs text-red-700">{errorOf(r)}</span>}
              {typeof r.attempts === "number" && r.attempts > 1 && <span className="ml-2 text-xs text-slate-500">{r.attempts} attempts</span>}
            </td>
            <td className="whitespace-nowrap px-4 py-2 text-slate-600">{r.created_at ? formatDateTime(r.created_at) : "—"}</td>
            <td className="whitespace-nowrap px-4 py-2 text-slate-600">{r.completed_at ? formatDateTime(r.completed_at) : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Ops({ batchOperator }: { batchOperator: boolean }) {
  const [params, setParams] = useSearchParams();
  const status = STATUSES.includes(params.get("status") ?? "") ? (params.get("status") as string) : "";
  const purpose = PURPOSES.includes(params.get("purpose") ?? "") ? (params.get("purpose") as string) : "";
  const summary = useApi<StatementsOpsSummary>(`${STATEMENTS}/ops/summary`);
  const requests = useApi<{ items: OpsRequest[] }>(`${STATEMENTS}/ops/requests${toQuery({ status, purpose, limit: 50 })}`);

  function setFilter(k: string, v: string) {
    const next: Record<string, string> = { status, purpose, [k]: v };
    for (const key of Object.keys(next)) if (!next[key]) delete next[key];
    setParams(next, { replace: true });
  }

  const s = summary.data;
  return (
    <div>
      <PageHeader
        title="Statement operations"
        subtitle="Processing status of statement requests. PDFs stay private to their owners; generation always runs in the background."
        actions={
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              summary.reload();
              requests.reload();
            }}
          >
            Refresh
          </button>
        }
      />

      {summary.loading && !s && <LoadingBlock label="Loading statement processing…" />}
      {summary.error && <ErrorState error={summary.error} onRetry={summary.reload} title="Statement status is unavailable" />}
      {s && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Counts title="Requests by status" data={s.by_status} keys={STATUSES} />
            <Counts title="Requests by type" data={s.by_purpose} keys={PURPOSES} />
          </div>

          <section className="card mt-6 min-w-0 overflow-x-auto">
            <div className="border-b border-slate-200 px-4 py-3">
              <h2 className="font-semibold text-navy-900">Recent failures</h2>
              <p className="text-xs text-slate-500">Error codes only; internal details are not shown.</p>
            </div>
            {(s.recent_failures ?? []).length === 0 ? <EmptyState title="No recent failures" /> : <RequestTable rows={s.recent_failures ?? []} />}
          </section>

          <div className="mt-6">
            <Batches batches={s.batches ?? []} canOperate={batchOperator} onChanged={summary.reload} />
          </div>
        </>
      )}

      <section className="card mt-6 min-w-0 overflow-x-auto">
        <div className="flex flex-wrap items-end gap-3 border-b border-slate-200 px-4 py-3">
          <h2 className="mr-auto font-semibold text-navy-900">Statement requests</h2>
          <label className="text-sm">
            <span className="label">Status</span>
            <select className="input" value={status} onChange={(e) => setFilter("status", e.target.value)}>
              <option value="">All</option>
              {STATUSES.map((v) => (
                <option key={v} value={v}>
                  {statusLabel(v)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="label">Type</span>
            <select className="input" value={purpose} onChange={(e) => setFilter("purpose", e.target.value)}>
              <option value="">All</option>
              <option value="customer_request">Customer request</option>
              <option value="batch">Monthly batch</option>
            </select>
          </label>
        </div>
        {requests.loading && !requests.data && <SkeletonRows rows={4} />}
        {requests.error && (
          <div className="p-4">
            <ErrorState error={requests.error} onRetry={requests.reload} title="Couldn't load statement requests" />
          </div>
        )}
        {requests.data && requests.data.items.length === 0 && <EmptyState title="No statement requests match" />}
        {requests.data && requests.data.items.length > 0 && <RequestTable rows={requests.data.items} />}
      </section>
    </div>
  );
}

export default function StatementOps() {
  const { statements } = useAdminAccess();
  const batchOperator = statements.state === "ok" && statements.data.capabilities?.batch_operations === true;
  return (
    <CapabilityGate probe={statements} allowed={canOperateStatements(statements)} service="Statements">
      <Ops batchOperator={batchOperator} />
    </CapabilityGate>
  );
}
