const egp = new Intl.NumberFormat("en-EG", { style: "currency", currency: "EGP", minimumFractionDigits: 2 });
const egpCompact = new Intl.NumberFormat("en-EG", { style: "currency", currency: "EGP", notation: "compact", maximumFractionDigits: 1 });

/** Money arrives as integer piastres; divide by 100 for display only. */
export function formatMinor(minor: number): string {
  return egp.format(minor / 100);
}

export function formatMinorCompact(minor: number): string {
  return egpCompact.format(minor / 100);
}

export function formatSignedMinor(minor: number): string {
  const s = egp.format(Math.abs(minor) / 100);
  return minor < 0 ? `−${s}` : `+${s}`;
}

/** Convert a validated decimal string ("1250.5") to integer minor units without floating point. */
export function decimalToMinor(value: string): number | null {
  const m = /^(\d{1,9})(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!m) return null;
  return parseInt(m[1], 10) * 100 + parseInt((m[2] ?? "").padEnd(2, "0") || "0", 10);
}

/** Format a server decimal string ("1250.50") as EGP via integer minor units. */
export function formatDecimal(value: string): string {
  const neg = value.startsWith("-");
  const minor = decimalToMinor(neg ? value.slice(1) : value);
  if (minor === null) return value;
  return formatMinor(neg ? -minor : minor);
}

const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDate(iso: string): string {
  return dateFmt.format(new Date(iso));
}

export function formatDateTime(iso: string): string {
  return dateTimeFmt.format(new Date(iso));
}

export function monthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", { month: "short" }).format(new Date(Date.UTC(y, m - 1, 1)));
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}
