import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AuthShell } from "../components/AuthShell";
import { Alert, Spinner } from "../components/ui";
import { api, ApiError, describeError } from "../lib/api";
import { normalizeUsername } from "../lib/validation";

const GENERIC = "If that account exists, we've sent password reset instructions to its registered email.";

export default function ForgotPassword() {
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const name = normalizeUsername(username);
    if (!name) {
      setError("Enter your username.");
      return;
    }
    setBusy(true);
    try {
      const r = await api<{ message?: string }>("/api/auth/password/forgot", {
        method: "POST",
        body: { username: name },
        skipAuthRedirect: true,
      });
      setSent(r?.message ?? GENERIC);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) setError("Enter a valid username.");
      else setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Forgot your password?" subtitle="Enter your username and we'll send a one-time reset link to the email registered on your account.">
      {sent ? (
        <div className="space-y-4">
          <Alert kind="success">{sent}</Alert>
          <Alert kind="info">
            <strong>Demo environment:</strong> no real email is sent. The reset email arrives in the administrator's <em>Demo mailbox</em> on the Operations page.
            The link is valid for 15 minutes and can be used once.
          </Alert>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Link to="/login" className="btn-primary flex-1">
              Back to sign in
            </Link>
            <button
              type="button"
              className="btn-secondary flex-1"
              onClick={() => {
                setSent(null);
                setUsername("");
              }}
            >
              Send another link
            </button>
          </div>
        </div>
      ) : (
        <form className="space-y-4" onSubmit={onSubmit} noValidate>
          {error && <Alert kind="error">{error}</Alert>}
          <div>
            <label htmlFor="username" className="label">
              Username
            </label>
            <input
              id="username"
              className="input"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              maxLength={64}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={busy}
            />
          </div>
          <button type="submit" className="btn-primary w-full py-2.5" disabled={busy}>
            {busy ? (
              <>
                <Spinner className="h-4 w-4 text-white" /> Sending…
              </>
            ) : (
              "Send reset link"
            )}
          </button>
          <p className="text-center text-sm">
            <Link to="/login" className="font-semibold text-teal-700 hover:underline">
              Back to sign in
            </Link>
          </p>
        </form>
      )}
    </AuthShell>
  );
}
