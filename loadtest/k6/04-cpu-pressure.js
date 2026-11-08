// 04 - Sustained CPU-pressure demo (SYNTHETIC WORKLOAD).
//
// Requires NVB_DEMO_WORKLOAD_ENABLED=true on the target (isolated demo only) and
// the seeded demo-role users demoload01..demoload10.
//
//   k6 run -e BASE_URL=... -e DEMO_PASSWORD=... -e PASSWORD=... \
//          -e ANALYSIS_RATE=4 -e BROWSE_VUS=20 -e DURATION=15m \
//          loadtest/k6/04-cpu-pressure.js
//
// Two concurrent scenarios:
//   analysis - constant arrival rate of POST /api/demo/statement-analysis
//              (bounded, pure-Python CPU work on synthetic data) by demo users
//   browse   - ordinary customers browsing, i.e. the user-facing latency
//              we care about while CPU is saturated
// 429 responses mean an instance hit its per-process workload concurrency cap;
// they are counted separately (nvb_workload_busy) and as failed requests.
import { check } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import {
  apiPost, baseOptions, browseAsCustomer, ensureSession, env, intEnv, requirePassword, userForVu, userName,
} from './lib/common.js';

const DEMO_PASSWORD = requirePassword('DEMO_PASSWORD');
const PASSWORD = requirePassword();
const DEMO_COUNT = intEnv('DEMO_USER_COUNT', 10);
const DURATION = env('DURATION', '15m');
const PROFILE = env('PROFILE', 'standard'); // standard | heavy

const workloadBusy = new Counter('nvb_workload_busy');
const workloadOk = new Rate('nvb_workload_success');
const computeMs = new Trend('nvb_workload_compute_ms', true);

export const options = baseOptions({
  scenarios: {
    analysis: {
      executor: 'constant-arrival-rate',
      rate: intEnv('ANALYSIS_RATE', 4),
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: intEnv('ANALYSIS_VUS', 20),
      maxVUs: intEnv('ANALYSIS_MAX_VUS', 60),
      exec: 'analysis',
    },
    browse: {
      executor: 'constant-vus',
      vus: intEnv('BROWSE_VUS', 20),
      duration: DURATION,
      exec: 'browse',
    },
  },
  thresholds: {
    // Informational: the point of this test is to observe saturation.
    'http_req_duration{scenario:browse}': [{ threshold: 'p(95)<1500', abortOnFail: false }],
    'http_req_failed{scenario:browse}': [{ threshold: 'rate<0.02', abortOnFail: false }],
    nvb_workload_success: [{ threshold: 'rate>0.9', abortOnFail: false }],
  },
});

export function analysis() {
  // demoload01..demoload10, rotated by VU.
  const user = userName('demoload', 2, ((__VU - 1) % DEMO_COUNT) + 1);
  ensureSession(user, DEMO_PASSWORD);
  const res = apiPost(
    '/api/demo/statement-analysis',
    { profile: PROFILE, months: 6, seed: __ITER % 1000 },
    'POST /api/demo/statement-analysis',
  );
  if (res.status === 429) workloadBusy.add(1);
  const ok = check(res, { 'analysis 200': (r) => r.status === 200 });
  workloadOk.add(ok);
  if (ok) computeMs.add(res.json('compute_ms'));
}

export function browse() {
  ensureSession(userForVu(), PASSWORD);
  browseAsCustomer();
}
