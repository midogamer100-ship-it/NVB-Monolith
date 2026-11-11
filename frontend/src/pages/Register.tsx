import { useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";
import { homePathFor, useAuth } from "../auth/AuthContext";
import { AuthShell, FieldError, PasswordChecklist } from "../components/AuthShell";
import { Alert, Spinner } from "../components/ui";
import { api, ApiError, describeError, fieldErrors } from "../lib/api";
import { formatDecimal } from "../lib/format";
import type { NewUserResult } from "../lib/types";
import { CITIES, normalizePhone, normalizeUsername, passwordOk, passwordRules, validatePerson, type PersonFields } from "../lib/validation";

interface FormState extends PersonFields {
  password: string;
  confirm: string;
}

type Errors = Partial<Record<keyof FormState, string>>;

const EMPTY: FormState = { full_name: "", username: "", email: "", phone: "+20", city: "", password: "", confirm: "" };

export default function Register() {
  const { status, session } = useAuth();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<NewUserResult | null>(null);

  if (status === "authenticated" && session) return <Navigate to={homePathFor(session.user.role)} replace />;

  const rules = passwordRules(form.password, form.username);

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  }

  function validate(): boolean {
    const errs: Errors = validatePerson(form);
    if (!passwordOk(form.password, form.username)) errs.password = "Choose a password that meets every rule below.";
    if (form.confirm !== form.password) errs.confirm = "The passwords don't match.";
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!validate()) return;
    setBusy(true);
    try {
      const r = await api<NewUserResult>("/api/auth/register", {
        method: "POST",
        skipAuthRedirect: true,
        body: {
          username: normalizeUsername(form.username),
          password: form.password,
          full_name: form.full_name.trim(),
          email: form.email.trim(),
          phone: normalizePhone(form.phone),
          city: form.city,
        },
      });
      setForm(EMPTY);
      setResult(r);
    } catch (err) {
      setForm((f) => ({ ...f, password: "", confirm: "" }));
      if (err instanceof ApiError && err.status === 409) {
        setErrors({ username: describeError(err) });
      } else if (err instanceof ApiError && err.status === 422) {
        const fe = fieldErrors(err) as Errors;
        setErrors(fe);
        if (Object.keys(fe).length === 0) setError(describeError(err));
      } else if (err instanceof ApiError && err.status === 429) {
        setError("Too many sign-up attempts from this network. Please try again later.");
      } else if (err instanceof ApiError && err.status === 404) {
        setError("Online sign-up is not available in this environment. Please contact the bank.");
      } else if (err instanceof ApiError && (err.status === 0 || err.status >= 500)) {
        setError(`${describeError(err)} Your account was not created; you can safely try again.`);
      } else {
        setError(describeError(err));
      }
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <AuthShell title="Your account is ready" subtitle={result.message}>
        <div className="rounded-xl bg-emerald-50 p-5 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-600 text-white" aria-hidden="true">
            <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M5 12l5 5L20 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <p className="mt-3 text-sm text-emerald-900">Welcome to R&amp;D bank, {result.username}.</p>
        </div>
        <dl className="mt-5 divide-y divide-slate-100 text-sm">
          <Row k="Username" v={result.username} />
          <Row k="Customer number" v={result.customer_number} />
          <Row k="New account" v={`${result.account.nickname} (${result.account.masked_number})`} />
          <Row k="Opening balance" v={formatDecimal(result.account.balance)} />
        </dl>
        <Link to="/login?registered=1" className="btn-primary mt-6 w-full py-2.5">
          Sign in
        </Link>
      </AuthShell>
    );
  }

  const field = (id: keyof FormState) => ({
    id,
    "aria-invalid": errors[id] ? true : undefined,
    "aria-describedby": errors[id] ? `${id}-error` : undefined,
    disabled: busy,
  });

  return (
    <AuthShell
      wide
      title="Create your account"
      subtitle={
        <>
          Open a free current account in a few seconds. Already a customer?{" "}
          <Link to="/login" className="font-semibold text-teal-700 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      {error && (
        <div className="mb-4">
          <Alert kind="error">{error}</Alert>
        </div>
      )}
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <div>
          <label htmlFor="full_name" className="label">
            Full name
          </label>
          <input {...field("full_name")} className="input" autoComplete="name" maxLength={120} value={form.full_name} onChange={(e) => set("full_name", e.target.value)} />
          <FieldError id="full_name-error" message={errors.full_name} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="username" className="label">
              Username
            </label>
            <input
              {...field("username")}
              className="input"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              maxLength={32}
              value={form.username}
              onChange={(e) => set("username", e.target.value)}
            />
            <FieldError id="username-error" message={errors.username} />
          </div>
          <div>
            <label htmlFor="city" className="label">
              City
            </label>
            <select {...field("city")} className="input" value={form.city} onChange={(e) => set("city", e.target.value)}>
              <option value="">Select a city</option>
              {CITIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <FieldError id="city-error" message={errors.city} />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="email" className="label">
              Email
            </label>
            <input {...field("email")} type="email" className="input" autoComplete="email" maxLength={254} value={form.email} onChange={(e) => set("email", e.target.value)} />
            <FieldError id="email-error" message={errors.email} />
          </div>
          <div>
            <label htmlFor="phone" className="label">
              Mobile number
            </label>
            <input {...field("phone")} type="tel" className="input" autoComplete="tel" maxLength={20} placeholder="+201012345678" value={form.phone} onChange={(e) => set("phone", e.target.value)} />
            <FieldError id="phone-error" message={errors.phone} />
          </div>
        </div>
        <div>
          <label htmlFor="password" className="label">
            Password
          </label>
          <input {...field("password")} type="password" className="input" autoComplete="new-password" maxLength={128} value={form.password} onChange={(e) => set("password", e.target.value)} />
          <PasswordChecklist rules={rules} />
          <FieldError id="password-error" message={errors.password} />
        </div>
        <div>
          <label htmlFor="confirm" className="label">
            Confirm password
          </label>
          <input {...field("confirm")} type="password" className="input" autoComplete="new-password" maxLength={128} value={form.confirm} onChange={(e) => set("confirm", e.target.value)} />
          <FieldError id="confirm-error" message={errors.confirm} />
        </div>
        <button type="submit" className="btn-primary w-full py-2.5" disabled={busy}>
          {busy ? (
            <>
              <Spinner className="h-4 w-4 text-white" /> Creating your account…
            </>
          ) : (
            "Create account"
          )}
        </button>
        <p className="text-xs text-slate-500">Your new current account opens with a balance of EGP 0.00. Synthetic demo data only.</p>
      </form>
    </AuthShell>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-4 py-2.5">
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-right font-medium text-navy-900">{v}</dd>
    </div>
  );
}
