import { useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { Alert, EmptyState, ErrorState, LoadingBlock, PageHeader, Spinner } from "../components/ui";
import { api, describeError } from "../lib/api";
import { formatMinor } from "../lib/format";
import { useApi } from "../lib/useApi";

interface WorkloadInfo {
  synthetic: boolean;
  description: string;
  profiles: string[];
  months_range: [number, number];
  max_concurrency_per_process: number;
  max_seconds: number;
  simulations: number;
  instance_id: string;
}

interface AnalysisResult {
  synthetic: boolean;
  profile: string;
  months: number;
  transactions_analysed: number;
  simulations: number;
  top_categories: [string, number][];
  projection_minor: { p10: number; p50: number; p90: number };
  compute_ms: number;
  instance_id: string;
}

interface Run {
  at: string;
  roundTripMs: number;
  result?: AnalysisResult;
  error?: string;
}

export default function DemoWorkload() {
  const { session } = useAuth();
  const enabled = Boolean(session?.features.demo_workload);
  const info = useApi<WorkloadInfo>(enabled ? "/api/demo/workload" : null);
  const [profile, setProfile] = useState("standard");
  const [months, setMonths] = useState(6);
  const [running, setRunning] = useState(false);
  const [runs, setRuns] = useState<Run[]>([]);

  if (!enabled) {
    return (
      <div className="card">
        <EmptyState
          title="Synthetic workload is disabled"
          message="The statement-analysis workload is off by default. An operator must set NVB_DEMO_WORKLOAD_ENABLED=true on the server for the isolated demo."
        />
      </div>
    );
  }

  async function onRun(e: FormEvent) {
    e.preventDefault();
    setRunning(true);
    const started = performance.now();
    const at = new Date().toLocaleTimeString("en-GB");
    try {
      const result = await api<AnalysisResult>("/api/demo/statement-analysis", {
        method: "POST",
        body: { profile, months, seed: Math.floor(Math.random() * 1_000_000) },
      });
      setRuns((r) => [{ at, roundTripMs: Math.round(performance.now() - started), result }, ...r].slice(0, 20));
    } catch (err) {
      setRuns((r) => [{ at, roundTripMs: Math.round(performance.now() - started), error: describeError(err) }, ...r].slice(0, 20));
    } finally {
      setRunning(false);
    }
  }

  const latest = runs[0]?.result;

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Demo workload" subtitle="Synthetic statement analysis used to create real application CPU pressure for the scaling demonstration." />
      <Alert kind="warning">
        <strong>SYNTHETIC WORKLOAD.</strong> This page runs a bounded, CPU-intensive analysis of a randomly generated statement. It uses no customer data, does not
        sleep or inject failures, and is available only to the demo operator role when the server-side flag is enabled.
      </Alert>

      {info.loading && <LoadingBlock label="Reading workload limits…" />}
      {info.error && (
        <div className="mt-4">
          <ErrorState error={info.error} onRetry={info.reload} />
        </div>
      )}

      {info.data && (
        <div className="mt-6 grid gap-6 lg:grid-cols-3">
          <form className="card space-y-4 p-5" onSubmit={onRun}>
            <h2 className="font-semibold text-navy-900">Run one analysis</h2>
            <div>
              <label htmlFor="profile" className="label">
                Profile
              </label>
              <select id="profile" className="input" value={profile} onChange={(e) => setProfile(e.target.value)} disabled={running}>
                {info.data.profiles.map((p) => (
                  <option key={p} value={p}>
                    {p === "heavy" ? "Heavy (2× work)" : "Standard"}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="months" className="label">
                Statement months: {months}
              </label>
              <input
                id="months"
                type="range"
                min={info.data.months_range[0]}
                max={info.data.months_range[1]}
                value={months}
                onChange={(e) => setMonths(Number(e.target.value))}
                disabled={running}
                className="w-full accent-teal-700"
              />
            </div>
            <button type="submit" className="btn-accent w-full" disabled={running}>
              {running ? (
                <>
                  <Spinner className="h-4 w-4 text-white" /> Computing…
                </>
              ) : (
                "Run synthetic analysis"
              )}
            </button>
            <dl className="space-y-1 border-t border-slate-200 pt-3 text-xs text-slate-600">
              <div className="flex justify-between">
                <dt>Max concurrent runs / process</dt>
                <dd className="font-semibold text-navy-900">{info.data.max_concurrency_per_process}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Execution budget</dt>
                <dd className="font-semibold text-navy-900">{info.data.max_seconds}s</dd>
              </div>
              <div className="flex justify-between">
                <dt>Base simulations</dt>
                <dd className="font-semibold text-navy-900">{info.data.simulations}</dd>
              </div>
            </dl>
            <p className="text-xs text-slate-500">For sustained load use the k6 CPU-pressure script; this form runs a single request.</p>
          </form>

          <section className="card p-5 lg:col-span-2" aria-labelledby="result-heading">
            <h2 id="result-heading" className="font-semibold text-navy-900">
              Latest result
            </h2>
            {!latest && runs.length === 0 && <EmptyState title="No runs yet" message="Run an analysis to see compute time and which instance served it." />}
            {runs[0]?.error && (
              <div className="mt-3">
                <Alert kind="error">{runs[0].error}</Alert>
              </div>
            )}
            {latest && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg bg-navy-50 p-4">
                  <p className="text-xs uppercase tracking-wide text-navy-700">Server compute time</p>
                  <p className="text-2xl font-bold text-navy-900">{latest.compute_ms} ms</p>
                  <p className="text-xs text-slate-600">Round trip {runs[0].roundTripMs} ms</p>
                </div>
                <div className="rounded-lg bg-teal-50 p-4">
                  <p className="text-xs uppercase tracking-wide text-teal-800">Served by instance</p>
                  <p className="break-all font-mono text-sm font-semibold text-navy-900">{latest.instance_id}</p>
                  <p className="text-xs text-slate-600">
                    {latest.transactions_analysed} synthetic txns · {latest.simulations} simulations
                  </p>
                </div>
                <div className="rounded-lg border border-slate-200 p-4 sm:col-span-2">
                  <p className="text-xs uppercase tracking-wide text-slate-500">Synthetic 12-month projection (p10 / p50 / p90)</p>
                  <p className="mt-1 text-sm font-semibold text-navy-900">
                    {formatMinor(latest.projection_minor.p10)} / {formatMinor(latest.projection_minor.p50)} / {formatMinor(latest.projection_minor.p90)}
                  </p>
                </div>
              </div>
            )}
            {runs.length > 0 && (
              <div className="mt-5 overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <th scope="col" className="py-2 pr-4">Time</th>
                      <th scope="col" className="py-2 pr-4">Profile</th>
                      <th scope="col" className="py-2 pr-4">Compute</th>
                      <th scope="col" className="py-2 pr-4">Round trip</th>
                      <th scope="col" className="py-2">Instance / error</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {runs.map((r, i) => (
                      <tr key={i}>
                        <td className="py-2 pr-4 text-slate-600">{r.at}</td>
                        <td className="py-2 pr-4">{r.result ? `${r.result.profile} · ${r.result.months}m` : "—"}</td>
                        <td className="py-2 pr-4 tabular-nums">{r.result ? `${r.result.compute_ms} ms` : "—"}</td>
                        <td className="py-2 pr-4 tabular-nums">{r.roundTripMs} ms</td>
                        <td className={`py-2 font-mono text-xs ${r.error ? "text-red-700" : "text-slate-700"}`}>{r.error ?? r.result?.instance_id}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
