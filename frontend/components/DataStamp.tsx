import { apiGet } from "@/lib/api";
import type { components } from "@/lib/api-schema";
import { jalali } from "@/lib/format";

type Freshness = components["schemas"]["FreshnessOut"];

const KIND: Record<string, string> = {
  prices: "قیمت‌ها",
  flows: "حقیقی و حقوقی",
  index: "شاخص",
  order_book: "صف و سفارش‌ها",
  macro: "دلار، طلا و تورم",
  news: "اخبار",
  codal: "کدال",
  model: "مدل و پیشنهادها",
};

const moment = (iso: string) =>
  new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
    timeZone: "Asia/Tehran",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));

/** When the database was last written, read fresh on every page view. */
export async function DataStamp() {
  const r = await apiGet<Freshness>("/freshness");
  if (!r.ok || !r.data.updated_at) return null;
  const prices = r.data.items.find((i) => i.kind === "prices");
  return (
    <details className="mb-4 text-xs text-muted">
      <summary className="cursor-pointer select-none">
        {prices?.date ? `قیمت‌ها تا ${jalali(prices.date)}` : "قیمت‌ها: نامشخص"}
        {" · "}آخرین دریافت از هر منبعی: {moment(r.data.updated_at)} (ساعت تهران)
      </summary>
      <ul className="mt-2 grid gap-1 sm:grid-cols-2">
        {r.data.items.map((i) => (
          <li key={i.kind}>
            {KIND[i.kind] ?? i.kind}: داده تا {i.date ? jalali(i.date) : "—"}
            {i.fetched_at ? `، گرفته‌شده ${moment(i.fetched_at)}` : ""}
          </li>
        ))}
      </ul>
    </details>
  );
}
