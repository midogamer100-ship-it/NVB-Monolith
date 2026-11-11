import { useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Alert, EmptyState, ErrorState, LoadingBlock, PageHeader, Spinner } from "../components/ui";
import { api, ApiError, describeError, newIdempotencyKey } from "../lib/api";
import { decimalToMinor, formatDateTime, formatDecimal, formatMinor } from "../lib/format";
import type { Account, Beneficiary, TransferPreview, TransferReceipt } from "../lib/types";
import { useApi } from "../lib/useApi";

type Step = "form" | "confirm" | "receipt";

interface FormState {
  source: string;
  destination: string; // "own:<id>" | "ben:<id>"
  amount: string;
  description: string;
}

const DESCRIPTION_RE = /^[\p{L}\p{N}_\s.,'()/#&:-]*$/u;

function buildBody(f: FormState) {
  const [kind, id] = f.destination.split(":");
  return {
    source_account_id: Number(f.source),
    beneficiary_id: kind === "ben" ? Number(id) : null,
    destination_account_id: kind === "own" ? Number(id) : null,
    amount: f.amount.trim(),
    description: f.description.trim(),
  };
}

export default function Transfer() {
  const [params] = useSearchParams();
  const accounts = useApi<{ accounts: Account[] }>("/api/accounts");
  const beneficiaries = useApi<{ beneficiaries: Beneficiary[] }>("/api/beneficiaries");

  const [step, setStep] = useState<Step>("form");
  const [form, setForm] = useState<FormState>({ source: params.get("from") ?? "", destination: "", amount: "", description: "" });
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof FormState, string>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(false);
  const [preview, setPreview] = useState<TransferPreview | null>(null);
  const [receipt, setReceipt] = useState<TransferReceipt | null>(null);
  const idemKey = useRef<string | null>(null);

  const activeAccounts = useMemo(() => (accounts.data?.accounts ?? []).filter((a) => a.status === "active"), [accounts.data]);
  const ownTargets = activeAccounts.filter((a) => String(a.id) !== form.source);
  const sourceAccount = activeAccounts.find((a) => String(a.id) === form.source);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => {
      const next = { ...f, [key]: value };
      if (key === "source" && f.destination === `own:${value}`) next.destination = "";
      return next;
    });
    setFormErrors((e) => ({ ...e, [key]: undefined }));
  }

  function validateLocally(): boolean {
    const errs: Partial<Record<keyof FormState, string>> = {};
    if (!form.source) errs.source = "Choose the account to pay from.";
    if (!form.destination) errs.destination = "Choose who to pay.";
    const minor = decimalToMinor(form.amount);
    if (minor === null) errs.amount = "Enter an amount like 1250 or 1250.50 (max two decimals).";
    else if (minor <= 0) errs.amount = "Amount must be greater than zero.";
    else if (sourceAccount && minor > sourceAccount.balance_minor) errs.amount = `Insufficient funds. Available: ${formatMinor(sourceAccount.balance_minor)}.`;
    if (form.description.length > 140) errs.description = "Maximum 140 characters.";
    else if (!DESCRIPTION_RE.test(form.description)) errs.description = "Use letters, numbers and basic punctuation only.";
    setFormErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function onReview(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!validateLocally()) return;
    setBusy(true);
    try {
      const p = await api<TransferPreview>("/api/transfers/preview", { method: "POST", body: buildBody(form) });
      setPreview(p);
      idemKey.current = newIdempotencyKey(); // one key per confirmation; reused on retry
      setRetryable(false);
      setStep("confirm");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm() {
    if (!idemKey.current) idemKey.current = newIdempotencyKey();
    setBusy(true);
    setError(null);
    try {
      const r = await api<TransferReceipt>("/api/transfers", {
        method: "POST",
        body: buildBody(form),
        headers: { "Idempotency-Key": idemKey.current },
      });
      setReceipt(r);
      setStep("receipt");
      accounts.reload();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && (err.body as TransferReceipt | null)?.status === "failed") {
        // Persisted failed attempt (e.g. insufficient funds): money did not move.
        setReceipt(err.body as TransferReceipt);
        setStep("receipt");
        accounts.reload();
      } else if (err instanceof ApiError && (err.status === 0 || err.status >= 500)) {
        // Outcome unknown: retrying with the SAME idempotency key cannot double-debit.
        setRetryable(true);
        setError(`${describeError(err)} It is safe to retry — the same request reference will be used, so you cannot be charged twice.`);
      } else {
        setError(describeError(err));
      }
    } finally {
      setBusy(false);
    }
  }

  function startOver(keepSource = true) {
    setForm({ source: keepSource ? form.source : "", destination: "", amount: "", description: "" });
    setPreview(null);
    setReceipt(null);
    setError(null);
    setRetryable(false);
    idemKey.current = null;
    setStep("form");
  }

  if (accounts.loading && !accounts.data) return <LoadingBlock label="Loading your accounts…" />;
  if (accounts.error) return <ErrorState error={accounts.error} onRetry={accounts.reload} />;

  const steps = ["Details", "Confirm", "Receipt"];
  const stepIndex = step === "form" ? 0 : step === "confirm" ? 1 : 2;

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Internal transfer" subtitle="Move money between R&amp;D bank accounts. Transfers are instant and free." />

      <ol className="mb-6 flex items-center gap-2 text-xs font-semibold" aria-label="Transfer progress">
        {steps.map((s, i) => (
          <li key={s} className="flex items-center gap-2">
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full ${
                i < stepIndex ? "bg-emerald-600 text-white" : i === stepIndex ? "bg-navy-800 text-white" : "bg-slate-200 text-slate-600"
              }`}
              aria-current={i === stepIndex ? "step" : undefined}
            >
              {i + 1}
            </span>
            <span className={i === stepIndex ? "text-navy-900" : "text-slate-500"}>{s}</span>
            {i < steps.length - 1 && <span className="mx-1 h-px w-8 bg-slate-300" aria-hidden="true" />}
          </li>
        ))}
      </ol>

      {step === "form" && (
        <form className="card space-y-5 p-6" onSubmit={onReview} noValidate>
          {activeAccounts.length === 0 && <EmptyState title="No active accounts" message="You need an active account to make a transfer." />}
          {error && <Alert kind="error">{error}</Alert>}
          <div>
            <label htmlFor="source" className="label">
              From account
            </label>
            <select id="source" className="input" value={form.source} onChange={(e) => update("source", e.target.value)} disabled={busy}>
              <option value="">Select an account</option>
              {activeAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nickname} ({a.masked_number}) — {formatMinor(a.balance_minor)}
                </option>
              ))}
            </select>
            {formErrors.source && <p className="mt-1 text-sm text-red-700">{formErrors.source}</p>}
          </div>

          <div>
            <label htmlFor="destination" className="label">
              To
            </label>
            {beneficiaries.error ? (
              <ErrorState error={beneficiaries.error} onRetry={beneficiaries.reload} title="Couldn't load beneficiaries" />
            ) : (
              <select
                id="destination"
                className="input"
                value={form.destination}
                onChange={(e) => update("destination", e.target.value)}
                disabled={busy || beneficiaries.loading}
              >
                <option value="">{beneficiaries.loading ? "Loading beneficiaries…" : "Select a beneficiary or your own account"}</option>
                {ownTargets.length > 0 && (
                  <optgroup label="My accounts">
                    {ownTargets.map((a) => (
                      <option key={`own-${a.id}`} value={`own:${a.id}`}>
                        {a.nickname} ({a.masked_number})
                      </option>
                    ))}
                  </optgroup>
                )}
                {(beneficiaries.data?.beneficiaries.length ?? 0) > 0 && (
                  <optgroup label="Saved beneficiaries">
                    {beneficiaries.data!.beneficiaries.map((b) => (
                      <option key={`ben-${b.id}`} value={`ben:${b.id}`}>
                        {b.nickname === b.holder_name ? b.holder_name : `${b.nickname} — ${b.holder_name}`} ({b.masked_number})
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
            )}
            {formErrors.destination && <p className="mt-1 text-sm text-red-700">{formErrors.destination}</p>}
          </div>

          <div>
            <label htmlFor="amount" className="label">
              Amount (EGP)
            </label>
            <div className="relative">
              <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm font-semibold text-slate-500">EGP</span>
              <input
                id="amount"
                className="input pl-12 tabular-nums"
                inputMode="decimal"
                autoComplete="off"
                placeholder="0.00"
                maxLength={13}
                value={form.amount}
                onChange={(e) => update("amount", e.target.value.replace(/[^\d.]/g, ""))}
                disabled={busy}
              />
            </div>
            {sourceAccount && !formErrors.amount && <p className="mt-1 text-xs text-slate-500">Available: {formatMinor(sourceAccount.balance_minor)}</p>}
            {formErrors.amount && <p className="mt-1 text-sm text-red-700">{formErrors.amount}</p>}
          </div>

          <div>
            <label htmlFor="description" className="label">
              Description <span className="font-normal text-slate-500">(optional)</span>
            </label>
            <input
              id="description"
              className="input"
              maxLength={140}
              placeholder="e.g. Rent for November"
              value={form.description}
              onChange={(e) => update("description", e.target.value)}
              disabled={busy}
            />
            {formErrors.description && <p className="mt-1 text-sm text-red-700">{formErrors.description}</p>}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Link to="/dashboard" className="btn-secondary">
              Cancel
            </Link>
            <button type="submit" className="btn-primary" disabled={busy || activeAccounts.length === 0}>
              {busy ? (
                <>
                  <Spinner className="h-4 w-4 text-white" /> Checking…
                </>
              ) : (
                "Review transfer"
              )}
            </button>
          </div>
        </form>
      )}

      {step === "confirm" && preview && (
        <div className="card p-6">
          <h2 className="text-lg font-semibold text-navy-900">Confirm your transfer</h2>
          <p className="mt-1 text-sm text-slate-600">Please check the details. Money moves only after you confirm.</p>
          <div className="mt-5 rounded-xl bg-navy-50 p-5 text-center">
            <p className="text-sm text-navy-700">You are sending</p>
            <p className="text-4xl font-bold tabular-nums text-navy-900">{formatDecimal(preview.amount)}</p>
          </div>
          <dl className="mt-5 divide-y divide-slate-100 text-sm">
            <Row k="From" v={`${preview.source.nickname} (${preview.source.masked_number})`} />
            <Row k="To" v={`${preview.destination.holder_name} (${preview.destination.masked_number})${preview.destination.is_own_account ? " · your account" : ""}`} />
            <Row k="Bank" v="R&amp;D bank (internal)" />
            <Row k="Fee" v={formatDecimal(preview.fee)} />
            <Row k="Description" v={preview.description || "—"} />
            <Row k="Balance after transfer" v={preview.balance_after ? formatDecimal(preview.balance_after) : "—"} />
          </dl>
          {!preview.sufficient_funds && (
            <div className="mt-4">
              <Alert kind="warning">
                Insufficient funds: the available balance is {formatDecimal(preview.source.balance)}. Reduce the amount or choose another account.
              </Alert>
            </div>
          )}
          {error && (
            <div className="mt-4">
              <Alert kind="error">{error}</Alert>
            </div>
          )}
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" className="btn-secondary" onClick={() => setStep("form")} disabled={busy}>
              Edit details
            </button>
            <button type="button" className="btn-accent" onClick={onConfirm} disabled={busy || !preview.sufficient_funds}>
              {busy ? (
                <>
                  <Spinner className="h-4 w-4 text-white" /> Sending…
                </>
              ) : retryable ? (
                "Retry transfer"
              ) : (
                "Confirm and send"
              )}
            </button>
          </div>
        </div>
      )}

      {step === "receipt" && receipt && (
        <div className="card overflow-hidden">
          <div className={`px-6 py-6 text-center ${receipt.status === "completed" ? "bg-emerald-50" : "bg-red-50"}`}>
            <div
              className={`mx-auto flex h-12 w-12 items-center justify-center rounded-full ${
                receipt.status === "completed" ? "bg-emerald-600 text-white" : "bg-red-600 text-white"
              }`}
              aria-hidden="true"
            >
              {receipt.status === "completed" ? (
                <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M5 12l5 5L20 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
                </svg>
              )}
            </div>
            <h2 className={`mt-3 text-xl font-bold ${receipt.status === "completed" ? "text-emerald-900" : "text-red-800"}`}>
              {receipt.status === "completed" ? "Transfer completed" : "Transfer not completed"}
            </h2>
            {receipt.status !== "completed" && <p className="mt-1 text-sm text-red-800">{receipt.message ?? "No money was moved."}</p>}
            <p className="mt-2 text-3xl font-bold tabular-nums text-navy-900">{formatMinor(receipt.amount_minor)}</p>
          </div>
          <dl className="divide-y divide-slate-100 px-6 py-2 text-sm">
            <Row k="Reference" v={<span className="font-mono">{receipt.reference}</span>} />
            <Row k="Status" v={receipt.status === "completed" ? "Completed" : `Failed (${(receipt.failure_reason ?? "unknown").replace(/_/g, " ")})`} />
            <Row k="From" v={`${receipt.source.nickname} (${receipt.source.masked_number})`} />
            <Row k="To" v={`${receipt.destination.holder_name} (${receipt.destination.masked_number})`} />
            <Row k="Description" v={receipt.description || "—"} />
            <Row k="Date" v={formatDateTime(receipt.completed_at ?? receipt.created_at)} />
          </dl>
          <div className="flex flex-col-reverse gap-2 border-t border-slate-200 px-6 py-4 sm:flex-row sm:justify-end">
            <Link to={`/accounts/${receipt.source.id}`} className="btn-secondary">
              View account
            </Link>
            <button type="button" className="btn-primary" onClick={() => startOver(true)}>
              Make another transfer
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
