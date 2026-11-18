/**
 * Operations Admin permission resolution.
 *
 * The browser never decides what an admin may do: both extension services resolve the caller
 * from the Core session (via the Core Adapter) and return server-side `capabilities`. This
 * module only loads them so pages can show the right screen; every API still enforces them.
 */

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { EmptyState, LoadingBlock } from "../../components/ui";
import { api, ApiError, describeError } from "../../lib/api";
import { LOANS, STATEMENTS } from "../../lib/digital";

export interface LoansMe {
  subject: string;
  username: string;
  display_name: string | null;
  core_role: string;
  extension_roles: string[];
  effective_roles?: string[];
  capabilities?: {
    loan_management?: boolean;
    batch_operations?: boolean;
    role_admin?: boolean;
    legacy_reviewer_workflow?: boolean;
  };
}

export interface StatementsMe {
  subject: string;
  username: string;
  core_role: string;
  extension_roles: string[];
  effective_roles?: string[];
  capabilities?: { statement_operations?: boolean; batch_operations?: boolean; role_admin?: boolean };
}

export type Probe<T> =
  | { state: "loading" }
  | { state: "ok"; data: T }
  | { state: "unavailable"; message: string }
  | { state: "denied"; message: string };

interface AdminAccess {
  loans: Probe<LoansMe>;
  statements: Probe<StatementsMe>;
  reload: () => void;
}

const Ctx = createContext<AdminAccess | null>(null);

function classify<T>(err: unknown): Probe<T> {
  if (err instanceof ApiError && (err.status === 403 || err.status === 404)) {
    return { state: "denied", message: describeError(err) };
  }
  // 401 is handled globally by the api helper (session-expired redirect).
  return { state: "unavailable", message: describeError(err) };
}

export function AdminAccessProvider({ children }: { children: ReactNode }) {
  const [loans, setLoans] = useState<Probe<LoansMe>>({ state: "loading" });
  const [statements, setStatements] = useState<Probe<StatementsMe>>({ state: "loading" });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoans({ state: "loading" });
    setStatements({ state: "loading" });
    api<LoansMe>(`${LOANS}/me`, { signal: ctrl.signal }).then(
      (data) => !ctrl.signal.aborted && setLoans({ state: "ok", data }),
      (e) => !ctrl.signal.aborted && !(e instanceof DOMException) && setLoans(classify<LoansMe>(e)),
    );
    api<StatementsMe>(`${STATEMENTS}/me`, { signal: ctrl.signal }).then(
      (data) => !ctrl.signal.aborted && setStatements({ state: "ok", data }),
      (e) => !ctrl.signal.aborted && !(e instanceof DOMException) && setStatements(classify<StatementsMe>(e)),
    );
    return () => ctrl.abort();
  }, [nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return <Ctx.Provider value={{ loans, statements, reload }}>{children}</Ctx.Provider>;
}

export function useAdminAccess(): AdminAccess {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAdminAccess must be used inside AdminAccessProvider");
  return ctx;
}

export const canManageLoans = (p: Probe<LoansMe>) => p.state === "ok" && p.data.capabilities?.loan_management === true;
export const canOperateStatements = (p: Probe<StatementsMe>) =>
  p.state === "ok" && p.data.capabilities?.statement_operations === true;

/** Neutral gate: loader while resolving, explicit screens when unavailable or not granted. */
export function CapabilityGate({
  probe,
  allowed,
  service,
  children,
}: {
  probe: Probe<unknown>;
  allowed: boolean;
  service: string;
  children: ReactNode;
}) {
  const { reload } = useAdminAccess();
  if (probe.state === "loading") return <LoadingBlock label="Checking your permissions…" />;
  if (probe.state === "unavailable") {
    return (
      <div className="card">
        <EmptyState
          title={`${service} is temporarily unavailable`}
          message="Your permissions could not be verified right now. Nothing has changed; please try again shortly."
          action={
            <button type="button" className="btn-primary" onClick={reload}>
              Try again
            </button>
          }
        />
      </div>
    );
  }
  if (!allowed) {
    return (
      <div className="card">
        <EmptyState
          title="Access not granted"
          message={`Your account does not hold the Operations Admin role for ${service}. An Operations Admin role assignment is required; ask the platform team (see the role handover document).`}
          action={
            <Link to="/admin" className="btn-secondary">
              Back to overview
            </Link>
          }
        />
      </div>
    );
  }
  return <>{children}</>;
}
