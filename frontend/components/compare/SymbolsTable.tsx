import Link from "next/link";
import type { EntrySetup, InstrumentDashboard, InstrumentDetail } from "@/lib/api";
import { faNumber, faPercent } from "@/lib/format";
import { signTone, verdictPill } from "@/lib/ui";
import { LabelChip } from "@/components/entry/EntryParts";
import { COLORS } from "./colors";

export type Picked = { detail: InstrumentDetail; dash: InstrumentDashboard | null };

const RANK: Record<EntrySetup["label"], number> = {
  better: 0,
  worse: 1,
  mixed: 2,
  same: 3,
  too_few: 4,
};

/** The setup of the symbol's current state that said the most in the past: a firm label first,
 *  then the narrowest condition (fewest cases). */
function telling(d: InstrumentDashboard | null): EntrySetup | null {
  const now = d?.entry?.now ?? [];
  return [...now].sort((a, b) => RANK[a.label] - RANK[b.label] || a.n - b.n)[0] ?? null;
}

const pct = (x: number | null | undefined, d = 0, signed = false) =>
  x == null ? "—" : faPercent(x, d, signed);

/** Side by side: price, risk, the candle streak now and how the candles after that state went. */
export function SymbolsTable({ picked }: { picked: Picked[] }) {
  const cols = picked.map((p) => {
    const d = p.dash;
    const r = d?.technical?.risk;
    const e = d?.entry;
    const s = telling(d);
    return {
      p,
      d,
      r,
      e,
      s,
      h1: s?.horizons.find((x) => x.h === 1),
      h5: s?.horizons.find((x) => x.h === 5),
    };
  });
  type C = (typeof cols)[number];
  const rows: [string, (c: C) => React.ReactNode][] = [
    [
      "قیمت پایانی",
      (c) =>
        c.d?.price?.close == null ? (
          "—"
        ) : (
          <>
            {faNumber(c.d.price.close)}{" "}
            <span className={signTone(c.d.price.close_change)}>
              {pct(c.d.price.close_change, 1, true)}
            </span>
          </>
        ),
    ],
    [
      "بازده ۲۵۰ روز معاملاتی",
      (c) => <span className={signTone(c.r?.ret_1y)}>{pct(c.r?.ret_1y, 0, true)}</span>,
    ],
    ["نوسان سالانه", (c) => pct(c.r?.vol_ann)],
    ["بیشترین افت", (c) => pct(c.r?.max_dd)],
    ["بتا به شاخص کل", (c) => (c.r?.beta_index == null ? "—" : faNumber(c.r.beta_index, 2))],
    [
      "کندل‌های اخیر",
      (c) =>
        !c.e ? (
          "—"
        ) : c.e.green ? (
          <span className="text-up">{faNumber(c.e.green)} سبز پشت سر هم</span>
        ) : c.e.red ? (
          <span className="text-down">{faNumber(c.e.red)} قرمز پشت سر هم</span>
        ) : (
          "بی‌تغییر"
        ),
    ],
    [
      "وضع",
      (c) =>
        !c.e
          ? "—"
          : [c.e.in_base && "کف چندماهه", c.e.in_up && "روند صعودی"].filter(Boolean).join("، ") ||
            "نه کف، نه روند صعودی",
    ],
    [
      "گویاترین حالتِ الان",
      (c) =>
        c.s ? (
          <span className="space-y-1">
            <span className="block">{c.s.title}</span>
            <LabelChip label={c.s.label} />
          </span>
        ) : (
          "—"
        ),
    ],
    [
      "کندل بعد بالاتر (این حالت / همه)",
      (c) =>
        c.h1 ? (
          <>
            <b>{pct(c.h1.up)}</b> <span className="text-muted">/ {pct(c.h1.up_all)}</span>
          </>
        ) : (
          "—"
        ),
    ],
    [
      "۵ کندل بعد بالاتر (این حالت / همه)",
      (c) =>
        c.h5 ? (
          <>
            <b>{pct(c.h5.up)}</b> <span className="text-muted">/ {pct(c.h5.up_all)}</span>
          </>
        ) : (
          "—"
        ),
    ],
    [
      "۱۰٪ سود پیش از ۵٪ ضرر (۲۰ کندل)",
      (c) =>
        c.s?.win == null ? (
          "—"
        ) : (
          <>
            <b>{pct(c.s.win)}</b> <span className="text-muted">/ {pct(c.s.win_all)}</span>
          </>
        ),
    ],
    [
      "حکم مدل",
      (c) =>
        c.d ? <span className={verdictPill(c.d.decision.verdict)}>{c.d.decision.label}</span> : "—",
    ],
  ];
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="tbl min-w-[36rem]" data-testid="compare-table">
          <caption className="sr-only">مقایسهٔ نمادها کنار هم</caption>
          <thead>
            <tr className="border-b border-line">
              <th scope="col" />
              {cols.map((c, i) => (
                <th key={c.p.detail.instrument.id} scope="col">
                  <Link
                    href={`/instruments/${c.p.detail.instrument.id}`}
                    className="inline-flex items-center gap-1.5 underline"
                  >
                    <span
                      className="inline-block h-2.5 w-2.5 rounded-full"
                      style={{ background: COLORS[i % COLORS.length] }}
                      aria-hidden
                    />
                    {c.p.detail.instrument.symbol}
                  </Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([k, f]) => (
              <tr key={k} className="border-b border-line last:border-0">
                <th scope="row" className="px-2 py-1.5 text-start text-xs font-normal text-muted">
                  {k}
                </th>
                {cols.map((c) => (
                  <td key={c.p.detail.instrument.id} className="px-2 py-1.5 text-sm">
                    {f(c)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">
        «این حالت / همه»: در گذشته بعد از همین وضع، چند بار قیمت بالاتر از قیمت خرید بوده، در برابر
        خریدن هر سهم دیگری در همان روزها. گویاترین حالت یعنی حالتی که در هر دو نیمهٔ تاریخچه حکم
        گرفته یا باریک‌ترین شرط را دارد. آمار گذشته است، نه پیش‌بینی و نه توصیه.
      </p>
    </div>
  );
}
