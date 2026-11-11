import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { BrandMark, DemoLabel } from "./ui";
import type { PasswordRule } from "../lib/validation";

/** Centered card layout for the public (signed-out) pages. */
export function AuthShell({ title, subtitle, children, wide = false }: { title: string; subtitle?: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <div className="flex min-h-screen flex-col items-center bg-slate-50 px-4 py-10 sm:justify-center">
      <div className={`w-full ${wide ? "max-w-xl" : "max-w-md"}`}>
        <div className="mb-6 flex items-center justify-between gap-3">
          <Link to="/login" aria-label="R&amp;D bank sign-in">
            <BrandMark />
          </Link>
          <DemoLabel className="hidden sm:inline-flex" />
        </div>
        <DemoLabel className="mb-4 sm:hidden" />
        <div className="card p-6 sm:p-8">
          <h1 className="text-2xl font-bold text-navy-900">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-600">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </div>
        <div className="mt-8 flex flex-col items-center gap-2">
          <img src="/gbg-logo-color.png" alt="Global Brands Group" className="h-10 w-auto" />
          <p className="text-xs font-semibold uppercase tracking-wider text-navy-600">A Global Brands Group company</p>
        </div>
        <p className="mt-6 text-center text-xs leading-relaxed text-slate-500">
          R&amp;D bank is fictitious. This environment contains synthetic data only and is not a real banking service.
        </p>
      </div>
    </div>
  );
}

export function PasswordChecklist({ rules }: { rules: PasswordRule[] }) {
  return (
    <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-2" aria-label="Password requirements">
      {rules.map((r) => (
        <li key={r.id} className={`flex items-center gap-1.5 ${r.ok ? "text-emerald-700" : "text-slate-500"}`}>
          <span aria-hidden="true">{r.ok ? "✓" : "○"}</span>
          <span>
            {r.label}
            <span className="sr-only">{r.ok ? " (met)" : " (not met)"}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="mt-1 text-sm text-red-700">
      {message}
    </p>
  );
}
