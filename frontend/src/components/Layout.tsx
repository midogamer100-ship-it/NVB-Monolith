import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import type { Role } from "../lib/types";
import { BrandMark, DemoLabel } from "./ui";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  roles: Role[];
  requiresWorkload?: boolean;
}

const icon = (d: string) => (
  <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
);

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", roles: ["customer"], icon: icon("M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10") },
  { to: "/accounts", label: "Accounts", roles: ["customer"], icon: icon("M3 7h18v12H3zM3 11h18M7 15h3") },
  { to: "/transfer", label: "Transfers", roles: ["customer"], icon: icon("M4 8h13l-3-3M20 16H7l3 3") },
  { to: "/cash", label: "Deposit & withdraw", roles: ["customer"], icon: icon("M3 7h18v10H3zM12 9.5v5M9.5 12h5M6 7V5h12v2") },
  { to: "/transactions", label: "Transactions", roles: ["customer"], icon: icon("M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01") },
  { to: "/profile", label: "Profile", roles: ["customer"], icon: icon("M12 12a4 4 0 100-8 4 4 0 000 8zM4 20a8 8 0 0116 0") },
  { to: "/operations", label: "Operations", roles: ["admin"], icon: icon("M4 19V9M10 19V5M16 19v-7M22 19H2") },
  { to: "/demo-workload", label: "Demo workload", roles: ["demo"], requiresWorkload: true, icon: icon("M13 2L4 14h7l-1 8 9-12h-7z") },
];

export default function Layout() {
  const { session, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const location = useLocation();

  useEffect(() => setOpen(false), [location.pathname]);

  if (!session) return null;
  const { user, features } = session;
  const items = NAV.filter((n) => n.roles.includes(user.role) && (!n.requiresWorkload || features.demo_workload));

  const sidebar = (
    <div className="flex h-full flex-col bg-navy-900 text-navy-100">
      <div className="px-5 py-5">
        <BrandMark inverted />
      </div>
      <nav className="flex-1 space-y-1 px-3" aria-label="Main navigation">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive ? "bg-teal-600/20 text-white ring-1 ring-inset ring-teal-500/40" : "text-navy-100 hover:bg-white/5 hover:text-white"
              }`
            }
          >
            {item.icon}
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="px-5 pb-5">
        <img src="/gbg-logo-white.png" alt="Global Brands Group" className="h-auto w-36" />
      </div>
      <div className="border-t border-white/10 px-5 py-4 text-xs text-navy-200">
        <p className="font-semibold text-white">{user.full_name ?? user.display_name}</p>
        <p className="mt-0.5 capitalize">{user.role === "customer" ? `Customer · ${user.customer_number}` : user.role === "admin" ? "Administrator" : "Demo operator"}</p>
        <p className="mt-3 leading-relaxed text-navy-300">Fictitious bank. Synthetic data. No real transactions.</p>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen lg:flex">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 lg:block">
        <div className="fixed inset-y-0 w-64">{sidebar}</div>
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-navy-950/50" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="fade-in absolute inset-y-0 left-0 w-72 shadow-xl">{sidebar}</div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur sm:px-6">
          <button
            type="button"
            className="rounded-md p-2 text-navy-800 hover:bg-slate-100 lg:hidden"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
            aria-expanded={open}
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
            </svg>
          </button>
          <img src="/rdbank-mark.svg" alt="" aria-hidden="true" className="h-8 w-8 shrink-0" />
          <DemoLabel className="hidden sm:inline-flex" />
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-sm text-slate-600 md:inline">
              Signed in as <strong className="text-navy-900">{user.display_name}</strong>
            </span>
            <button
              type="button"
              className="btn-secondary px-3 py-1.5"
              disabled={signingOut}
              onClick={async () => {
                setSigningOut(true);
                try {
                  await logout();
                } finally {
                  setSigningOut(false);
                }
              }}
            >
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </div>
        </header>
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-center text-xs font-semibold text-amber-900 sm:hidden">
          Demo environment — synthetic data
        </div>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="fade-in" key={location.pathname}>
            <Outlet />
          </div>
        </main>
        <footer className="border-t border-slate-200 px-6 py-4 text-center text-xs text-slate-500">
          R&amp;D bank is a fictitious bank for a modernization demo. All data is synthetic. Not a real financial service.
        </footer>
      </div>
    </div>
  );
}
