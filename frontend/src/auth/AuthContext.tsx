import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, onUnauthorized, setCsrfToken } from "../lib/api";
import type { Role, SessionInfo } from "../lib/types";

type Status = "loading" | "anonymous" | "authenticated";

interface AuthValue {
  status: Status;
  session: SessionInfo | null;
  login: (username: string, password: string) => Promise<SessionInfo>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function homePathFor(role: Role): string {
  if (role === "admin") return "/operations";
  if (role === "demo") return "/demo-workload";
  return "/dashboard";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [session, setSession] = useState<SessionInfo | null>(null);
  const navigate = useNavigate();

  const apply = useCallback((s: SessionInfo | null) => {
    setCsrfToken(s?.csrf_token ?? null);
    setSession(s);
    setStatus(s ? "authenticated" : "anonymous");
  }, []);

  // Restore an existing session (cookie) on page load.
  useEffect(() => {
    api<SessionInfo>("/api/auth/me", { skipAuthRedirect: true })
      .then(apply)
      .catch(() => apply(null));
  }, [apply]);

  // Any 401 from a protected call means the server-side session is gone.
  useEffect(() => {
    onUnauthorized(() => {
      apply(null);
      navigate("/login?expired=1", { replace: true });
    });
    return () => onUnauthorized(null);
  }, [apply, navigate]);

  const login = useCallback(
    async (username: string, password: string) => {
      const s = await api<SessionInfo>("/api/auth/login", {
        method: "POST",
        body: { username, password },
        skipAuthRedirect: true,
      });
      apply(s);
      return s;
    },
    [apply],
  );

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST", skipAuthRedirect: true });
    } finally {
      apply(null);
      navigate("/login", { replace: true });
    }
  }, [apply, navigate]);

  const value = useMemo(() => ({ status, session, login, logout }), [status, session, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
