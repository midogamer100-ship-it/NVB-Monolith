export type Role = "customer" | "admin" | "demo";

export interface SessionUser {
  username: string;
  role: Role;
  display_name: string;
  full_name: string | null;
  customer_number: string | null;
}

export interface SessionInfo {
  user: SessionUser;
  csrf_token: string;
  session_expires_at: string;
  idle_timeout_minutes: number;
  features: { demo_workload: boolean };
}

export interface Account {
  id: number;
  masked_number: string;
  last4: string;
  type: string;
  nickname: string;
  currency: string;
  balance: string;
  balance_minor: number;
  status: string;
  opened_at: string;
}

export interface Txn {
  id: number;
  account_id: number;
  reference: string;
  direction: "debit" | "credit";
  type: string;
  category: string;
  amount: string;
  amount_minor: number;
  signed_amount_minor: number;
  balance_after: string;
  description: string;
  counterparty: string;
  posted_at: string;
  transfer_reference: string | null;
  account?: { id: number; masked_number: string; nickname: string };
}

export interface TxnPage {
  items: Txn[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
  types: string[];
}

export interface Beneficiary {
  id: number;
  nickname: string;
  holder_name: string;
  masked_number: string;
  bank: string;
}

export interface Dashboard {
  greeting_name: string;
  customer_number: string;
  accounts: Account[];
  total_balance: string;
  total_balance_minor: number;
  currency: string;
  recent_transactions: Txn[];
  monthly: { month: string; income: string; income_minor: number; spending: string; spending_minor: number }[];
  spending_by_category: { category: string; amount: string; amount_minor: number }[];
}

export interface TransferPreview {
  source: { id: number; masked_number: string; nickname: string; balance: string };
  destination: { masked_number: string; holder_name: string; is_own_account: boolean };
  amount: string;
  fee: string;
  currency: string;
  description: string;
  sufficient_funds: boolean;
  balance_after: string | null;
}

export interface TransferReceipt {
  reference: string;
  status: "completed" | "failed";
  failure_reason: string | null;
  amount: string;
  amount_minor: number;
  currency: string;
  description: string;
  source: { id: number; masked_number: string; nickname: string };
  destination: { masked_number: string; holder_name: string; is_own_account: boolean };
  created_at: string;
  completed_at: string | null;
  message?: string;
}

export interface Profile {
  customer_number: string;
  full_name: string;
  preferred_name: string | null;
  email: string;
  phone: string;
  city: string;
  segment: string;
  username: string;
  member_since: string;
  last_login_at: string | null;
  editable_fields: string[];
  cities: string[];
}

export interface ClusterMetrics {
  status: "ok" | "error" | "not_configured";
  message?: string;
  source?: string;
  request_rate_per_second?: number | null;
  p95_latency_seconds?: number | null;
  error_rate?: number | null;
  available_replicas?: number | null;
  desired_replicas?: number | null;
}

export interface OpsStatus {
  environment_label: string;
  app_version: string;
  instance_id: string;
  database: { status: string; latency_ms?: number; backend?: string; host?: string; error?: string };
  db_pool: { size?: number; checked_out?: number; overflow?: number; status?: string };
  this_instance: {
    uptime_seconds: number;
    requests_total: number;
    errors_total: number;
    last_minute: {
      requests: number;
      request_rate_per_second: number;
      error_rate: number | null;
      p95_latency_ms: number | null;
    };
  };
  cluster: ClusterMetrics;
  demo_workload_enabled: boolean;
  server_time: string;
}

export interface AuditEvent {
  id: number;
  event_type: string;
  outcome: string;
  actor: string | null;
  source_ip: string | null;
  request_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}
