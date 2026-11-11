import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { api } from "./api";

export const STATEMENTS = "/x/statements/v1";
export const LOANS = "/x/loans/v1";
export interface DigitalIdentity { subject: string; extension_roles: string[] }
export function useDigitalAccess() {
  const { session } = useAuth();
  const [access, setAccess] = useState<{ username: string; loans: DigitalIdentity | null; unavailable: boolean } | null>(null);
  const username = session?.user.username;
  useEffect(() => {
    setAccess(null);
    if (!username) return;
    const controller = new AbortController();
    api<DigitalIdentity>(`${LOANS}/me`, { signal: controller.signal }).then(
      loans => { if (!controller.signal.aborted) setAccess({ username, loans, unavailable: false }); },
      () => { if (!controller.signal.aborted) setAccess({ username, loans: null, unavailable: true }); },
    );
    return () => controller.abort();
  }, [username]);
  const current = access?.username === username ? access : null;
  return { identity: current?.loans ?? null, loading: !!username && !current, unavailable: current?.unavailable ?? false };
}

export function minorUnits(value: string): number | null {
  const match = /^(\d{1,12})(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!match) return null;
  const amount = Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  return Number.isSafeInteger(amount) ? amount : null;
}

export function money(amount: number, currency: string) {
  return new Intl.NumberFormat("en", { style: "currency", currency }).format(amount / 100);
}
