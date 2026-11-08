import { formatDate, formatDecimal, formatSignedMinor, titleCase } from "../lib/format";
import type { Txn } from "../lib/types";

/** Responsive transaction table (cards on mobile). Rows are buttons when onSelect is given. */
export default function TxnList({ items, onSelect, showBalance = false }: { items: Txn[]; onSelect?: (t: Txn) => void; showBalance?: boolean }) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <th scope="col" className="px-4 py-3">Date</th>
              <th scope="col" className="px-4 py-3">Description</th>
              <th scope="col" className="px-4 py-3">Type</th>
              <th scope="col" className="px-4 py-3 text-right">Amount</th>
              {showBalance && <th scope="col" className="px-4 py-3 text-right">Balance after</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((t) => (
              <tr
                key={t.id}
                className={onSelect ? "cursor-pointer transition-colors hover:bg-navy-50/60" : ""}
                onClick={onSelect ? () => onSelect(t) : undefined}
              >
                <td className="whitespace-nowrap px-4 py-3 text-slate-600">{formatDate(t.posted_at)}</td>
                <td className="px-4 py-3">
                  {onSelect ? (
                    <button type="button" className="text-left font-medium text-navy-900 hover:underline" onClick={(e) => { e.stopPropagation(); onSelect(t); }}>
                      {t.description}
                    </button>
                  ) : (
                    <span className="font-medium text-navy-900">{t.description}</span>
                  )}
                  {t.counterparty && <p className="text-xs text-slate-500">{t.counterparty}</p>}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-slate-600">{titleCase(t.type)}</td>
                <td className={`whitespace-nowrap px-4 py-3 text-right font-semibold tabular-nums ${t.direction === "credit" ? "text-teal-700" : "text-slate-900"}`}>
                  {formatSignedMinor(t.signed_amount_minor)}
                </td>
                {showBalance && (
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-slate-600">
                    {formatDecimal(t.balance_after)}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="divide-y divide-slate-100 md:hidden">
        {items.map((t) => (
          <li key={t.id}>
            <button
              type="button"
              disabled={!onSelect}
              onClick={onSelect ? () => onSelect(t) : undefined}
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left disabled:cursor-default"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-navy-900">{t.description}</p>
                <p className="text-xs text-slate-500">
                  {formatDate(t.posted_at)} · {titleCase(t.type)}
                </p>
              </div>
              <span className={`shrink-0 text-sm font-semibold tabular-nums ${t.direction === "credit" ? "text-teal-700" : "text-slate-900"}`}>
                {formatSignedMinor(t.signed_amount_minor)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
