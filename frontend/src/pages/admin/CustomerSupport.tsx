import { useState, type FormEvent } from "react";
import { CreateUserCard, MailboxCard } from "../../components/AdminUserTools";
import { Alert, Badge, EmptyState, ErrorState, PageHeader, SkeletonRows } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import type { AuditEvent } from "../../lib/types";
import { useApi } from "../../lib/useApi";

/** Existing Core admin features (create user, clear lockout, demo mailbox, audit log). */
export default function CustomerSupport() {
  const auditLog = useApi<{ items: AuditEvent[] }>("/api/ops/audit?limit=50");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [unlockName, setUnlockName] = useState("");
  const [unlocking, setUnlocking] = useState(false);
  const [unlockResult, setUnlockResult] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [mailboxKey, setMailboxKey] = useState(0);

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

  return (
    <div>
      <PageHeader
        title="Customer support"
        subtitle="Onboard customers, help with sign-in problems and review the audit trail."
        actions={
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-teal-600" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            Auto-refresh mailbox (10s)
          </label>
        }
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <CreateUserCard
          onCreated={() => {
            setMailboxKey((k) => k + 1);
            auditLog.reload();
          }}
        />
        <MailboxCard autoRefresh={autoRefresh} refreshKey={mailboxKey} />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
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
