/**
 * Number presentation only: grouping, decimals, parentheses for negatives.
 * No arithmetic on engine values happens here.
 */

const fixed = (decimals: number) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

const FORMATS = {
  usd: fixed(2),
  price: fixed(2),
  mw: fixed(1),
  mmbtu: fixed(0),
} as const;

export type NumberFormat = keyof typeof FORMATS;

/** Negative values are shown in parentheses, never with a bare minus sign. */
export function formatNumber(value: number, format: NumberFormat): string {
  const text = FORMATS[format].format(Math.abs(value));
  return value < 0 ? `(${text})` : text;
}

const HOUR = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZoneName: "short",
});

/** Hour-beginning stamp in market local time, e.g. "Wed, Jan 15, 2025, 14:00 EST". */
export function formatHour(tsUtc: string): string {
  return HOUR.format(new Date(tsUtc));
}
