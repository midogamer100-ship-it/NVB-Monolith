// 02 - Gradual load increase (read-heavy). Finds the point where latency bends.
//
//   k6 run -e BASE_URL=... -e PASSWORD=... -e TARGET_VUS=200 -e STEP_DURATION=2m \
//          loadtest/k6/02-ramp-up.js
//
// Ramps 0 -> TARGET_VUS in 5 equal steps, holding each step for STEP_DURATION,
// then ramps down. Watch p95 latency and error rate per step and correlate with
// CPU / DB measurements on the target (see docs/SCALING_DEMO.md). Thresholds are
// informational (no abort) because the purpose is to observe degradation.
import { baseOptions, browseAsCustomer, ensureSession, env, intEnv, requirePassword, userForVu } from './lib/common.js';

const PASSWORD = requirePassword();
const TARGET = intEnv('TARGET_VUS', 200);
const STEP = env('STEP_DURATION', '2m');
const STEPS = 5;

const stages = [];
for (let i = 1; i <= STEPS; i++) {
  const target = Math.round((TARGET * i) / STEPS);
  stages.push({ duration: '30s', target });
  stages.push({ duration: STEP, target });
}
stages.push({ duration: '1m', target: 0 });

export const options = baseOptions({
  scenarios: {
    ramp: { executor: 'ramping-vus', startVUs: 0, stages, gracefulRampDown: '30s' },
  },
  thresholds: {
    http_req_failed: [{ threshold: 'rate<0.05', abortOnFail: false }],
    http_req_duration: [{ threshold: 'p(95)<2000', abortOnFail: false }],
  },
});

export default function () {
  ensureSession(userForVu(), PASSWORD);
  browseAsCustomer();
}
