// 03 - Salary-day traffic spike (read-heavy, login-heavy).
//
//   k6 run -e BASE_URL=... -e PASSWORD=... -e BASE_RATE=5 -e SPIKE_RATE=60 \
//          -e SPIKE_DURATION=3m loadtest/k6/03-salary-day-spike.js
//
// Open-model arrival rate (new "visits" per second, independent of response
// time) so a slow system cannot hide by slowing the load generator down.
// Each visit = fresh login (customers rushing to check their salary) +
// dashboard + transactions filtered to credits.
//
// Note: login uses Argon2 password hashing, which is intentionally CPU-costly,
// so this scenario stresses CPU more than script 01.
import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, apiGet, baseOptions, env, intEnv, login, requirePassword, userName } from './lib/common.js';

const PASSWORD = requirePassword();
const BASE_RATE = intEnv('BASE_RATE', 5);
const SPIKE_RATE = intEnv('SPIKE_RATE', 60);
const PREFIX = env('USER_PREFIX', 'loadtest');
const PAD = intEnv('USER_PAD', 3);
const COUNT = intEnv('USER_COUNT', 100);

export const options = baseOptions({
  scenarios: {
    salary_day: {
      executor: 'ramping-arrival-rate',
      startRate: BASE_RATE,
      timeUnit: '1s',
      preAllocatedVUs: intEnv('PREALLOCATED_VUS', 100),
      maxVUs: intEnv('MAX_VUS', 400),
      stages: [
        { duration: env('BASELINE_DURATION', '2m'), target: BASE_RATE },
        { duration: '30s', target: SPIKE_RATE },
        { duration: env('SPIKE_DURATION', '3m'), target: SPIKE_RATE },
        { duration: '30s', target: BASE_RATE },
        { duration: env('RECOVERY_DURATION', '3m'), target: BASE_RATE },
      ],
    },
  },
  thresholds: {
    http_req_failed: [{ threshold: 'rate<0.05', abortOnFail: false }],
    'http_req_duration{name:GET /api/dashboard}': [{ threshold: 'p(95)<2000', abortOnFail: false }],
    dropped_iterations: [{ threshold: 'count<1', abortOnFail: false }],
  },
});

export default function () {
  // Fresh cookie jar per visit so each iteration is a real new login.
  http.cookieJar().clear(BASE_URL);
  const user = userName(PREFIX, PAD, 1 + Math.floor(Math.random() * COUNT));
  if (!login(user, PASSWORD)) return;
  check(apiGet('/api/dashboard', 'GET /api/dashboard'), { 'dashboard 200': (r) => r.status === 200 });
  check(apiGet('/api/transactions?direction=credit&page=1&page_size=10', 'GET /api/transactions'), {
    'credits 200': (r) => r.status === 200,
  });
}
