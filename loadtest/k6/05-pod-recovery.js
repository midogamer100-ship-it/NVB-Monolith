// 05 - Recovery while a pod is deleted (OpenShift containers).
//
//   k6 run -e BASE_URL=https://<route-host> -e PASSWORD=... -e RATE=20 -e DURATION=10m \
//          --out json=results/05-pod-recovery.json loadtest/k6/05-pod-recovery.js
//
// While it runs, in another terminal:
//   oc get pods -l app=nvb-app -n <ns> -w
//   oc delete pod <one-nvb-app-pod> -n <ns>        # e.g. 3 minutes in
//
// What to look for:
//   * nvb_errors (rate) - should stay near zero: readiness + preStop drain the
//     pod from the Route before it stops, and other replicas keep serving.
//   * nvb_relogins - should stay 0: sessions live in PostgreSQL, so a user whose
//     pod disappears is NOT logged out when another pod serves the next request.
//   * Instance distribution: every response carries X-NVB-Instance (the pod
//     name). It is recorded as the `instance` tag on nvb_responses_by_instance.
//     Summarise after the run with:
//       jq -r 'select(.metric=="nvb_responses_by_instance" and .type=="Point") | .data.tags.instance' \
//          results/05-pod-recovery.json | sort | uniq -c
//     A new pod name appears after the replacement pod becomes Ready.
import { check } from 'k6';
import { Counter, Rate } from 'k6/metrics';
import { apiGet, baseOptions, ensureSession, env, intEnv, requirePassword, userForVu } from './lib/common.js';

const PASSWORD = requirePassword();
const errors = new Rate('nvb_errors');
const byInstance = new Counter('nvb_responses_by_instance');
let lastInstance = null;

export const options = baseOptions({
  scenarios: {
    steady: {
      executor: 'constant-arrival-rate',
      rate: intEnv('RATE', 20),
      timeUnit: '1s',
      duration: env('DURATION', '10m'),
      preAllocatedVUs: intEnv('PREALLOCATED_VUS', 50),
      maxVUs: intEnv('MAX_VUS', 200),
    },
  },
  thresholds: {
    nvb_errors: ['rate<0.01'],
    nvb_relogins: ['count<1'],
  },
});

export default function () {
  ensureSession(userForVu(), PASSWORD);
  const res = apiGet('/api/dashboard', 'GET /api/dashboard');
  const ok = check(res, { 'dashboard 200': (r) => r.status === 200 });
  errors.add(!ok);
  const instance = res.headers['X-Nvb-Instance'] || res.headers['X-NVB-Instance'] || 'none';
  byInstance.add(1, { instance });
  if (__VU === 1 && instance !== lastInstance) {
    console.log(`VU1 now served by ${instance} (status ${res.status})`);
    lastInstance = instance;
  }
}
