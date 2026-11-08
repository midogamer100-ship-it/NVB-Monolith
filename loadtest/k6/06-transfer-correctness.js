// 06 - Concurrent transfer + idempotency CORRECTNESS validation.
// Deliberately separate from the read-heavy performance scripts: it changes
// balances and its pass/fail criterion is integrity, not latency.
//
//   k6 run -e BASE_URL=... -e PASSWORD=... -e TRANSFER_USERS=20 -e VUS_PER_USER=2 \
//          -e DURATION=2m loadtest/k6/06-transfer-correctness.js
//
// Topology: users loadtest001..loadtestN form a ring; user i sends to its seeded
// beneficiary user i+1 (N wraps to 1). VUS_PER_USER VUs share each user so the
// same source account is debited concurrently from different requests.
// Nobody else may use loadtest001..N during this run.
//
// Each iteration:
//   1. POST a transfer of AMOUNT with a fresh Idempotency-Key  -> expect 201
//   2. (RETRY_PCT % of iterations) re-POST the identical request with the same
//      key -> expect 200, Idempotent-Replayed: true, the SAME reference
//   3. (once per VU) reuse that key with a different amount -> expect 409
// Teardown verifies, for every user, that
//   balance_after - balance_before == (transfers_in - transfers_out) * AMOUNT
// using ledger counts from the API, that no balance is negative, and that the
// ring's total money is conserved. Any violation increments
// nvb_integrity_violations, which has a threshold of zero.
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import {
  BASE_URL, apiGet, apiPost, baseOptions, env, idempotencyKey, intEnv, login, requirePassword, userName,
} from './lib/common.js';

const PASSWORD = requirePassword();
const N = intEnv('TRANSFER_USERS', 20);
const VUS_PER_USER = intEnv('VUS_PER_USER', 2);
const AMOUNT = env('AMOUNT', '1.00');
const AMOUNT_MINOR = Math.round(parseFloat(AMOUNT) * 100); // test-side bookkeeping only
const RETRY_PCT = intEnv('RETRY_PCT', 30);

const violations = new Counter('nvb_integrity_violations');
const created = new Counter('nvb_transfers_created');
const replayed = new Counter('nvb_transfers_replayed');

export const options = baseOptions({
  scenarios: {
    transfers: {
      executor: 'constant-vus',
      vus: N * VUS_PER_USER,
      duration: env('DURATION', '2m'),
    },
  },
  thresholds: {
    nvb_integrity_violations: ['count==0'],
    checks: ['rate==1.0'],
  },
  setupTimeout: '5m',
  teardownTimeout: '5m',
});

function totalOf(path) {
  const r = apiGet(path, 'GET /api/transactions (count)');
  return r.status === 200 ? r.json('total') : null;
}

function snapshot(i) {
  http.cookieJar().clear(BASE_URL);
  if (!login(userName('loadtest', 3, i), PASSWORD)) return null;
  const accts = apiGet('/api/accounts', 'GET /api/accounts');
  const bens = apiGet('/api/beneficiaries', 'GET /api/beneficiaries');
  if (accts.status !== 200 || bens.status !== 200) return null;
  const account = accts.json('accounts')[0];
  const ben = (bens.json('beneficiaries') || [])[0];
  return {
    accountId: account.id,
    beneficiaryId: ben ? ben.id : null,
    balanceMinor: account.balance_minor,
    outCount: totalOf(`/api/transactions?account_id=${account.id}&type=transfer_out&page_size=1`),
    inCount: totalOf(`/api/transactions?account_id=${account.id}&type=transfer_in&page_size=1`),
  };
}

export function setup() {
  const users = {};
  for (let i = 1; i <= N; i++) {
    const s = snapshot(i);
    if (!s || s.beneficiaryId === null) {
      throw new Error(`setup: could not read account/beneficiary for ${userName('loadtest', 3, i)}`);
    }
    users[i] = s;
  }
  return { users };
}

let triedConflict = false;
let me = null;

export default function (data) {
  const idx = ((__VU - 1) % N) + 1;
  const u = data.users[idx];
  if (!me) {
    me = login(userName('loadtest', 3, idx), PASSWORD);
    if (!me) return;
  }
  const body = {
    source_account_id: u.accountId,
    beneficiary_id: u.beneficiaryId,
    amount: AMOUNT,
    description: 'k6 correctness test',
  };
  const key = idempotencyKey();
  const first = apiPost('/api/transfers', body, 'POST /api/transfers', { 'Idempotency-Key': key });
  const ok = check(first, { 'transfer 201': (r) => r.status === 201 });
  if (!ok) {
    console.error(`unexpected transfer status ${first.status}: ${first.body}`);
    return;
  }
  created.add(1);
  const ref = first.json('reference');

  if (Math.random() * 100 < RETRY_PCT) {
    const retry = apiPost('/api/transfers', body, 'POST /api/transfers (retry)', { 'Idempotency-Key': key });
    check(retry, {
      'retry 200': (r) => r.status === 200,
      'retry marked replayed': (r) => r.headers['Idempotent-Replayed'] === 'true',
      'retry same reference': (r) => r.status === 200 && r.json('reference') === ref,
    });
    if (retry.status === 200) replayed.add(1);
  }

  if (!triedConflict) {
    triedConflict = true;
    const conflict = apiPost('/api/transfers', Object.assign({}, body, { amount: '2.00' }),
      'POST /api/transfers (conflict)', { 'Idempotency-Key': key });
    check(conflict, { 'key reuse with different payload 409': (r) => r.status === 409 });
  }
}

export function teardown(data) {
  let before = 0;
  let after = 0;
  for (let i = 1; i <= N; i++) {
    const b = data.users[i];
    const a = snapshot(i);
    if (!a) {
      violations.add(1);
      console.error(`teardown: cannot read ${userName('loadtest', 3, i)}`);
      continue;
    }
    before += b.balanceMinor;
    after += a.balanceMinor;
    const dIn = a.inCount - b.inCount;
    const dOut = a.outCount - b.outCount;
    const expected = (dIn - dOut) * AMOUNT_MINOR;
    const actual = a.balanceMinor - b.balanceMinor;
    const good = check(null, {
      'balance delta matches ledger': () => actual === expected,
      'balance not negative': () => a.balanceMinor >= 0,
    });
    if (!good) {
      violations.add(1);
      console.error(`user ${i}: delta ${actual} != expected ${expected} (in +${dIn}, out +${dOut})`);
    }
  }
  if (!check(null, { 'ring total conserved': () => before === after })) {
    violations.add(1);
    console.error(`ring total changed: before ${before} after ${after}`);
  }
}
