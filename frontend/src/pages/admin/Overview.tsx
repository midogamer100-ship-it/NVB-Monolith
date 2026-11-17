import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Alert, ErrorState, LoadingBlock, PageHeader } from "../../components/ui";
import { LOANS, STATEMENTS } from "../../lib/digital";
import { useApi } from "../../lib/useApi";
import { canManageLoans, canOperateStatements, useAdminAccess } from "./access";
import { count, type LoanStats } from "./loanTypes";
import type { StatementsOpsSummary } from "./StatementOps";

function Metric({ label, value, to, hint }: { label: string; value: number | null; to?: string; hint?: string }) {
  const body = (
    <>
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums text-navy-900">{value === null ? "Unavailable" : value.toLocaleString("en-US")}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </>
  );
  return to ? (
    <Link to={to} className="block rounded-lg border border-slate-200 bg-white p-4 transition-colors hover:border-teal-400 hover:bg-teal-50/40">
      {body}
    </Link>
  ) : (
    <div className="rounded-lg border border-slate-200 bg-white p-4">{body}</div>
  );
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="mt-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-navy-900">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function NotGranted({ service }: { service: string }) {
  return <Alert kind="info">{service} metrics are not shown: your account does not hold the Operations Admin role for this service.</Alert>;
}

function LoanMetrics() {
  const stats = useApi<LoanStats>(`${LOANS}/review/stats`);
  if (stats.loading && !stats.data) return <LoadingBlock label="Loading loan workload…" />;
  if (stats.error) return <ErrorState error={stats.error} onRetry={stats.reload} title="Loan metrics are unavailable" />;
  const s = stats.data;
  if (!s) return null;
  const by = s.by_status ?? {};
  const retired = count(s.held_by_retired_reviewer) ?? 0;
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        <Metric label="Pending review" value={count(s.pending_review)} to="/admin/loans?queue=pending_review" hint="Submitted, or under review without a recommendation" />
        <Metric label="Pending decision" value={count(s.pending_decision)} to="/admin/loans?queue=pending_decision" hint="Recommendation recorded; final decision outstanding" />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Submitted" value={count(by.submitted)} to="/admin/loans?queue=all&status=submitted" />
        <Metric label="Under review" value={count(by.under_review)} to="/admin/loans?queue=all&status=under_review" />
        <Metric label="Approved" value={count(by.approved)} to="/admin/loans?queue=all&status=approved" />
        <Metric label="Rejected" value={count(by.rejected)} to="/admin/loans?queue=all&status=rejected" />
      </div>
      {retired > 0 && (
        <div className="mt-3">
          <Alert kind="warning">
            {retired} application{retired === 1 ? " is" : "s are"} still assigned to a reviewer from the retired Reviewer workflow. Open it from{" "}
            <Link to="/admin/loans?queue=pending_review" className="font-semibold underline">
              Pending review
            </Link>{" "}
            and use “Take over review”; the previous reviewer and their notes stay in the history.
          </Alert>
        </div>
      )}
    </>
  );
}

function StatementMetrics() {
  const summary = useApi<StatementsOpsSummary>(`${STATEMENTS}/ops/summary`);
  if (summary.loading && !summary.data) return <LoadingBlock label="Loading statement processing…" />;
  if (summary.error) return <ErrorState error={summary.error} onRetry={summary.reload} title="Statement metrics are unavailable" />;
  const s = summary.data;
  if (!s) return null;
  const by = s.by_status ?? {};
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <Metric label="Queued" value={count(by.queued)} to="/admin/statements?status=queued" />
      <Metric label="Running" value={count(by.running)} to="/admin/statements?status=running" />
      <Metric label="Completed" value={count(by.completed)} to="/admin/statements?status=completed" />
      <Metric label="Failed" value={count(by.failed)} to="/admin/statements?status=failed" hint={`${(s.recent_failures ?? []).length} recent failure(s) listed`} />
      <Metric label="Cancelled" value={count(by.cancelled)} to="/admin/statements?status=cancelled" />
    </div>
  );
}

export default function Overview() {
  const { loans, statements } = useAdminAccess();
  return (
    <div>
      <PageHeader title="Admin overview" subtitle="Work waiting for the Operations team. Counts come directly from the Loans and Statements services." />

      <Section
        title="Loan applications"
        action={canManageLoans(loans) ? <Link to="/admin/loans" className="btn-secondary">Open loan management</Link> : null}
      >
        {loans.state === "loading" ? (
          <LoadingBlock label="Checking your permissions…" />
        ) : loans.state === "unavailable" ? (
          <Alert kind="warning">The Loans service is temporarily unavailable, so loan metrics can't be shown. Reload to retry.</Alert>
        ) : canManageLoans(loans) ? (
          <LoanMetrics />
        ) : (
          <NotGranted service="Loans" />
        )}
      </Section>

      <Section
        title="Statement processing"
        action={canOperateStatements(statements) ? <Link to="/admin/statements" className="btn-secondary">Open statement operations</Link> : null}
      >
        {statements.state === "loading" ? (
          <LoadingBlock label="Checking your permissions…" />
        ) : statements.state === "unavailable" ? (
          <Alert kind="warning">The Statements service is temporarily unavailable, so statement metrics can't be shown. Reload to retry.</Alert>
        ) : canOperateStatements(statements) ? (
          <StatementMetrics />
        ) : (
          <NotGranted service="Statements" />
        )}
      </Section>

      <Section title="Customer support">
        <div className="card flex flex-wrap items-center justify-between gap-3 p-5">
          <p className="text-sm text-slate-600">Create customer users, clear sign-in lockouts and read the demo mailbox.</p>
          <Link to="/admin/customers" className="btn-secondary">
            Open customer support
          </Link>
        </div>
      </Section>
    </div>
  );
}
