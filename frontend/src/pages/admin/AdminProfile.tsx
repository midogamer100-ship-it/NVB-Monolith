import type { ReactNode } from "react";
import { useAuth } from "../../auth/AuthContext";
import { Alert, LoadingBlock, PageHeader } from "../../components/ui";
import { formatDateTime } from "../../lib/format";
import { useAdminAccess, type Probe } from "./access";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-3 sm:grid-cols-3">
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="text-sm font-medium text-navy-900 sm:col-span-2">{children}</dd>
    </div>
  );
}

function Permissions({ service, probe, lines }: { service: string; probe: Probe<{ capabilities?: Record<string, boolean | undefined> }>; lines: [string, string][] }) {
  if (probe.state === "loading") return <LoadingBlock label={`Checking ${service} permissions…`} />;
  if (probe.state === "unavailable") return <Alert kind="warning">{service} is temporarily unavailable; permissions can't be shown right now.</Alert>;
  if (probe.state === "denied") return <p className="text-sm text-slate-600">No {service} permissions.</p>;
  const caps = probe.data.capabilities ?? {};
  const granted = lines.filter(([key]) => caps[key] === true);
  return granted.length ? (
    <ul className="list-inside list-disc space-y-1 text-sm text-navy-900">
      {granted.map(([key, text]) => (
        <li key={key}>{text}</li>
      ))}
    </ul>
  ) : (
    <p className="text-sm text-slate-600">No {service} administration permissions are assigned to your account.</p>
  );
}

/** Read-only: roles are never changed from the profile page. */
export default function AdminProfile() {
  const { session } = useAuth();
  const { loans, statements } = useAdminAccess();
  if (!session) return null;
  const { user } = session;
  return (
    <div>
      <PageHeader title="Profile" subtitle="Your administrator account. Role changes are made by the platform team, not here." />
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card p-5">
          <h2 className="font-semibold text-navy-900">Account</h2>
          <dl className="mt-2 divide-y divide-slate-100">
            <Row label="Username">{user.username}</Row>
            <Row label="Display name">{user.display_name}</Row>
            <Row label="Role">Operations Admin</Row>
            <Row label="Session expires">{formatDateTime(session.session_expires_at)}</Row>
            <Row label="Idle sign-out">After {session.idle_timeout_minutes} minutes of inactivity</Row>
          </dl>
        </section>
        <section className="card space-y-5 p-5">
          <h2 className="font-semibold text-navy-900">Permissions</h2>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">Loans</h3>
            <Permissions
              service="Loans"
              probe={loans}
              lines={[
                ["loan_management", "Review loan applications, record recommendations and take final decisions (not on your own applications)"],
                ["batch_operations", "Run loan summary refresh batches"],
                ["role_admin", "Administer Loans service roles"],
              ]}
            />
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">Statements</h3>
            <Permissions
              service="Statements"
              probe={statements}
              lines={[
                ["statement_operations", "View statement processing status and failures (no access to customer PDFs)"],
                ["batch_operations", "Resume and retry monthly statement batches"],
                ["role_admin", "Administer Statements service roles"],
              ]}
            />
          </div>
        </section>
      </div>
    </div>
  );
}
