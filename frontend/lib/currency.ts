/**
 * Indian-locale currency and number formatting (₹, lakh/crore grouping).
 */

function toNumber(value: number | string | null | undefined): number {
  const num = typeof value === 'string' ? parseFloat(value) : value ?? 0;
  return Number.isFinite(num) ? (num as number) : 0;
}

/** Full currency display, e.g. ₹1,23,456.00 */
export function formatINR(value: number | string | null | undefined, decimals = 2): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(toNumber(value));
}

/** Compact currency for chart axes/tooltips, e.g. ₹1.2L, ₹3.4Cr, ₹850 */
export function formatINRCompact(value: number | string | null | undefined): string {
  const num = toNumber(value);
  const abs = Math.abs(num);
  if (abs >= 1_00_00_000) return `₹${(num / 1_00_00_000).toFixed(1)}Cr`;
  if (abs >= 1_00_000) return `₹${(num / 1_00_000).toFixed(1)}L`;
  if (abs >= 1_000) return `₹${(num / 1_000).toFixed(1)}k`;
  return `₹${num.toFixed(0)}`;
}

/** Indian-grouped plain number, no currency symbol — for quantities/inputs. */
export function formatNumberIN(value: number | string | null | undefined, decimals = 0): string {
  return new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(toNumber(value));
}

/** Live-typing input formatter with Indian digit grouping (e.g. 12,34,567). */
export function formatIndianNumberInput(value: string): string {
  const cleaned = value.replace(/[^0-9.]/g, '');
  const parts = cleaned.split('.');
  parts[0] = parts[0].replace(/(\d)(?=(\d\d)+(\d)(?!\d))/g, '$1,');
  return parts.slice(0, 2).join('.');
}
