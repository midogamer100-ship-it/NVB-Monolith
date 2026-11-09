import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AuthShell, FieldError, PasswordChecklist } from "../components/AuthShell";
import { Alert, Spinner } from "../components/ui";
import { api, ApiError, describeError, fieldErrors } from "../lib/api";
import { passwordOk, passwordRules } from "../lib/validation";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [errors, setErrors] = useState<{ password?: string; confirm?: string }>({});

  // The username is unknown on this page; the server also rejects passwords containing it.
  const rules = passwordRules(password, "");

  if (!token || token.length > 256) {
    return (
      <AuthShell title="Reset link missing" subtitle="This page needs the one-time link from your reset email.">
        <Alert kind="error">The link is incomplete. Open the full link from the email, or request a new one.</Alert>
        <Link to="/forgot-password" className="btn-primary mt-5 w-full py-2.5">
          Request a new link
        </Link>
      </AuthShell>
    );
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const errs: typeof errors = {};
    if (!passwordOk(password, "")) errs.password = "Choose a password that meets every rule below.";
    if (confirm !== password) errs.confirm = "The passwords don't match.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await api("/api/auth/password/reset", {
        method: "POST",
        body: { token, new_password: password },
        skipAuthRedirect: true,
      });
      navigate("/login?reset=1", { replace: true });
    } catch (err) {
      setPassword("");
      setConfirm("");
      if (err instanceof ApiError && err.status === 400) {
        setExpired(true);
        setError(describeError(err));
      } else if (err instanceof ApiError && err.status === 422) {
        const fe = fieldErrors(err);
        if (fe.new_password) setErrors({ password: fe.new_password });
        else setError(describeError(err));
      } else {
        setError(describeError(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Choose a new password" subtitle="Set a new password for your Nova Valley Bank sign-in. All your other sessions will be signed out.">
      {error && (
        <div className="mb-4 space-y-3">
          <Alert kind="error">{error}</Alert>
          {expired && (
            <Link to="/forgot-password" className="btn-secondary w-full">
              Request a new link
            </Link>
          )}
        </div>
      )}
      {!expired && (
        <form className="space-y-4" onSubmit={onSubmit} noValidate>
          <div>
            <label htmlFor="new-password" className="label">
              New password
            </label>
            <input
              id="new-password"
              type="password"
              className="input"
              autoComplete="new-password"
              maxLength={128}
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setErrors((x) => ({ ...x, password: undefined }));
              }}
              aria-invalid={errors.password ? true : undefined}
              aria-describedby={errors.password ? "new-password-error" : undefined}
              disabled={busy}
            />
            <PasswordChecklist rules={rules.filter((r) => r.id !== "username")} />
            <p className="mt-1 text-xs text-slate-500">It also must not contain your username.</p>
            <FieldError id="new-password-error" message={errors.password} />
          </div>
          <div>
            <label htmlFor="confirm-password" className="label">
              Confirm new password
            </label>
            <input
              id="confirm-password"
              type="password"
              className="input"
              autoComplete="new-password"
              maxLength={128}
              value={confirm}
              onChange={(e) => {
                setConfirm(e.target.value);
                setErrors((x) => ({ ...x, confirm: undefined }));
              }}
              aria-invalid={errors.confirm ? true : undefined}
              aria-describedby={errors.confirm ? "confirm-password-error" : undefined}
              disabled={busy}
            />
            <FieldError id="confirm-password-error" message={errors.confirm} />
          </div>
          <button type="submit" className="btn-primary w-full py-2.5" disabled={busy}>
            {busy ? (
              <>
                <Spinner className="h-4 w-4 text-white" /> Saving…
              </>
            ) : (
              "Save new password"
            )}
          </button>
        </form>
      )}
      <p className="mt-5 text-center text-sm">
        <Link to="/login" className="font-semibold text-teal-700 hover:underline">
          Back to sign in
        </Link>
      </p>
    </AuthShell>
  );
}
