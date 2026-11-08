import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Alert, Badge, EmptyState, ErrorState, LoadingBlock, PageHeader, SkeletonRows, Spinner } from "../components/ui";
import { api, describeError } from "../lib/api";
import { formatDateTime, formatDuration } from "../lib/format";
import type { AuditEvent, ClusterMetrics, OpsStatus } from "../lib/types";
import { useApi } from "../lib/useApi";

const NOT_CONFIGURED = "Not configured";

function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 break-all text-lg font-semibold text-navy-900">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

function fmt(v: number | null | undefined, render: (n: number) => string): string {
  return v === null || v === undefined ? "No data" : render(v);
}

function ClusterPanel({ c }: { c: ClusterMetrics }) {
  if (c.status === "not_configured") {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Request rate (all instances)" value={NOT_CONFIGURED} />
        <Stat label="p95 latency (all instances)" value={NOT_CONFIGURED} />
        <Stat label="Error rate (all instances)" value={NOT_CONFIGURED} />
        <Stat label="Replicas" value={NOT_CONFIGURED} hint="Requires the optional monitoring integration" />
      </div>
    );
  }
  if (c.status === "error") {
    return <Alert kind="warning">Monitoring integration is configured but unavailable: {c.message ?? "query failed"}.</Alert>;
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="Request rate (all instances)" value={fmt(c.request_rate_per_second, (n) => `${n.toFixed(2)} req/s`)} hint="2-minute rate" />
      <Stat label="p95 latency (all instances)" value={fmt(c.p95_latency_seconds, (n) => `${(n * 1000).toFixed(0)} ms`)} />
      <Stat label="Error rate (all instances)" value={fmt(c.error_rate, (n) => `${(n * 100).toFixed(2)} %`)} hint="HTTP 5xx share" />
      <Stat
        label="Replicas available / desired"
        value={`${fmt(c.available_replicas, (n) => String(Math.round(n)))} / ${fmt(c.desired_replicas, (n) => String(Math.round(n)))}`}
        hint="From kube-state-metrics via Prometheus"
      />
    </div>
  );
}

export default function Operations() {
  const status = useApi<OpsStatus>("/api/ops/status");
  const auditLog = useApi<{ items: AuditEvent[] }>("/api/ops/audit?limit=50");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [unlockName, setUnlockName] = useState("");
  const [unlocking, setUnlocking] = useState(false);
  const [unlockResult, setUnlockResult] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const { reload: reloadStatus } = status;

  useEffect(() => {
    if (!autoRefresh) return;
    const t = window.setInterval(reloadStatus, 10_000);
    return () => window.clearInterval(t);
  }, [autoRefresh, reloadStatus]);

  async function onUnlock(e: FormEvent) {
    e.preventDefault();
    const name = unlockName.trim().toLowerCase();
    if (!name) {
      setUnlockResult({ kind: "error", text: "Enter a username." });
      return;
    }
    setUnlocking(true);
    setUnlockResult(null);
    try {
      const r = await api<{ username: string; cleared_failures: number }>(`/api/ops/users/${encodeURIComponent(name)}/unlock`, { method: "POST" });
      setUnlockResult({ kind: "success", text: `Cleared ${r.cleared_failures} failed sign-in record(s) for ${r.username}.` });
      setUnlockName("");
      auditLog.reload();
    } catch (err) {
      setUnlockResult({ kind: "error", text: describeError(err) });
    } finally {
      setUnlocking(false);
    }
  }

  const s = status.data;

  return (
    <div>
      <PageHeader
        title="Operations"
        subtitle="Live, measured values only. Anything not measured is shown as “Not configured”."
        actions={
          <>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-teal-600" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
              Auto-refresh (10s)
            </label>
            <button type="button" className="btn-secondary" onClick={status.reload} disabled={status.loading}>
              {status.loading ? <Spinner className="h-4 w-4" /> : null}
              Refresh
            </button>
          </>
        }
      />

      {status.loading && !s && <LoadingBlock label="Reading instance status…" />}
      {status.error && <ErrorState error={status.error} onRetry={status.reload} title="Couldn't read operations status" />}

      {s && (
        <>
          <section className="rounded-xl bg-navy-900 p-6 text-white shadow-card" aria-label="Environment">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-teal-300">Environment</p>
                <p className="mt-1 text-3xl font-bold">{s.environment_label}</p>
              </div>
              <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
                <span className="text-navy-300">Version</span>
                <span className="font-mono">{s.app_version}</span>
                <span className="text-navy-300">Serving instance</span>
                <span className="break-all font-mono">{s.instance_id}</span>
                <span className="text-navy-300">Server time</span>
                <span>{formatDateTime(s.server_time)}</span>
              </div>
            </div>
          </section>

          <section className="mt-6" aria-labelledby="db-heading">
            <h2 id="db-heading" className="mb-3 text-lg font-semibold text-navy-900">
              Database
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Connectivity"
                value={<Badge tone={s.database.status === "connected" ? "teal" : "red"}>{s.database.status === "connected" ? "Connected" : "Unavailable"}</Badge>}
                hint={s.database.error ?? (s.database.host ? `${s.database.backend} @ ${s.database.host}` : undefined)}
              />
              <Stat label="Round-trip" value={s.database.latency_ms !== undefined ? `${s.database.latency_ms} ms` : "—"} hint="SELECT 1 from this instance" />
              <Stat
                label="Pool in use / size"
                value={s.db_pool.size !== undefined ? `${s.db_pool.checked_out} / ${s.db_pool.size}` : NOT_CONFIGURED}
                hint={s.db_pool.overflow !== undefined ? `Overflow connections: ${s.db_pool.overflow}` : undefined}
              />
              <Stat label="Demo workload" value={s.demo_workload_enabled ? "Enabled" : "Disabled"} hint="Server-side configuration flag" />
            </div>
          </section>

          <section className="mt-6" aria-labelledby="instance-heading">
            <h2 id="instance-heading" className="mb-1 text-lg font-semibold text-navy-900">
              This instance
            </h2>
            <p className="mb-3 text-sm text-slate-600">Measured in-process by the instance that answered this request ({s.instance_id}).</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Request rate" value={`${s.this_instance.last_minute.request_rate_per_second.toFixed(2)} req/s`} hint={`${s.this_instance.last_minute.requests} requests in the last minute`} />
              <Stat label="p95 latency" value={fmt(s.this_instance.last_minute.p95_latency_ms, (n) => `${n} ms`)} hint="Last minute" />
              <Stat label="Error rate" value={fmt(s.this_instance.last_minute.error_rate, (n) => `${(n * 100).toFixed(2)} %`)} hint="HTTP 5xx, last minute" />
              <Stat label="Uptime" value={formatDuration(s.this_instance.uptime_seconds)} hint={`${s.this_instance.requests_total.toLocaleString("en-US")} requests · ${s.this_instance.errors_total} errors`} />
            </div>
          </section>

          <section className="mt-6" aria-labelledby="cluster-heading">
            <h2 id="cluster-heading" className="mb-1 text-lg font-semibold text-navy-900">
              All instances (monitoring integration)
            </h2>
            <p className="mb-3 text-sm text-slate-600">Values come only from an authorised Prometheus/Thanos query. The application never calls the Kubernetes API.</p>
            <ClusterPanel c={s.cluster} />
          </section>
        </>
      )}

      <div className="mt-8 grid grid-cols-1 gap-6 xl:grid-cols-3">
        <section className="card min-w-0 p-5" aria-labelledby="unlock-heading">
          <h2 id="unlock-heading" className="font-semibold text-navy-900">
            Clear sign-in lockout
          </h2>
          <p className="mt-1 text-sm text-slate-600">Removes failed sign-in records for a username. This administrative action is audited.</p>
          <form className="mt-4 space-y-3" onSubmit={onUnlock}>
            <div>
              <label htmlFor="unlock-user" className="label">
                Username
              </label>
              <input id="unlock-user" className="input" maxLength={64} autoComplete="off" value={unlockName} onChange={(e) => setUnlockName(e.target.value)} disabled={unlocking} />
            </div>
            {unlockResult && <Alert kind={unlockResult.kind}>{unlockResult.text}</Alert>}
            <button type="submit" className="btn-primary w-full" disabled={unlocking}>
              {unlocking ? "Clearing…" : "Clear lockout"}
            </button>
          </form>
        </section>

        <section className="card min-w-0 overflow-x-auto xl:col-span-2" aria-labelledby="audit-heading">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
            <h2 id="audit-heading" className="font-semibold text-navy-900">
              Recent audit events
            </h2>
            <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={auditLog.reload} disabled={auditLog.loading}>
              Refresh
            </button>
          </div>
          {auditLog.loading && !auditLog.data && <SkeletonRows rows={5} />}
          {auditLog.error && (
            <div className="p-4">
              <ErrorState error={auditLog.error} onRetry={auditLog.reload} />
            </div>
          )}
          {auditLog.data && auditLog.data.items.length === 0 && <EmptyState title="No audit events yet" />}
          {auditLog.data && auditLog.data.items.length > 0 && (
            <div className="max-h-[28rem] overflow-auto">
              <table className="min-w-full text-sm">
                <thead className="sticky top-0 bg-white">
                  <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th scope="col" className="px-4 py-2">Time</th>
                    <th scope="col" className="px-4 py-2">Event</th>
                    <th scope="col" className="px-4 py-2">Outcome</th>
                    <th scope="col" className="px-4 py-2">Actor</th>
                    <th scope="col" className="px-4 py-2">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {auditLog.data.items.map((e) => (
                    <tr key={e.id}>
                      <td className="whitespace-nowrap px-4 py-2 text-slate-600">{formatDateTime(e.created_at)}</td>
                      <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-navy-900">{e.event_type}</td>
                      <td className="px-4 py-2">
                        <Badge tone={e.outcome === "success" || e.outcome === "completed" ? "teal" : e.outcome === "failure" || e.outcome === "failed" ? "red" : "amber"}>{e.outcome}</Badge>
                      </td>
                      <td className="px-4 py-2 text-slate-700">{e.actor ?? "—"}</td>
                      <td className="max-w-xs truncate px-4 py-2 font-mono text-xs text-slate-500" title={JSON.stringify(e.details)}>
                        {Object.keys(e.details).length ? JSON.stringify(e.details) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
