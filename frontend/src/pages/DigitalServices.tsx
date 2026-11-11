import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, describeError, newIdempotencyKey } from "../lib/api";
import { LOANS, STATEMENTS, minorUnits, money, useDigitalAccess } from "../lib/digital";

interface Account { account_id: number; masked_number: string; currency: string; nickname?: string }
interface Statement { id: string; status: string; period: { label: string }; account: { masked_number: string }; error_code?: string | null }
interface Summary { status: string; label: string; result: Record<string, unknown> | null; error_code: string | null }
interface Loan {
  id: string; version: number; status: string; amount_minor: number; currency: string; term_months: number;
  monthly_income_minor: number; purpose: string; account: { masked_number: string };
  owner_subject?: string; owner_label?: string; reviewer_subject?: string | null;
  recommendation?: string | null; recommendation_reason?: string | null; decision_reason?: string | null;
  summary?: Summary | null; events?: { type: string; actor: string; at: string }[];
}
const errorText = (error: unknown) => error instanceof ApiError && error.status === 409
  ? `${describeError(error)} Reload the application before trying again.` : describeError(error);
function Box({ children }: { children: ReactNode }) { return <section className="card space-y-4">{children}</section>; }
function ErrorMessage({ message }: { message: string }) { return message ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{message}</p> : null; }
function Status({ value }: { value: string }) { return <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold capitalize">{value.replace(/_/g, " ")}</span>; }
function Accounts({ accounts, value, onChange }: { accounts: Account[]; value: string; onChange: (value: string) => void }) {
  return <label className="block text-sm font-medium">Account<select className="input mt-1 w-full" required value={value} onChange={e => onChange(e.target.value)}><option value="">Choose an account</option>{accounts.map(a => <option key={a.account_id} value={a.account_id}>{a.masked_number} · {a.currency}</option>)}</select></label>;
}
function useAccounts() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { const controller = new AbortController(); api<{ items: Account[] }>(`${STATEMENTS}/accounts`, { signal: controller.signal }).then(data => { if (!controller.signal.aborted) setAccounts(data.items); }, e => { if (!controller.signal.aborted) setError(errorText(e)); }); return () => controller.abort(); }, []);
  return { accounts, error };
}
function useList<T>(url: string) {
  const [items, setItems] = useState<T[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const refresh = () => setRevision(n => n + 1);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    async function load() {
      try { const data = await api<{ items: T[] }>(url, { signal: controller.signal }); if (active) { setItems(data.items); setError(""); } }
      catch (e) { if (active) setError(errorText(e)); }
      finally { if (active) setLoading(false); }
    }
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 5000);
    return () => { active = false; controller.abort(); window.clearInterval(timer); };
  }, [url, revision]);
  return { items, error, loading, refresh };
}

export function StatementsPage() {
  const { accounts, error: accountError } = useAccounts();
  const list = useList<Statement>(`${STATEMENTS}/requests?limit=100`);
  const [account, setAccount] = useState("");
  const now = new Date();
  const months = Array.from({ length: 13 }, (_, n) => { const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - n - 1, 1)); return date.toISOString().slice(0, 7); });
  const [period, setPeriod] = useState(months[0]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());
  function selectAccount(value: string) { setAccount(value); key.current = newIdempotencyKey(); }
  async function request() {
    setBusy(true); setError(""); setNotice("");
    try { await api(`${STATEMENTS}/requests`, { method: "POST", body: { account_id: Number(account), period }, headers: { "Idempotency-Key": key.current } }); key.current = newIdempotencyKey(); setNotice("Statement requested. Its status will update here."); list.refresh(); }
    catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  async function cancel(id: string) { setBusy(true); setError(""); try { await api(`${STATEMENTS}/requests/${id}/cancel`, { method: "POST" }); list.refresh(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); } }
  return <div className="space-y-6"><div><h1 className="text-2xl font-bold text-navy-900">Account statements</h1><p className="mt-1 text-slate-600">Request and download a PDF for a closed calendar month.</p></div>
    <Box><form className="grid gap-4 sm:grid-cols-3" onSubmit={e => { e.preventDefault(); void request(); }}>
      <Accounts accounts={accounts} value={account} onChange={selectAccount}/>
      <label className="text-sm font-medium">Month (Africa/Cairo)<select className="input mt-1 w-full" value={period} onChange={e => { setPeriod(e.target.value); key.current = newIdempotencyKey(); }}>{months.map(month => <option key={month}>{month}</option>)}</select></label>
      <button className="btn-primary self-end" disabled={busy || !account}>Request statement</button>
    </form><ErrorMessage message={error || accountError}/>{notice && <p role="status" className="text-sm text-teal-800">{notice}</p>}</Box>
    <Box><h2 className="text-lg font-semibold">My statements</h2><ErrorMessage message={list.error}/>{list.loading ? <p>Loading statements…</p> : !list.items.length ? <p className="text-slate-500">No statement requests yet.</p> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-3">Period</th><th>Account</th><th>Status</th><th>Action</th></tr></thead><tbody>{list.items.map(item => <tr className="border-t" key={item.id}><td className="p-3">{item.period.label}</td><td>{item.account.masked_number}</td><td><Status value={item.status}/>{item.error_code && <p className="mt-2 text-red-700">{item.error_code}</p>}</td><td>{item.status === "completed" && <a className="btn-secondary" href={`${STATEMENTS}/requests/${encodeURIComponent(item.id)}/document`}>Download PDF</a>}{item.status === "queued" && <button className="btn-secondary" disabled={busy} onClick={() => void cancel(item.id)}>Cancel</button>}</td></tr>)}</tbody></table></div>}</Box>
  </div>;
}

export function LoansPage() {
  const { accounts, error: accountError } = useAccounts();
  const list = useList<Loan>(`${LOANS}/applications`);
  const [account, setAccount] = useState(""); const [amount, setAmount] = useState(""); const [income, setIncome] = useState(""); const [term, setTerm] = useState("24"); const [purpose, setPurpose] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  async function create() {
    const requested = minorUnits(amount), declared = minorUnits(income), months = Number(term);
    if (requested === null || requested <= 0 || declared === null || !Number.isSafeInteger(months) || months <= 0) { setError("Enter valid amounts with up to two decimal places and a whole number of months."); return; }
    setBusy(true); setError(""); setNotice("");
    try { await api(`${LOANS}/applications`, { method: "POST", body: { account_id: Number(account), amount_minor: requested, term_months: months, monthly_income_minor: declared, purpose } }); setNotice("Draft saved. Submit it from My applications when ready."); list.refresh(); }
    catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  async function submit(item: Loan) { setBusy(true); setError(""); try { await api(`${LOANS}/applications/${item.id}/submit`, { method: "POST", body: { version: item.version } }); setNotice("Application submitted for review."); list.refresh(); } catch (e) { setError(errorText(e)); list.refresh(); } finally { setBusy(false); } }
  return <div className="space-y-6"><h1 className="text-2xl font-bold text-navy-900">Loan applications</h1><p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Demo workflow: approval does not disburse money or create a loan in the core.</p>
    <Box><h2 className="text-lg font-semibold">New application</h2><form className="grid gap-4 sm:grid-cols-2" onSubmit={e => { e.preventDefault(); void create(); }}>
      <Accounts accounts={accounts} value={account} onChange={setAccount}/>
      <label className="text-sm font-medium">Amount requested<input className="input mt-1 w-full" required inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)}/></label>
      <label className="text-sm font-medium">Term (months)<input className="input mt-1 w-full" required type="number" min="1" step="1" value={term} onChange={e => setTerm(e.target.value)}/></label>
      <label className="text-sm font-medium">Declared monthly income<input className="input mt-1 w-full" required inputMode="decimal" value={income} onChange={e => setIncome(e.target.value)}/></label>
      <label className="text-sm font-medium sm:col-span-2">Purpose<textarea className="input mt-1 w-full" maxLength={200} value={purpose} onChange={e => setPurpose(e.target.value)}/></label>
      <button className="btn-primary justify-self-start" disabled={busy || !account}>Save draft</button>
    </form><ErrorMessage message={error || accountError}/>{notice && <p role="status" className="text-sm text-teal-800">{notice}</p>}</Box>
    <Box><h2 className="text-lg font-semibold">My applications</h2><ErrorMessage message={list.error}/>{list.loading ? <p>Loading applications…</p> : !list.items.length ? <p className="text-slate-500">No applications yet.</p> : list.items.map(item => <article key={item.id} className="space-y-3 rounded-lg border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><strong>{money(item.amount_minor, item.currency)} · {item.term_months} months</strong><Status value={item.status}/></div><p className="text-sm text-slate-600">{item.account.masked_number} · {item.purpose}</p>{item.decision_reason && <p>Decision reason: {item.decision_reason}</p>}{item.status === "draft" && <button className="btn-primary" disabled={busy} onClick={() => void submit(item)}>Submit application</button>}</article>)}</Box>
  </div>;
}

export function LoanReviewPage() {
  const access = useDigitalAccess();
  const held = access.identity?.extension_roles ?? [];
  const allowed = held.some(role => ["reviewer", "approver", "extension_admin"].includes(role));
  if (access.loading) return <Box>Checking review access…</Box>;
  if (access.unavailable) return <Box><ErrorMessage message="Cannot verify Loans permissions. Please reload when the service is available."/></Box>;
  if (!allowed || !access.identity) return <Box><h1 className="text-xl font-semibold">Review access required</h1><p>Your identity has no loan review role.</p><Link to="/">Return to banking</Link></Box>;
  return <ReviewWorkspace subject={access.identity.subject} roles={held}/>;
}

function ReviewWorkspace({ subject, roles }: { subject: string; roles: string[] }) {
  const management = roles.some(role => ["approver", "extension_admin"].includes(role));
  const [filter, setFilter] = useState("");
  const list = useList<Loan>(`${LOANS}/review/applications${filter ? `?status=${encodeURIComponent(filter)}` : ""}`);
  const [selected, setSelected] = useState<Loan | null>(null);
  const [reviewers, setReviewers] = useState<{ subject: string; label: string }[]>([]);
  const [reviewer, setReviewer] = useState(""); const [reason, setReason] = useState("");
  const [choice, setChoice] = useState("approve"); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const selection = useRef<string | null>(null);
  useEffect(() => {
    if (!management) return;
    const controller = new AbortController();
    api<{ items: { subject: string; label: string }[] }>(`${LOANS}/review/reviewers`, { signal: controller.signal }).then(data => { if (!controller.signal.aborted) setReviewers(data.items); }, e => { if (!controller.signal.aborted) setError(errorText(e)); });
    return () => controller.abort();
  }, [management]);
  useEffect(() => () => { selection.current = null; }, []);
  async function open(id: string) {
    selection.current = id; setSelected(null); setReason(""); setReviewer(""); setError("");
    try { const item = await api<Loan>(`${LOANS}/review/applications/${id}`); if (selection.current === id) setSelected(item); } catch (e) { if (selection.current === id) setError(errorText(e)); }
  }
  async function act(action: "assign" | "recommendation" | "decision") {
    if (!selected) return;
    if (action !== "assign" && reason.trim().length < 10) { setError("Please provide a reason of at least 10 characters."); return; }
    setBusy(true); setError("");
    const body = action === "assign" ? { version: selected.version, reviewer_subject: reviewer }
      : action === "recommendation" ? { version: selected.version, recommendation: choice, reason: reason.trim() }
      : { version: selected.version, decision: choice === "approve" ? "approved" : "rejected", reason: reason.trim() };
    try { await api(`${LOANS}/review/applications/${selected.id}/${action}`, { method: "POST", body }); await open(selected.id); list.refresh(); }
    catch (e) { setError(errorText(e)); list.refresh(); } finally { setBusy(false); }
  }
  const canRecommend = !!selected && selected.status === "under_review" && roles.includes("reviewer") && selected.reviewer_subject === subject && selected.owner_subject !== subject;
  const canDecide = !!selected && selected.status === "under_review" && !!selected.recommendation && roles.includes("approver") && subject !== selected.owner_subject && subject !== selected.reviewer_subject;
  return <div className="space-y-6"><h1 className="text-2xl font-bold text-navy-900">{management ? "Loan management & decisions" : "Assigned loan reviews"}</h1>
    <Box><div className="flex flex-wrap items-center justify-between gap-3"><label>Status <select className="input" value={filter} onChange={e => setFilter(e.target.value)}><option value="">All reviewable applications</option>{["submitted", "under_review", "approved", "rejected"].map(value => <option key={value} value={value}>{value.replace(/_/g, " ")}</option>)}</select></label><button className="btn-secondary" onClick={list.refresh}>Refresh queue</button></div><p className="text-xs text-slate-500">Most recent applications, up to 200. Reviewers see only their assigned requests.</p><ErrorMessage message={list.error}/>{list.loading ? <p>Loading queue…</p> : !list.items.length ? <p>No applications in this view.</p> : list.items.map(item => <button key={item.id} disabled={busy} onClick={() => void open(item.id)} className="flex w-full flex-wrap items-center justify-between gap-3 rounded-lg border p-4 text-left hover:bg-slate-50"><span><strong>{item.owner_label || "Applicant"}</strong> · {money(item.amount_minor, item.currency)}<span className="block text-xs text-slate-500">{item.account.masked_number}</span></span><Status value={item.status}/></button>)}</Box>
    <ErrorMessage message={error}/>{selected && <Box><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Application details</h2><button className="btn-secondary" disabled={busy} onClick={() => void open(selected.id)}>Reload details</button></div><dl className="grid gap-3 text-sm sm:grid-cols-2"><div><dt className="text-slate-500">Applicant</dt><dd>{selected.owner_label}</dd></div><div><dt className="text-slate-500">Amount / term</dt><dd>{money(selected.amount_minor, selected.currency)} / {selected.term_months} months</dd></div><div><dt className="text-slate-500">Declared monthly income</dt><dd>{money(selected.monthly_income_minor, selected.currency)}</dd></div><div><dt className="text-slate-500">Purpose</dt><dd>{selected.purpose || "—"}</dd></div></dl>
      <div className="rounded-lg bg-slate-50 p-4"><h3 className="font-semibold">Background summary</h3><p className="text-sm">{selected.summary?.status ?? "No summary available"}</p>{selected.summary?.error_code && <ErrorMessage message={selected.summary.error_code}/>}<p className="mt-2 text-xs text-amber-800">Synthetic demo summary; not a credit decision.</p>{selected.summary?.result && <SummaryDetails result={selected.summary.result} currency={selected.currency}/>}</div>
      {selected.recommendation && <p className="text-sm">Reviewer recommendation: <strong>{selected.recommendation}</strong> — {selected.recommendation_reason}</p>}{selected.decision_reason && <p className="text-sm">Final decision: <strong>{selected.status}</strong> — {selected.decision_reason}</p>}
      {management && ["submitted", "under_review"].includes(selected.status) && !selected.recommendation && <form className="flex flex-wrap gap-3" onSubmit={e => { e.preventDefault(); void act("assign"); }}><label>Assign reviewer<select className="input ml-2" required value={reviewer} onChange={e => setReviewer(e.target.value)}><option value="">Select reviewer</option>{reviewers.filter(r => r.subject !== selected.owner_subject).map(r => <option key={r.subject} value={r.subject}>{r.label || r.subject}</option>)}</select></label><button className="btn-secondary" disabled={busy || !reviewer}>Assign</button></form>}
      {(canRecommend || canDecide) && <form className="space-y-3 border-t pt-4" onSubmit={e => { e.preventDefault(); void act(canDecide ? "decision" : "recommendation"); }}><h3 className="font-semibold">{canDecide ? "Final decision" : "Reviewer recommendation"}</h3><select aria-label="Recommendation or decision" className="input" value={choice} onChange={e => setChoice(e.target.value)}><option value="approve">Approve</option><option value="reject">Reject</option></select><label className="block text-sm">Reason<textarea className="input mt-1 w-full" minLength={10} maxLength={500} required value={reason} onChange={e => setReason(e.target.value)}/></label><button className="btn-primary" disabled={busy}>{canDecide ? "Record final decision" : "Save recommendation"}</button><p className="text-xs text-slate-500">Workflow decision only. No money is disbursed.</p></form>}
      <h3 className="font-semibold">Application history</h3><ol className="space-y-2 text-sm">{selected.events?.map((event, i) => <li key={i}>{event.type.replace(/_/g, " ")} · {event.actor} · {new Date(event.at).toLocaleString()}</li>)}</ol>
    </Box>}
  </div>;
}

function SummaryDetails({ result, currency }: { result: Record<string, unknown>; currency: string }) {
  const labels: Record<string, string> = { installment_minor: "Monthly instalment (no interest)", average_monthly_credits_minor: "Average monthly credits", average_monthly_debits_minor: "Average monthly debits", disposable_income_minor: "Disposable income" };
  return <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">{Object.entries(labels).map(([key, label]) => typeof result[key] === "number" ? <div key={key}><dt className="text-slate-500">{label}</dt><dd>{money(result[key] as number, currency)}</dd></div> : null)}</dl>;
}
