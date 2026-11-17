import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, describeError, newIdempotencyKey } from "../lib/api";
import { LOANS, STATEMENTS, minorUnits, money } from "../lib/digital";

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
