// 01 - Normal customer activity (read-heavy). Baseline for every environment.
//
//   k6 run -e BASE_URL=https://nvb.example.internal -e PASSWORD=... \
//          -e VUS=20 -e DURATION=5m loadtest/k6/01-normal-activity.js
//
// Each VU logs in once as loadtestNNN and repeatedly browses
// dashboard -> accounts -> account detail -> transactions with think time.
import { baseOptions, browseAsCustomer, ensureSession, env, intEnv, requirePassword, userForVu } from './lib/common.js';

const PASSWORD = requirePassword();

export const options = baseOptions({
  scenarios: {
    normal: {
      executor: 'constant-vus',
      vus: intEnv('VUS', 20),
      duration: env('DURATION', '5m'),
    },
  },
  thresholds: {
    // Starting expectations for an unloaded system; tune per environment.
    http_req_failed: ['rate<0.01'],
    'http_req_duration{name:GET /api/dashboard}': ['p(95)<800'],
    checks: ['rate>0.99'],
  },
});

export default function () {
  ensureSession(userForVu(), PASSWORD);
  browseAsCustomer();
}
