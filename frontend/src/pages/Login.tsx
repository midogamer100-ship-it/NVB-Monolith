import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { homePathFor, useAuth } from "../auth/AuthContext";
import { ApiError, describeError } from "../lib/api";
import { Alert, BrandMark, DemoLabel, Spinner } from "../components/ui";

export default function Login() {
  const { status, session, login } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "authenticated" && session) {
    return <Navigate to={homePathFor(session.user.role)} replace />;
  }

  const expired = params.get("expired") === "1";

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setSubmitting(true);
    try {
      const s = await login(username.trim(), password);
      navigate(homePathFor(s.user.role), { replace: true });
    } catch (err) {
      setPassword("");
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many failed sign-in attempts. Please wait a few minutes and try again.");
      } else if (err instanceof ApiError && err.status === 401) {
        setError("Invalid username or password.");
      } else {
        setError(describeError(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <section className="relative hidden flex-1 flex-col justify-between overflow-hidden bg-navy-900 p-12 text-white lg:flex">
        <div className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-teal-500/10" aria-hidden="true" />
        <div className="absolute -bottom-32 -left-16 h-80 w-80 rounded-full bg-navy-700/60" aria-hidden="true" />
        <div className="relative">
          <BrandMark inverted />
        </div>
        <div className="relative max-w-md">
          <h1 className="text-4xl font-bold leading-tight">Banking that grows with the valley.</h1>
          <p className="mt-4 text-navy-200">
            This is the Nova Valley Bank modernization demo — the same application running on a virtual machine and as containers on
            OpenShift.
          </p>
        </div>
        <p className="relative text-xs text-navy-300">Fictitious bank · Synthetic data only · No real financial transactions</p>
      </section>

      <section className="flex flex-1 flex-col items-center justify-center bg-white px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <BrandMark />
          </div>
          <DemoLabel className="mb-6" />
          <h2 className="text-2xl font-bold text-navy-900">Sign in to online banking</h2>
          <p className="mt-1 text-sm text-slate-600">Use the demo credentials issued by your presenter.</p>

          <div className="mt-6 space-y-3">
            {expired && !error && <Alert kind="info">Your session has expired. Please sign in again.</Alert>}
            {error && <Alert kind="error">{error}</Alert>}
          </div>

          <form className="mt-6 space-y-4" onSubmit={onSubmit} noValidate>
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
                disabled={submitting}
                required
              />
            </div>
            <div>
              <label htmlFor="password" className="label">
                Password
              </label>
              <input
                id="password"
                type="password"
                className="input"
                autoComplete="current-password"
                maxLength={256}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
                required
              />
            </div>
            <button type="submit" className="btn-primary w-full py-2.5" disabled={submitting || status === "loading"}>
              {submitting ? (
                <>
                  <Spinner className="h-4 w-4 text-white" /> Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </button>
          </form>
          <p className="mt-8 text-xs leading-relaxed text-slate-500">
            Nova Valley Bank is fictitious. This environment contains synthetic data only and is not a real banking service.
          </p>
        </div>
      </section>
    </div>
  );
}
