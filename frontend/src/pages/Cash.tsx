import { useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Alert, EmptyState, ErrorState, LoadingBlock, PageHeader, Spinner } from "../components/ui";
import { api, ApiError, describeError, newIdempotencyKey } from "../lib/api";
import { decimalToMinor, formatDateTime, formatMinor } from "../lib/format";
import type { Account, CashReceipt } from "../lib/types";
import { useApi } from "../lib/useApi";

type Mode = "deposit" | "withdraw";
type Step = "form" | "confirm" | "receipt";

const DESCRIPTION_RE = /^[\p{L}\p{N}_\s.,'()/#&:-]*$/u;
/** Per-operation limits (server defaults: NVB_MAX_DEPOSIT_MINOR / NVB_MAX_WITHDRAWAL_MINOR). */
const LIMIT_MINOR: Record<Mode, number> = { deposit: 10_000_000, withdraw: 5_000_000 };
const COPY: Record<Mode, { title: string; verb: string; action: string; done: string; failed: string }> = {
  deposit: { title: "Deposit", verb: "deposit", action: "Confirm deposit", done: "Deposit completed", failed: "Deposit not completed" },
  withdraw: { title: "Withdraw", verb: "withdraw", action: "Confirm withdrawal", done: "Withdrawal completed", failed: "Withdrawal not completed" },
};

function parseMode(v: string | null): Mode {
  return v === "withdraw" || v === "withdrawal" ? "withdraw" : "deposit";
}

export default function Cash() {
  const [params, setParams] = useSearchParams();
  const accounts = useApi<{ accounts: Account[] }>("/api/accounts");
  const [mode, setMode] = useState<Mode>(parseMode(params.get("kind")));
  const [accountId, setAccountId] = useState(params.get("account") ?? "");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [formErrors, setFormErrors] = useState<{ account?: string; amount?: string; description?: string }>({});
  const [step, setStep] = useState<Step>("form");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(false);
  const [receipt, setReceipt] = useState<CashReceipt | null>(null);
  const idemKey = useRef<string | null>(null);

  const active = useMemo(() => (accounts.data?.accounts ?? []).filter((a) => a.status === "active"), [accounts.data]);
  const account = active.find((a) => String(a.id) === accountId);
  const amountMinor = decimalToMinor(amount);
  const copy = COPY[mode];

  function switchMode(next: Mode) {
    if (step !== "form" || busy) return;
    setMode(next);
    setFormErrors({});
    setError(null);
    const p = new URLSearchParams(params);
    p.set("kind", next);
    setParams(p, { replace: true });
  }

  function validate(): boolean {
    const errs: typeof formErrors = {};
    if (!account) errs.account = "Choose an account.";
    if (amountMinor === null) errs.amount = "Enter an amount like 500 or 500.50 (max two decimals).";
    else if (amountMinor <= 0) errs.amount = "Amount must be greater than zero.";
    else if (amountMinor > LIMIT_MINOR[mode]) errs.amount = `The limit per ${copy.verb} is ${formatMinor(LIMIT_MINOR[mode])}.`;
    else if (mode === "withdraw" && account && amountMinor > account.balance_minor)
      errs.amount = `Insufficient funds. Available: ${formatMinor(account.balance_minor)}.`;
    if (description.length > 140) errs.description = "Maximum 140 characters.";
    else if (!DESCRIPTION_RE.test(description)) errs.description = "Use letters, numbers and basic punctuation only.";
    setFormErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function onReview(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!validate()) return;
    idemKey.current = newIdempotencyKey(); // one key per confirmation; reused on retry
    setRetryable(false);
    setStep("confirm");
  }

  async function onConfirm() {
    if (!account) return;
    if (!idemKey.current) idemKey.current = newIdempotencyKey();
    setBusy(true);
    setError(null);
    try {
      const r = await api<CashReceipt>(`/api/accounts/${account.id}/${mode}`, {
        method: "POST",
        body: { amount: amount.trim(), description: description.trim() },
        headers: { "Idempotency-Key": idemKey.current },
      });
      setReceipt(r);
      setStep("receipt");
      accounts.reload();
    } catch (err) {
      const body = err instanceof ApiError ? (err.body as CashReceipt | null) : null;
      if (err instanceof ApiError && err.status === 422 && body?.status === "failed") {
        // Persisted failed withdrawal (insufficient funds): no money moved.
        setReceipt(body);
        setStep("receipt");
        accounts.reload();
      } else if (err instanceof ApiError && (err.status === 0 || err.status >= 500)) {
        setRetryable(true);
        setError(`${describeError(err)} It is safe to retry — the same request reference is reused, so it cannot be applied twice.`);
      } else {
        setError(describeError(err));
      }
    } finally {
      setBusy(false);
    }
  }

  function startOver() {
    setAmount("");
    setDescription("");
    setReceipt(null);
    setError(null);
    setRetryable(false);
    idemKey.current = null;
    setStep("form");
  }

  if (accounts.loading && !accounts.data) return <LoadingBlock label="Loading your accounts…" />;
  if (accounts.error) return <ErrorState error={accounts.error} onRetry={accounts.reload} />;

  const balanceAfter = account && amountMinor !== null ? account.balance_minor + (mode === "deposit" ? amountMinor : -amountMinor) : null;

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="Deposit & withdraw"
        subtitle="Simulated branch cash operations for this demo. No real money is involved."
      />

      <div className="mb-6 inline-flex rounded-lg bg-slate-100 p-1" role="tablist" aria-label="Operation type">
        {(["deposit", "withdraw"] as Mode[]).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            disabled={step !== "form" || busy}
            onClick={() => switchMode(m)}
            className={`rounded-md px-5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${
              mode === m ? "bg-white text-navy-900 shadow-sm" : "text-slate-600 hover:text-navy-900"
            }`}
          >
            {COPY[m].title}
          </button>
        ))}
      </div>

      {step === "form" && (
        <form className="card space-y-5 p-6" onSubmit={onReview} noValidate>
          {active.length === 0 && <EmptyState title="No active accounts" message={`You need an active account to ${copy.verb}.`} />}
          {error && <Alert kind="error">{error}</Alert>}
          <div>
            <label htmlFor="cash-account" className="label">
              {mode === "deposit" ? "Deposit into" : "Withdraw from"}
            </label>
            <select
              id="cash-account"
              className="input"
              value={accountId}
              onChange={(e) => {
                setAccountId(e.target.value);
                setFormErrors((x) => ({ ...x, account: undefined, amount: undefined }));
              }}
              disabled={busy}
            >
              <option value="">Select an account</option>
              {active.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nickname} ({a.masked_number}) — {formatMinor(a.balance_minor)}
                </option>
              ))}
            </select>
            {formErrors.account && <p className="mt-1 text-sm text-red-700">{formErrors.account}</p>}
          </div>

          <div>
            <label htmlFor="cash-amount" className="label">
              Amount (EGP)
            </label>
            <div className="relative">
              <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm font-semibold text-slate-500">EGP</span>
              <input
                id="cash-amount"
                className="input pl-12 tabular-nums"
                inputMode="decimal"
                autoComplete="off"
                placeholder="0.00"
                maxLength={13}
                value={amount}
                onChange={(e) => {
                  setAmount(e.target.value.replace(/[^\d.]/g, ""));
                  setFormErrors((x) => ({ ...x, amount: undefined }));
                }}
                disabled={busy}
              />
            </div>
            {!formErrors.amount && (
              <p className="mt-1 text-xs text-slate-500">
                Limit per {copy.verb}: {formatMinor(LIMIT_MINOR[mode])}
                {account && mode === "withdraw" ? ` · Available: ${formatMinor(account.balance_minor)}` : ""}
              </p>
            )}
            {formErrors.amount && <p className="mt-1 text-sm text-red-700">{formErrors.amount}</p>}
          </div>

          <div>
            <label htmlFor="cash-description" className="label">
              Description <span className="font-normal text-slate-500">(optional)</span>
            </label>
            <input
              id="cash-description"
              className="input"
              maxLength={140}
              placeholder={mode === "deposit" ? "e.g. Cash deposit at branch" : "e.g. Cash for travel"}
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
                setFormErrors((x) => ({ ...x, description: undefined }));
              }}
              disabled={busy}
            />
            {formErrors.description && <p className="mt-1 text-sm text-red-700">{formErrors.description}</p>}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Link to="/dashboard" className="btn-secondary">
              Cancel
            </Link>
            <button type="submit" className="btn-primary" disabled={busy || active.length === 0}>
              Review {copy.verb}
            </button>
          </div>
        </form>
      )}

      {step === "confirm" && account && amountMinor !== null && (
        <div className="card p-6">
          <h2 className="text-lg font-semibold text-navy-900">Confirm your {mode === "deposit" ? "deposit" : "withdrawal"}</h2>
          <p className="mt-1 text-sm text-slate-600">Please check the details. Nothing changes until you confirm.</p>
          <div className={`mt-5 rounded-xl p-5 text-center ${mode === "deposit" ? "bg-teal-50" : "bg-navy-50"}`}>
            <p className="text-sm text-navy-700">You are {mode === "deposit" ? "depositing" : "withdrawing"}</p>
            <p className="text-4xl font-bold tabular-nums text-navy-900">{formatMinor(amountMinor)}</p>
          </div>
          <dl className="mt-5 divide-y divide-slate-100 text-sm">
            <Row k="Account" v={`${account.nickname} (${account.masked_number})`} />
            <Row k="Current balance" v={formatMinor(account.balance_minor)} />
            <Row k="Balance after" v={balanceAfter !== null ? formatMinor(balanceAfter) : "—"} />
            <Row k="Description" v={description.trim() || (mode === "deposit" ? "Cash deposit" : "Cash withdrawal")} />
            <Row k="Channel" v="NVB Branch (demo)" />
          </dl>
          {error && (
            <div className="mt-4">
              <Alert kind="error">{error}</Alert>
            </div>
          )}
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" className="btn-secondary" onClick={() => setStep("form")} disabled={busy}>
              Edit details
            </button>
            <button type="button" className="btn-accent" onClick={onConfirm} disabled={busy}>
              {busy ? (
                <>
                  <Spinner className="h-4 w-4 text-white" /> Processing…
                </>
              ) : retryable ? (
                "Retry"
              ) : (
                copy.action
              )}
            </button>
          </div>
        </div>
      )}

      {step === "receipt" && receipt && (
        <div className="card overflow-hidden">
          <div className={`px-6 py-6 text-center ${receipt.status === "completed" ? "bg-teal-50" : "bg-red-50"}`}>
            <div
              className={`mx-auto flex h-12 w-12 items-center justify-center rounded-full ${receipt.status === "completed" ? "bg-teal-600" : "bg-red-600"} text-white`}
              aria-hidden="true"
            >
              <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.5">
                {receipt.status === "completed" ? <path d="M5 12l5 5L20 7" strokeLinecap="round" strokeLinejoin="round" /> : <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />}
              </svg>
            </div>
            <h2 className={`mt-3 text-xl font-bold ${receipt.status === "completed" ? "text-teal-900" : "text-red-800"}`}>
              {receipt.status === "completed" ? copy.done : copy.failed}
            </h2>
            {receipt.status !== "completed" && <p className="mt-1 text-sm text-red-800">{receipt.message ?? "No money was moved."}</p>}
            <p className="mt-2 text-3xl font-bold tabular-nums text-navy-900">{formatMinor(receipt.amount_minor)}</p>
          </div>
          <dl className="divide-y divide-slate-100 px-6 py-2 text-sm">
            <Row k="Reference" v={<span className="font-mono">{receipt.reference}</span>} />
            <Row k="Type" v={receipt.kind === "deposit" ? "Cash deposit" : "Cash withdrawal"} />
            <Row
              k="Status"
              v={receipt.status === "completed" ? "Completed" : `Failed (${(receipt.failure_reason ?? "unknown").replace(/_/g, " ")})`}
            />
            <Row k="Account" v={`${receipt.account.nickname} (${receipt.account.masked_number})`} />
            <Row k={receipt.status === "completed" ? "New balance" : "Balance"} v={formatMinor(receipt.account.balance_minor)} />
            <Row k="Description" v={receipt.description || "—"} />
            <Row k="Date" v={formatDateTime(receipt.created_at)} />
          </dl>
          <div className="flex flex-col-reverse gap-2 border-t border-slate-200 px-6 py-4 sm:flex-row sm:justify-end">
            <Link to={`/accounts/${receipt.account.id}`} className="btn-secondary">
              View account
            </Link>
            <button type="button" className="btn-primary" onClick={startOver}>
              New {mode === "deposit" ? "deposit" : "withdrawal"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-2.5">
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-right font-medium text-navy-900">{v}</dd>
    </div>
  );
}
