import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { FieldError } from "./AuthShell";
import { Alert, Badge, EmptyState, ErrorState, SkeletonRows, Spinner } from "./ui";
import { api, ApiError, describeError, fieldErrors } from "../lib/api";
import { formatDateTime, titleCase } from "../lib/format";
import type { MailboxMessage, NewUserResult } from "../lib/types";
import { useApi } from "../lib/useApi";
import { CITIES, normalizePhone, normalizeUsername, validatePerson, type PersonFields } from "../lib/validation";

const EMPTY: PersonFields = { username: "", full_name: "", email: "", phone: "+20", city: "" };

/** Admin: create a customer user. The user sets a password via a link in the demo mailbox. */
export function CreateUserCard({ onCreated }: { onCreated?: () => void }) {
  const [form, setForm] = useState<PersonFields>(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<keyof PersonFields, string>>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ kind: "success" | "error"; content: ReactNode } | null>(null);

  function set<K extends keyof PersonFields>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setResult(null);
    const errs = validatePerson(form);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const r = await api<NewUserResult>("/api/ops/users", {
        method: "POST",
        body: {
          username: normalizeUsername(form.username),
          full_name: form.full_name.trim(),
          email: form.email.trim(),
          phone: normalizePhone(form.phone),
          city: form.city,
        },
      });
      setResult({
        kind: "success",
        content: (
          <>
            Created <strong>{r.username}</strong> — customer {r.customer_number}, account {r.account.masked_number}. {r.message}
          </>
        ),
      });
      setForm(EMPTY);
      onCreated?.();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setErrors({ username: describeError(err) });
      } else if (err instanceof ApiError && err.status === 422 && Object.keys(fieldErrors(err)).length) {
        setErrors(fieldErrors(err) as Partial<Record<keyof PersonFields, string>>);
      } else {
        setResult({ kind: "error", content: describeError(err) });
      }
    } finally {
      setBusy(false);
    }
  }

  const input = (key: keyof PersonFields) => ({
    id: `cu-${key}`,
    className: "input",
    disabled: busy,
    value: form[key],
    "aria-invalid": errors[key] ? true : undefined,
    "aria-describedby": errors[key] ? `cu-${key}-error` : undefined,
  });

  return (
    <section className="card min-w-0 p-5" aria-labelledby="create-user-heading">
      <h2 id="create-user-heading" className="font-semibold text-navy-900">
        Create customer user
      </h2>
      <p className="mt-1 text-sm text-slate-600">
        Opens a customer profile and an EGP current account. The customer chooses their own password from a set-password link sent to the demo mailbox. Audited.
      </p>
      <form className="mt-4 space-y-3" onSubmit={onSubmit} noValidate>
        <div>
          <label htmlFor="cu-full_name" className="label">
            Full name
          </label>
          <input {...input("full_name")} maxLength={120} autoComplete="off" onChange={(e) => set("full_name", e.target.value)} />
          <FieldError id="cu-full_name-error" message={errors.full_name} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="cu-username" className="label">
              Username
            </label>
            <input {...input("username")} maxLength={32} autoComplete="off" autoCapitalize="none" spellCheck={false} onChange={(e) => set("username", e.target.value)} />
            <FieldError id="cu-username-error" message={errors.username} />
          </div>
          <div>
            <label htmlFor="cu-city" className="label">
              City
            </label>
            <select {...input("city")} onChange={(e) => set("city", e.target.value)}>
              <option value="">Select a city</option>
              {CITIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <FieldError id="cu-city-error" message={errors.city} />
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="cu-email" className="label">
              Email
            </label>
            <input {...input("email")} type="email" maxLength={254} autoComplete="off" onChange={(e) => set("email", e.target.value)} />
            <FieldError id="cu-email-error" message={errors.email} />
          </div>
          <div>
            <label htmlFor="cu-phone" className="label">
              Mobile number
            </label>
            <input {...input("phone")} type="tel" maxLength={20} autoComplete="off" placeholder="+201012345678" onChange={(e) => set("phone", e.target.value)} />
            <FieldError id="cu-phone-error" message={errors.phone} />
          </div>
        </div>
        {result && <Alert kind={result.kind}>{result.content}</Alert>}
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy ? (
            <>
              <Spinner className="h-4 w-4 text-white" /> Creating…
            </>
          ) : (
            "Create user"
          )}
        </button>
      </form>
    </section>
  );
}

const RESET_LINK_RE = /(https?:\/\/[^\s]*?)?(\/reset-password\?token=[A-Za-z0-9_-]+)/g;

/** Render the plain-text body; only same-origin reset links become clickable (never arbitrary URLs). */
function MessageBody({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(RESET_LINK_RE)) {
    const start = m.index ?? 0;
    if (start > last) parts.push(text.slice(last, start));
    parts.push(
      <a key={start} href={m[2]} target="_blank" rel="noopener noreferrer" className="break-all font-semibold text-teal-700 underline hover:text-teal-800">
        {m[0]}
      </a>,
    );
    last = start + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <p className="mt-2 whitespace-pre-wrap break-words text-sm text-slate-700">{parts}</p>;
}

/** Admin: demo-only mailbox that stands in for a real email provider. */
export function MailboxCard({ autoRefresh, refreshKey = 0 }: { autoRefresh: boolean; refreshKey?: number }) {
  const mailbox = useApi<{ items: MailboxMessage[] }>("/api/ops/mailbox?limit=50");
  const { reload } = mailbox;
  const [open, setOpen] = useState<string | number | null>(null);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = window.setInterval(reload, 10_000);
    return () => window.clearInterval(t);
  }, [autoRefresh, reload]);

  useEffect(() => {
    if (refreshKey) reload();
  }, [refreshKey, reload]);

  const items = mailbox.data?.items ?? [];

  return (
    <section className="card min-w-0" aria-labelledby="mailbox-heading">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
        <div>
          <h2 id="mailbox-heading" className="font-semibold text-navy-900">
            Demo mailbox
          </h2>
          <p className="text-xs text-amber-800">Demo only — stands in for a real email provider. Links here can take over the account: keep this page private.</p>
        </div>
        <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={reload} disabled={mailbox.loading}>
          {mailbox.loading ? <Spinner className="h-3 w-3" /> : null}
          Refresh
        </button>
      </div>
      {mailbox.loading && !mailbox.data && <SkeletonRows rows={3} />}
      {mailbox.error && (
        <div className="p-4">
          <ErrorState error={mailbox.error} onRetry={reload} title="Couldn't load the demo mailbox" />
        </div>
      )}
      {mailbox.data && items.length === 0 && (
        <EmptyState title="No messages yet" message="Password-reset and set-password emails appear here when customers request them." />
      )}
      {items.length > 0 && (
        <ul className="max-h-[28rem] divide-y divide-slate-100 overflow-auto">
          {items.map((m) => {
            const expanded = open === m.id;
            return (
              <li key={m.id} className="px-4 py-3">
                <button
                  type="button"
                  className="flex w-full flex-col gap-1 text-left sm:flex-row sm:items-center sm:justify-between"
                  onClick={() => setOpen(expanded ? null : m.id)}
                  aria-expanded={expanded}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-navy-900">{m.subject}</span>
                    <span className="block truncate text-xs text-slate-500">
                      To {m.to} · {m.username}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2 text-xs text-slate-500">
                    <Badge tone={m.kind === "password_reset" ? "amber" : "teal"}>{titleCase(m.kind)}</Badge>
                    {formatDateTime(m.created_at)}
                  </span>
                </button>
                {expanded && <MessageBody text={m.body} />}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
