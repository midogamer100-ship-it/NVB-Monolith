import { Badge } from "../../components/ui";
import { money } from "../../lib/digital";

export interface LoanSummary {
  status: string;
  label: string;
  result: Record<string, unknown> | null;
  error_code: string | null;
  completed_at?: string | null;
}

export interface LoanEvent {
  type: string;
  actor: string;
  from?: string | null;
  to?: string | null;
  at: string;
  details?: Record<string, unknown> | null;
}

export interface LoanApp {
  id: string;
  version: number;
  status: string;
  amount_minor: number;
  currency: string;
  term_months: number;
  monthly_income_minor: number;
  purpose: string;
  account: { account_id?: number; masked_number: string };
  created_at?: string | null;
  submitted_at?: string | null;
  decided_at?: string | null;
  owner_subject?: string;
  owner_label?: string;
  reviewer_subject?: string | null;
  recommendation?: string | null;
  recommendation_reason?: string | null;
  recommended_at?: string | null;
  decision_reason?: string | null;
  decided_by?: string | null;
  disbursement?: string;
  summary?: LoanSummary | null;
  events?: LoanEvent[];
  assignment?: {
    reviewer_subject: string | null;
    reviewer_is_current_admin: boolean;
    held_by_retired_reviewer: boolean;
  } | null;
}

export interface LoanStats {
  by_status: Record<string, number>;
  pending_review: number;
  pending_decision: number;
  held_by_retired_reviewer: number;
  legacy_workflow_enabled?: boolean;
}

export const QUEUES = [
  { key: "pending_review", label: "Pending review" },
  { key: "pending_decision", label: "Pending decision" },
  { key: "decided", label: "Decided" },
  { key: "all", label: "All" },
] as const;

export const LOAN_STATUSES = ["submitted", "under_review", "approved", "rejected"] as const;

export function statusLabel(s: string): string {
  return s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export function LoanStatus({ value }: { value: string }) {
  const tone = value === "approved" ? "teal" : value === "rejected" ? "red" : value === "under_review" ? "navy" : "amber";
  return <Badge tone={tone}>{statusLabel(value)}</Badge>;
}

export function RecommendationBadge({ value }: { value?: string | null }) {
  if (!value) return null;
  return <Badge tone={value === "approve" ? "teal" : "red"}>Recommends {value === "approve" ? "approval" : "rejection"}</Badge>;
}

export function amount(app: Pick<LoanApp, "amount_minor" | "currency">): string {
  return money(app.amount_minor, app.currency);
}

/** Integer counts only; anything else is reported as unavailable rather than guessed. */
export function count(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
