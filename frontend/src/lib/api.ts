/**
 * Minimal same-origin API client.
 * - Session lives in an HttpOnly cookie set by the backend.
 * - The CSRF token (from login or /api/auth/me) is kept in memory only and sent
 *   as X-CSRF-Token on state-changing requests.
 * - Any 401 clears client state and routes to /login?expired=1.
 */

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

let csrfToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function onUnauthorized(handler: (() => void) | null) {
  unauthorizedHandler = handler;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH";
  body?: unknown;
  headers?: Record<string, string>;
  /** Do not trigger the global session-expired redirect on 401. */
  skipAuthRedirect?: boolean;
  signal?: AbortSignal;
}

/** Turn any FastAPI error shape into one readable sentence. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const msg = detailMessage(err.body);
    if (msg) return msg;
    if (err.status === 0) return "Cannot reach the R&D bank service. Check your connection and try again.";
    if (err.status === 429) return "Too many requests. Please wait a moment and try again.";
    if (err.status >= 500) return "The service is temporarily unavailable. Please try again.";
    return `Request failed (HTTP ${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

function cleanMsg(msg: string): string {
  return msg.replace(/^Value error,\s*/i, "");
}

export function detailMessage(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  if (b.error && typeof b.error === "object") {
    const extensionError = b.error as Record<string, unknown>;
    if (typeof extensionError.message === "string") return extensionError.message;
  }
  if (typeof b.message === "string") return b.message;
  const detail = b.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as Record<string, unknown>;
    if (typeof d.message === "string") return d.message;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const item = e as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null;
        const msg = cleanMsg(item.msg ?? "Invalid value");
        return field && field !== "body" ? `${String(field).replace(/_/g, " ")}: ${msg}` : msg;
      })
      .join(" ");
  }
  return null;
}

/** Field-level messages from a FastAPI 422 validation error, keyed by field name. */
export function fieldErrors(err: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (!(err instanceof ApiError)) return out;
  const detail = (err.body as { detail?: unknown } | null)?.detail;
  if (!Array.isArray(detail)) return out;
  for (const e of detail as { loc?: unknown[]; msg?: string }[]) {
    const field = Array.isArray(e.loc) ? String(e.loc[e.loc.length - 1]) : "";
    if (field) out[field] = cleanMsg(e.msg ?? "Invalid value");
  }
  return out;
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers ?? {}) };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, null, "Network error");
  }

  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { detail: text.slice(0, 200) };
    }
  }

  if (!res.ok) {
    if (res.status === 401 && !opts.skipAuthRedirect) {
      csrfToken = null;
      unauthorizedHandler?.();
    }
    const err = new ApiError(res.status, body, `HTTP ${res.status}`);
    err.message = describeError(err);
    throw err;
  }
  return body as T;
}

/** Idempotency key for one transfer attempt: 32 hex chars, matches [A-Za-z0-9_-]{16,64}. */
export function newIdempotencyKey(): string {
  const c: Crypto = globalThis.crypto;
  if (typeof c.randomUUID === "function") {
    return c.randomUUID().replace(/-/g, "");
  }
  // randomUUID is unavailable on plain-http non-localhost origins; fall back.
  const bytes = new Uint8Array(16);
  c.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function toQuery(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
