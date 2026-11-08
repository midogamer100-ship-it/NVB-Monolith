import { Link } from "react-router-dom";
import { formatDateTime, formatDecimal, formatMinor, formatSignedMinor, titleCase } from "../lib/format";
import type { Txn } from "../lib/types";
import { useApi } from "../lib/useApi";
import { ErrorState, LoadingBlock, Modal } from "./ui";

/** Loads the full transaction record from the server (ownership enforced server-side). */
export default function TxnDetailModal({ txnId, onClose }: { txnId: number | null; onClose: () => void }) {
  const { data, error, loading, reload } = useApi<Txn>(txnId !== null ? `/api/transactions/${txnId}` : null);
  return (
    <Modal open={txnId !== null} title="Transaction details" onClose={onClose}>
      {loading && <LoadingBlock />}
      {error && !loading && <ErrorState error={error} onRetry={reload} />}
      {data && !loading && !error && (
        <div>
          <p className={`text-3xl font-bold tabular-nums ${data.direction === "credit" ? "text-teal-700" : "text-navy-900"}`}>
            {formatSignedMinor(data.signed_amount_minor)}
          </p>
          <p className="mt-1 text-sm text-slate-600">{data.description}</p>
          <dl className="mt-5 divide-y divide-slate-100 text-sm">
            {[
              ["Reference", <span className="font-mono">{data.reference}</span>],
              ["Date", formatDateTime(data.posted_at)],
              ["Type", titleCase(data.type)],
              ["Category", data.category],
              ["Direction", titleCase(data.direction)],
              ["Counterparty", data.counterparty || "—"],
              ["Account", data.account ? `${data.account.nickname} (${data.account.masked_number})` : "—"],
              ["Amount", formatMinor(data.amount_minor)],
              ["Balance after", formatDecimal(data.balance_after)],
            ].map(([k, v]) => (
              <div key={String(k)} className="flex justify-between gap-4 py-2.5">
                <dt className="text-slate-500">{k}</dt>
                <dd className="text-right font-medium text-navy-900">{v}</dd>
              </div>
            ))}
          </dl>
          {data.account && (
            <Link to={`/accounts/${data.account.id}`} className="btn-secondary mt-4 w-full" onClick={onClose}>
              View account
            </Link>
          )}
        </div>
      )}
    </Modal>
  );
}
