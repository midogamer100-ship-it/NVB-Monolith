// Shared helpers for the NVB k6 scripts.
//
// Configuration (all via -e NAME=value or environment variables):
//   BASE_URL      target, e.g. https://nvb.example.internal   (default http://localhost:8080)
//   USER_PREFIX   username prefix                              (default loadtest)
//   USER_PAD      zero padding of the user number              (default 3 -> loadtest001)
//   USER_COUNT    number of seeded users to rotate through     (default 100)
//   PASSWORD      password of those users (REQUIRED, never hard-coded)
//   VUS / TARGET_VUS / DURATION   per-script load shape (see each script)
//   INSECURE_TLS  "true" to accept self-signed certificates in the demo lab
//   THINK_MIN / THINK_MAX  think time in seconds between user actions
import http from 'k6/http';
import { check, fail, sleep } from 'k6';
import { Counter } from 'k6/metrics';

export const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8080').replace(/\/+$/, '');
export const INSECURE_TLS = (__ENV.INSECURE_TLS || 'false') === 'true';
export const THINK_MIN = parseFloat(__ENV.THINK_MIN || '1');
export const THINK_MAX = parseFloat(__ENV.THINK_MAX || '3');

export const relogins = new Counter('nvb_relogins');
export const loginFailures = new Counter('nvb_login_failures');

export function env(name, fallback) {
  const v = __ENV[name];
  return v === undefined || v === '' ? fallback : v;
}

export function intEnv(name, fallback) {
  const v = parseInt(env(name, String(fallback)), 10);
  return Number.isFinite(v) ? v : fallback;
}

export function requirePassword(varName = 'PASSWORD') {
  const pw = __ENV[varName];
  if (!pw) {
    fail(`${varName} is required (pass -e ${varName}=... ; seeded via NVB_SEED_* or the credentials file)`);
  }
  return pw;
}

export function userName(prefix, pad, n) {
  return `${prefix}${String(n).padStart(pad, '0')}`;
}

// Deterministic user for the current VU: VU 1 -> user 1, VU 101 -> user 1 again.
export function userForVu(prefix = env('USER_PREFIX', 'loadtest'), pad = intEnv('USER_PAD', 3),
  count = intEnv('USER_COUNT', 100)) {
  return userName(prefix, pad, ((__VU - 1) % count) + 1);
}

export function baseOptions(extra = {}) {
  return Object.assign(
    {
      insecureSkipTLSVerify: INSECURE_TLS,
      discardResponseBodies: false,
      summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
      userAgent: 'nvb-k6-loadtest/1.0',
    },
    extra,
  );
}

export function think() {
  sleep(THINK_MIN + Math.random() * Math.max(0, THINK_MAX - THINK_MIN));
}

// ---- Session handling -------------------------------------------------------
// Each VU has its own JS runtime and cookie jar, so this module-level state is
// per VU. The nvb_session cookie is stored by k6's jar automatically.
let session = null;

export function login(username, password) {
  const res = http.post(
    `${BASE_URL}/api/auth/login`,
    JSON.stringify({ username, password }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'POST /api/auth/login' } },
  );
  const ok = check(res, { 'login 200': (r) => r.status === 200 });
  if (!ok) {
    loginFailures.add(1);
    session = null;
    return null;
  }
  session = { username, password, csrf: res.json('csrf_token') };
  return session;
}

export function ensureSession(username, password) {
  if (!session || session.username !== username) {
    login(username, password);
  }
  return session;
}

function withRelogin(doRequest) {
  let res = doRequest();
  if (res.status === 401 && session) {
    relogins.add(1);
    const { username, password } = session;
    if (login(username, password)) {
      res = doRequest();
    }
  }
  return res;
}

export function apiGet(path, name, extraTags = {}) {
  return withRelogin(() =>
    http.get(`${BASE_URL}${path}`, { tags: Object.assign({ name: name || `GET ${path}` }, extraTags) }),
  );
}

export function apiPost(path, body, name, headers = {}, extraTags = {}) {
  return withRelogin(() =>
    http.post(`${BASE_URL}${path}`, JSON.stringify(body), {
      headers: Object.assign(
        { 'Content-Type': 'application/json', 'X-CSRF-Token': session ? session.csrf : '' },
        headers,
      ),
      tags: Object.assign({ name: name || `POST ${path}` }, extraTags),
    }),
  );
}

// Idempotency keys: 16-64 chars of [A-Za-z0-9_-].
export function idempotencyKey() {
  let s = `k6-${__VU}-${__ITER}-`;
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  while (s.length < 40) s += chars[Math.floor(Math.random() * chars.length)];
  return s;
}

// A typical read-only customer visit: dashboard, accounts, one transactions page.
export function browseAsCustomer() {
  const dash = apiGet('/api/dashboard', 'GET /api/dashboard');
  check(dash, { 'dashboard 200': (r) => r.status === 200 });
  think();
  const accts = apiGet('/api/accounts', 'GET /api/accounts');
  check(accts, { 'accounts 200': (r) => r.status === 200 });
  let accountId = null;
  if (accts.status === 200) {
    const list = accts.json('accounts') || [];
    if (list.length) accountId = list[Math.floor(Math.random() * list.length)].id;
  }
  if (accountId) {
    const detail = apiGet(`/api/accounts/${accountId}`, 'GET /api/accounts/{id}');
    check(detail, { 'account detail 200': (r) => r.status === 200 });
  }
  think();
  const page = 1 + Math.floor(Math.random() * 3);
  const txns = apiGet(`/api/transactions?page=${page}&page_size=20`, 'GET /api/transactions');
  check(txns, { 'transactions 200': (r) => r.status === 200 });
  return accountId;
}
