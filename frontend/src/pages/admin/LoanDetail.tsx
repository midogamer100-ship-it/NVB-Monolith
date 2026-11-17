import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { Alert, EmptyState, ErrorState, LoadingBlock, PageHeader } from "../../components/ui";
import { api, ApiError, describeError } from "../../lib/api";
import { LOANS, money } from "../../lib/digital";
import { formatDateTime } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { CapabilityGate, canManageLoans, useAdminAccess, type LoansMe } from "./access";
import { amount, LoanStatus, RecommendationBadge, statusLabel, type LoanApp } from "./loanTypes";

const SUMMARY_LABELS: Record<string, string> = {
  installment_minor: "Monthly instalment (no interest)",
  average_monthly_credits_minor: "Average monthly credits",
  average_monthly_debits_minor: "Average monthly debits",
  disposable_income_minor: "Disposable income",
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-navy-900">{children}</dd>
    </div>
  );
}

function who(actor: string | null | undefined, app: LoanApp, me: LoansMe): string {
  if (!actor) return "—";
  if (actor === me.subject) return "You";
  if (actor === app.owner_subject) return `${app.owner_label || "Applicant"} (applicant)`;
  return actor;
}

/** Render audit details as plain text only (never HTML). */
function details(d: Record<string, unknown> | null | undefined, app: LoanApp, me: LoansMe): string {
  if (!d) return "";
  return Object.entries(d)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "string" && v.startsWith("nvb-user:") ? who(v, app, me) : String(v)}`)
    .join(" · ");
}

function DecisionForm({
  title,
  options,
  submitLabel,
  busy,
  onSubmit,
  note,
}: {
  title: string;
  options: { value: string; label: string }[];
  submitLabel: string;
  busy: boolean;
  onSubmit: (choice: string, reason: string) => void;
  note: ReactNode;
}) {
  const [choice, setChoice] = useState(options[0].value);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    const r = reason.trim();
    if (r.length < 10) {
      setError("Give a meaningful reason of at least 10 characters.");
      return;
    }
    setError("");
    onSubmit(choice, r);
  }
  return (
    <form className="space-y-3 border-t border-slate-200 pt-4" onSubmit={submit}>
      <h3 className="font-semibold text-navy-900">{title}</h3>
      <fieldset className="flex flex-wrap gap-4">
        <legend className="sr-only">{title}</legend>
        {options.map((o) => (
          <label key={o.value} className="flex items-center gap-2 text-sm">
            <input type="radio" name={title} value={o.value} checked={choice === o.value} onChange={() => setChoice(o.value)} disabled={busy} />
            {o.label}
          </label>
        ))}
      </fieldset>
      <div>
        <label className="label" htmlFor={`${title}-reason`}>
          Reason (required, at least 10 characters)
        </label>
        <textarea id={`${title}-reason`} className="input min-h-[6rem]" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} />
        {error && <p className="mt-1 text-sm text-red-700">{error}</p>}
      </div>
      {note}
      <button type="submit" className="btn-primary" disabled={busy}>
        {busy ? "Saving…" : submitLabel}
      </button>
    </form>
  );
}

function Detail({ id, me }: { id: string; me: LoansMe }) {
  const app = useApi<LoanApp>(`${LOANS}/review/applications/${encodeURIComponent(id)}`);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ kind: "success" | "error" | "warning"; text: string; stale?: boolean } | null>(null);

  if (app.loading && !app.data) return <LoadingBlock label="Loading application…" />;
  if (app.error && !app.data) {
    if (app.error instanceof ApiError && app.error.status === 404) {
      return (
        <div className="card">
          <EmptyState
            title="Application not found"
            message="It doesn't exist or isn't available for review."
            action={
              <Link to="/admin/loans" className="btn-secondary">
                Back to loan management
              </Link>
            }
          />
        </div>
      );
    }
    return <ErrorState error={app.error} onRetry={app.reload} title="Couldn't load this application" />;
  }
  const a = app.data;
  if (!a) return null;

  const own = a.owner_subject === me.subject;
  const open = a.status === "submitted" || a.status === "under_review";
  const mine = a.assignment?.reviewer_is_current_admin === true;
  const retired = a.assignment?.held_by_retired_reviewer === true;
  const canStart = !own && (a.status === "submitted" || (a.status === "under_review" && !a.recommendation && !mine));
  const canRecommend = !own && a.status === "under_review" && mine && !a.recommendation;
  const canDecide = !own && a.status === "under_review" && !!a.recommendation;

  async function act(path: "start-review" | "recommendation" | "decision", body: Record<string, unknown>, ok: string) {
    if (!a) return;
    setBusy(true);
    setResult(null);
    try {
      await api(`${LOANS}/review/applications/${encodeURIComponent(a.id)}/${path}`, { method: "POST", body: { ...body, version: a.version } });
      setResult({ kind: "success", text: ok });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setResult({ kind: "warning", text: `${describeError(e)} This application changed or the action is no longer valid. Reload to see the latest version.`, stale: true });
      } else {
        setResult({ kind: "error", text: describeError(e) });
      }
    } finally {
      setBusy(false);
      app.reload();
    }
  }

  const summary = a.summary;
  return (
    <div>
      <PageHeader
        title={`Application from ${a.owner_label || "applicant"}`}
        subtitle={<span className="font-mono text-xs">{a.id}</span>}
        actions={
          <>
            <Link to="/admin/loans" className="btn-secondary">
              Back to queue
            </Link>
            <button type="button" className="btn-secondary" onClick={app.reload} disabled={busy || app.loading}>
              Reload
            </button>
          </>
        }
      />

      <div className="mb-4">
        <Alert kind="warning">
          <strong>Approval is a workflow decision only</strong> — no money is disbursed, no Core loan is created and no account balance changes.
        </Alert>
      </div>

      {result && (
        <div className="mb-4">
          <Alert kind={result.kind}>
            {result.text}{" "}
            {result.stale && (
              <button type="button" className="font-semibold underline" onClick={app.reload}>
                Reload now
              </button>
            )}
          </Alert>
        </div>
      )}
      {app.error && app.data && (
        <div className="mb-4">
          <Alert kind="warning">The latest version couldn't be loaded: {describeError(app.error)}</Alert>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <section className="card space-y-5 p-5 xl:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <LoanStatus value={a.status} />
            <RecommendationBadge value={a.recommendation} />
          </div>
          <dl className="grid gap-4 sm:grid-cols-2">
            <Field label="Applicant">{a.owner_label || "—"}</Field>
            <Field label="Account">{a.account.masked_number}</Field>
            <Field label="Amount / term">
              {amount(a)} over {a.term_months} months
            </Field>
            <Field label="Declared monthly income">{money(a.monthly_income_minor, a.currency)}</Field>
            <Field label="Purpose">{a.purpose || "—"}</Field>
            <Field label="Submitted">{a.submitted_at ? formatDateTime(a.submitted_at) : "—"}</Field>
          </dl>

          <div className="rounded-lg bg-slate-50 p-4">
            <h2 className="font-semibold text-navy-900">Background summary</h2>
            <p className="mt-1 text-xs text-amber-800">Synthetic demo summary of authorised account data — not a credit decision.</p>
            {!summary ? (
              <p className="mt-2 text-sm text-slate-600">No summary available yet.</p>
            ) : (
              <>
                <p className="mt-2 text-sm">Status: {statusLabel(summary.status)}</p>
                {summary.error_code && <p className="mt-1 text-sm text-red-700">Summary failed ({summary.error_code}).</p>}
                {summary.result && (
                  <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                    {Object.entries(SUMMARY_LABELS).map(([k, label]) =>
                      typeof summary.result?.[k] === "number" ? (
                        <Field key={k} label={label}>
                          {money(summary.result[k] as number, a.currency)}
                        </Field>
                      ) : null,
                    )}
                  </dl>
                )}
              </>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-lg border border-slate-200 p-4">
              <h2 className="font-semibold text-navy-900">Review recommendation</h2>
              <p className="text-xs text-slate-500">Advisory step. It does not decide the application.</p>
              {a.recommendation ? (
                <div className="mt-2 space-y-1 text-sm">
                  <RecommendationBadge value={a.recommendation} />
                  <p>{a.recommendation_reason}</p>
                  <p className="text-xs text-slate-500">
                    By {who(a.reviewer_subject, a, me)}
                    {a.recommended_at ? ` · ${formatDateTime(a.recommended_at)}` : ""}
                  </p>
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-600">
                  {a.reviewer_subject ? `In review by ${who(a.reviewer_subject, a, me)}.` : "Not started."}
                </p>
              )}
            </div>
            <div className="rounded-lg border border-slate-200 p-4">
              <h2 className="font-semibold text-navy-900">Final decision</h2>
              <p className="text-xs text-slate-500">Binding workflow outcome. No disbursement.</p>
              {a.decision_reason ? (
                <div className="mt-2 space-y-1 text-sm">
                  <LoanStatus value={a.status} />
                  <p>{a.decision_reason}</p>
                  <p className="text-xs text-slate-500">
                    By {who(a.decided_by, a, me)}
                    {a.decided_at ? ` · ${formatDateTime(a.decided_at)}` : ""}
                  </p>
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-600">No decision yet.</p>
              )}
            </div>
          </div>

          {own && open && (
            <Alert kind="info">This is your own application. You can't review or decide it; another Operations Admin must handle it.</Alert>
          )}

          {canStart && (
            <div className="space-y-2 border-t border-slate-200 pt-4">
              {a.status === "under_review" && (
                <p className="text-sm text-slate-700">
                  {retired
                    ? `This application is still assigned to ${who(a.reviewer_subject, a, me)} from the retired Reviewer workflow. Taking over moves it to you; the previous assignment stays in the history.`
                    : `This application is in review by ${who(a.reviewer_subject, a, me)}. Taking over moves it to you; the change is recorded in the history.`}
                </p>
              )}
              <button type="button" className="btn-primary" disabled={busy} onClick={() => void act("start-review", {}, "You are now reviewing this application.")}>
                {a.status === "under_review" ? "Take over review" : "Start review"}
              </button>
            </div>
          )}

          {canRecommend && (
            <DecisionForm
              title="Review recommendation"
              options={[
                { value: "approve", label: "Recommend approval" },
                { value: "reject", label: "Recommend rejection" },
              ]}
              submitLabel="Save recommendation"
              busy={busy}
              onSubmit={(choice, reason) => void act("recommendation", { recommendation: choice, reason }, "Recommendation saved. The final decision is a separate step.")}
              note={<p className="text-xs text-slate-500">A recommendation is required before the final decision.</p>}
            />
          )}

          {canDecide && (
            <DecisionForm
              title="Final decision"
              options={[
                { value: "approved", label: "Approve application" },
                { value: "rejected", label: "Reject application" },
              ]}
              submitLabel="Record final decision"
              busy={busy}
              onSubmit={(choice, reason) => void act("decision", { decision: choice, reason }, "Final decision recorded. No money was moved.")}
              note={<p className="text-xs text-amber-800">This final decision cannot be changed afterwards. No funds are disbursed.</p>}
            />
          )}
        </section>

        <section className="card min-w-0 p-5">
          <h2 className="font-semibold text-navy-900">History</h2>
          {!a.events || a.events.length === 0 ? (
            <p className="mt-2 text-sm text-slate-600">No events recorded.</p>
          ) : (
            <ol className="mt-3 space-y-3">
              {a.events.map((e, i) => (
                <li key={i} className="border-l-2 border-teal-500 pl-3 text-sm">
                  <p className="font-medium text-navy-900">{statusLabel(e.type)}</p>
                  <p className="text-xs text-slate-500">
                    {who(e.actor, a, me)} · {formatDateTime(e.at)}
                    {e.from && e.to && e.from !== e.to ? ` · ${statusLabel(e.from)} → ${statusLabel(e.to)}` : ""}
                  </p>
                  {details(e.details, a, me) && <p className="break-words text-xs text-slate-600">{details(e.details, a, me)}</p>}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}

export default function LoanDetail() {
  const { id = "" } = useParams();
  const { loans } = useAdminAccess();
  return (
    <CapabilityGate probe={loans} allowed={canManageLoans(loans)} service="Loans">
      {loans.state === "ok" && <Detail id={id} me={loans.data} />}
    </CapabilityGate>
  );
}
