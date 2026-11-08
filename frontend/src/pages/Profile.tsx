import { useEffect, useState, type FormEvent } from "react";
import { Alert, ErrorState, LoadingBlock, PageHeader, Spinner } from "../components/ui";
import { api, describeError, fieldErrors } from "../lib/api";
import { formatDate, formatDateTime } from "../lib/format";
import type { Profile as ProfileData } from "../lib/types";
import { useApi } from "../lib/useApi";

type Editable = "preferred_name" | "email" | "phone" | "city";
type Draft = Record<Editable, string>;

function toDraft(p: ProfileData): Draft {
  return { preferred_name: p.preferred_name ?? "", email: p.email, phone: p.phone, city: p.city };
}

export default function Profile() {
  const { data, error, loading, reload } = useApi<ProfileData>("/api/profile");
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<{ kind: "success" | "error" | "info"; text: string } | null>(null);

  useEffect(() => {
    if (data) {
      setProfile(data);
      setDraft(toDraft(data));
    }
  }, [data]);

  if (loading && !profile) return <LoadingBlock label="Loading profile…" />;
  if (error && !profile) return <ErrorState error={error} onRetry={reload} />;
  if (!profile || !draft) return null;

  const original = toDraft(profile);
  const changed = (Object.keys(draft) as Editable[]).filter((k) => draft[k].trim() !== original[k]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    if (!draft) return;
    setResult(null);
    setErrors({});
    if (changed.length === 0) {
      setResult({ kind: "info", text: "There are no changes to save." });
      return;
    }
    const body: Partial<Draft> = {};
    for (const k of changed) body[k] = draft[k].trim();
    setSaving(true);
    try {
      const res = await api<{ profile: ProfileData; changed: string[] }>("/api/profile", { method: "PATCH", body });
      setProfile(res.profile);
      setDraft(toDraft(res.profile));
      setResult(
        res.changed.length
          ? { kind: "success", text: `Profile updated: ${res.changed.map((f) => f.replace(/_/g, " ")).join(", ")}.` }
          : { kind: "info", text: "Nothing changed on the server." },
      );
    } catch (err) {
      const fe = fieldErrors(err);
      setErrors(fe);
      setResult({ kind: "error", text: Object.keys(fe).length ? "Please correct the highlighted fields." : describeError(err) });
    } finally {
      setSaving(false);
    }
  }

  const field = (k: Editable) => ({
    id: k,
    value: draft[k],
    disabled: saving,
    "aria-invalid": Boolean(errors[k]),
    onChange: (e: { target: { value: string } }) => setDraft((d) => (d ? { ...d, [k]: e.target.value } : d)),
  });

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Profile" subtitle="Your personal details. Some fields can only be changed by visiting a branch." />

      <section className="card p-6">
        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-navy-800 text-lg font-bold text-white" aria-hidden="true">
            {profile.full_name
              .split(" ")
              .slice(0, 2)
              .map((s) => s[0])
              .join("")}
          </div>
          <div>
            <p className="text-lg font-semibold text-navy-900">{profile.full_name}</p>
            <p className="text-sm text-slate-600">
              {profile.segment} customer · {profile.customer_number}
            </p>
          </div>
        </div>
        <dl className="mt-6 grid gap-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-slate-500">Username</dt>
            <dd className="font-medium text-navy-900">{profile.username}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Member since</dt>
            <dd className="font-medium text-navy-900">{formatDate(profile.member_since)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Last sign-in</dt>
            <dd className="font-medium text-navy-900">{profile.last_login_at ? formatDateTime(profile.last_login_at) : "—"}</dd>
          </div>
        </dl>
      </section>

      <form className="card mt-6 space-y-5 p-6" onSubmit={onSave} noValidate>
        <h2 className="text-lg font-semibold text-navy-900">Contact details</h2>
        {result && <Alert kind={result.kind}>{result.text}</Alert>}
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="preferred_name" className="label">
              Preferred name
            </label>
            <input className="input" maxLength={60} placeholder="How should we greet you?" {...field("preferred_name")} />
            {errors.preferred_name && <p className="mt-1 text-sm text-red-700">{errors.preferred_name}</p>}
          </div>
          <div>
            <label htmlFor="city" className="label">
              City
            </label>
            <select className="input" {...field("city")}>
              {profile.cities.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            {errors.city && <p className="mt-1 text-sm text-red-700">{errors.city}</p>}
          </div>
          <div>
            <label htmlFor="email" className="label">
              Email
            </label>
            <input type="email" className="input" maxLength={254} autoComplete="email" {...field("email")} />
            {errors.email && <p className="mt-1 text-sm text-red-700">{errors.email}</p>}
          </div>
          <div>
            <label htmlFor="phone" className="label">
              Mobile number
            </label>
            <input type="tel" className="input" maxLength={20} placeholder="+201XXXXXXXXX" autoComplete="tel" {...field("phone")} />
            {errors.phone ? <p className="mt-1 text-sm text-red-700">{errors.phone}</p> : <p className="mt-1 text-xs text-slate-500">Egyptian mobile, e.g. +201012345678</p>}
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="btn-secondary"
            disabled={saving || changed.length === 0}
            onClick={() => {
              setDraft(original);
              setErrors({});
              setResult(null);
            }}
          >
            Discard changes
          </button>
          <button type="submit" className="btn-primary" disabled={saving || changed.length === 0}>
            {saving ? (
              <>
                <Spinner className="h-4 w-4 text-white" /> Saving…
              </>
            ) : (
              "Save changes"
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
