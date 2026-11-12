// Persian-digit number formatting and Jalali dates. Storage is UTC/ISO; display is Asia/Tehran.

const MINUS = "−";

/**
 * Bidi isolate: a signed number or a percent keeps one fixed order inside right-to-left text,
 * sign on the left of the digits and ٪ after them ("+۵٫۷٪", "−۱٫۲٪"), wherever it appears.
 */
const LRI = "⁦";
const PDI = "⁩";
export function ltr(text: string): string {
  return `${LRI}${text}${PDI}`;
}

export type NumKind = "percent" | "price" | "count" | "plain";

function group(n: number, digits: number): string {
  return new Intl.NumberFormat("fa-IR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
}

/** Latin digits inside a server-written sentence -> Persian digits. */
export function faDigits(text: string): string {
  return text
    .replace(/[⁦⁩]/g, "")
    .replace(/(\d)\.(\d)/g, "$1٫$2") // decimal point
    .replace(/(^|[\s(])-(?=\d)/g, "$1−") // minus sign
    .replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)])
    .replace(/[+−]?[۰-۹][۰-۹٫٬]*٪?/g, (m) => (/^[+−]|٪$/.test(m) ? ltr(m) : m)); // signed numbers and percents
}

export function faNumber(n: number, digits = 0): string {
  const s = group(n, digits);
  return /[−-]/.test(s) ? ltr(s.replace(/[‎‏]/g, "")) : s;
}

/** ``0.031`` -> ``۳٫۱٪``. ``signed`` adds an explicit + for positive values. */
export function faPercent(fraction: number, digits = 1, signed = false): string {
  const v = fraction * 100;
  const body = group(Math.abs(v), digits);
  const zero = Number(Math.abs(v).toFixed(digits)) === 0;
  const sign = zero ? "" : v < 0 ? MINUS : signed ? "+" : "";
  return ltr(`${sign}${body}٪`);
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
      return value < 0 && Number(Math.abs(value).toFixed(digits ?? 2)) !== 0
        ? ltr(`${MINUS}${s}`)
        : s;
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
const jalaliWeekday = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: TZ,
  weekday: "long",
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
      return `${jalaliWeekday.format(d)}، ${jalaliLong.format(d)}`;
    case "monthDay":
      return jalaliMonthDay.format(d);
    case "monthYear":
      return jalaliMonthYear.format(d);
    default:
      return jalaliLong.format(d);
  }
}

/** Rial amount in short toman units: ``۱٫۲ همت``, ``۴۵٫۰ میلیارد``. */
export function faToman(rial: number | null | undefined): string {
  if (rial == null) return "—";
  const t = rial / 10;
  const a = Math.abs(t);
  if (a >= 1e12) return `${group(t / 1e12, 2)} همت`;
  if (a >= 1e9) return `${group(t / 1e9, 1)} میلیارد`;
  if (a >= 1e6) return `${group(t / 1e6, 1)} میلیون`;
  return group(t, 0);
}

/** A share count in short form: ``۲٫۵ میلیارد``, ``۳۴۰ هزار``. */
export function faCount(n: number | null | undefined): string {
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return `${group(n / 1e9, 1)} میلیارد`;
  if (a >= 1e6) return `${group(n / 1e6, 1)} میلیون`;
  if (a >= 1e3) return `${group(n / 1e3, 0)} هزار`;
  return group(n, 0);
}

const RULE_NAMES: Record<string, string> = {
  commission_buy: "کارمزد خرید",
  commission_sell: "کارمزد فروش",
  price_limit: "حد نوسان قیمت",
  sell_tax: "مالیات فروش",
  tick_size: "گام قیمت",
  lot_size: "اندازهٔ سفارش",
};

/** Calibration warnings come from the backend with raw rule keys; show them in plain Persian. */
export function friendlyWarning(w: string): string {
  return faDigits(
    w
      .replace(/«([a-z_]+)»/g, (_, k: string) => `«${RULE_NAMES[k] ?? k}»`)
      .replace(/ ?\(verified=false\)/g, "")
      .replace("تأییدنشده است", "هنوز با منبع رسمی تطبیق داده نشده است"),
  );
}
