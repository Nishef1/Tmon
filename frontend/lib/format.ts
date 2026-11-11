// Persian-digit number formatting and Jalali dates. Storage is UTC/ISO; display is Asia/Tehran.

const MINUS = "−";

export type NumKind = "percent" | "price" | "count" | "plain";

function group(n: number, digits: number): string {
  return new Intl.NumberFormat("fa-IR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
}

export function faNumber(n: number, digits = 0): string {
  return group(n, digits);
}

/** ``0.031`` -> ``۳٫۱٪``. ``signed`` adds an explicit + for positive values. */
export function faPercent(fraction: number, digits = 1, signed = false): string {
  const v = fraction * 100;
  const body = group(Math.abs(v), digits);
  const zero = Number(Math.abs(v).toFixed(digits)) === 0;
  const sign = zero ? "" : v < 0 ? MINUS : signed ? "+" : "";
  return `${sign}${body}٪`;
}

/** Rial price, rounded to a whole rial. */
export function faPrice(n: number): string {
  return group(Math.round(n), 0);
}

export function formatValue(
  value: number | null | undefined,
  kind: NumKind,
  digits?: number,
  signed = false,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  switch (kind) {
    case "percent":
      return faPercent(value, digits ?? 1, signed);
    case "price":
      return faPrice(value);
    case "count":
      return faNumber(value, 0);
    default: {
      const s = group(Math.abs(value), digits ?? 2);
      return value < 0 && Number(Math.abs(value).toFixed(digits ?? 2)) !== 0 ? `${MINUS}${s}` : s;
    }
  }
}

const TZ = "Asia/Tehran";

function toDate(iso: string): Date {
  // Noon UTC keeps the calendar day stable in Tehran (UTC+3:30) for a date-only value.
  return new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T12:00:00Z` : iso);
}

const jalaliLong = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: TZ,
  year: "numeric",
  month: "long",
  day: "numeric",
});
const jalaliShort = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: TZ,
  year: "2-digit",
  month: "2-digit",
  day: "2-digit",
});
const jalaliDay = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: TZ,
  weekday: "long",
  year: "numeric",
  month: "long",
  day: "numeric",
});
const jalaliMonthDay = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: TZ,
  month: "short",
  day: "numeric",
});
const jalaliMonthYear = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: TZ,
  year: "numeric",
  month: "short",
});

export type DateStyle = "long" | "short" | "weekday" | "monthDay" | "monthYear";

export function jalali(iso: string | null | undefined, style: DateStyle = "long"): string {
  if (!iso) return "—";
  const d = toDate(iso);
  if (Number.isNaN(d.getTime())) return "—";
  switch (style) {
    case "short":
      return jalaliShort.format(d);
    case "weekday":
      return jalaliDay.format(d);
    case "monthDay":
      return jalaliMonthDay.format(d);
    case "monthYear":
      return jalaliMonthYear.format(d);
    default:
      return jalaliLong.format(d);
  }
}
