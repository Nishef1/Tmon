import type { EntryHorizon, EntrySetup } from "@/lib/api";
import { faNumber, faPercent } from "@/lib/format";

export const LABEL_FA: Record<EntrySetup["label"], string> = {
  better: "بهتر از بقیهٔ سهم‌ها",
  worse: "بدتر از بقیهٔ سهم‌ها",
  same: "فرقی نداشته",
  mixed: "ناپایدار",
  too_few: "نمونهٔ کم",
};

const LABEL_CLS: Record<EntrySetup["label"], string> = {
  better: "border-up text-up",
  worse: "border-down text-down",
  same: "border-line text-muted",
  mixed: "border-line text-muted",
  too_few: "border-line text-muted",
};

/** The chart colour of an entry candle by its tested label. */
export function labelColor(label: EntrySetup["label"]): string {
  return label === "better" ? "var(--up)" : label === "worse" ? "var(--down)" : "var(--muted)";
}

export function LabelChip({ label }: { label: EntrySetup["label"] }) {
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-bold ${LABEL_CLS[label]}`}
      data-label={label}
    >
      {LABEL_FA[label]}
    </span>
  );
}

const pct = (x: number | null | undefined, d = 0) => (x == null ? "—" : faPercent(x, d));

/** Two bars on one scale: how often the price was above the entry after this setup, and after
 *  buying any liquid symbol on the same days. */
export function OddsBars({ x, compact = false }: { x: EntryHorizon; compact?: boolean }) {
  const tone = x.edge >= 0.03 ? "bg-up" : x.edge <= -0.03 ? "bg-down" : "bg-accent";
  return (
    <div className="space-y-0.5" data-testid="odds-bars">
      <div className="flex items-center gap-2 text-xs">
        <span className={compact ? "w-16 shrink-0" : "w-24 shrink-0"}>این حالت</span>
        <span className="relative h-3 flex-1 rounded bg-surface-2">
          <span
            className={`absolute inset-y-0 start-0 rounded ${tone}`}
            style={{ width: `${100 * x.up}%` }}
          />
          <span className="absolute inset-y-0 start-1/2 w-px bg-ink/30" aria-hidden />
        </span>
        <b className="w-10 shrink-0 text-end">{pct(x.up)}</b>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted">
        <span className={compact ? "w-16 shrink-0" : "w-24 shrink-0"}>همان روزها</span>
        <span className="relative h-2 flex-1 rounded bg-surface-2">
          <span
            className="absolute inset-y-0 start-0 rounded bg-faint"
            style={{ width: `${100 * x.up_all}%` }}
          />
          <span className="absolute inset-y-0 start-1/2 w-px bg-ink/30" aria-hidden />
        </span>
        <span className="w-10 shrink-0 text-end">{pct(x.up_all)}</span>
      </div>
    </div>
  );
}

/** The candles after the setup, horizon by horizon, with each half of the history apart. */
export function HorizonTable({ s }: { s: EntrySetup }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[30rem] text-xs" data-testid="entry-horizons">
        <thead className="text-muted">
          <tr>
            <th className="py-1 text-start font-normal">چند کندل بعد</th>
            <th className="py-1 text-start font-normal">بالاتر از خرید</th>
            <th className="py-1 text-start font-normal">بقیهٔ سهم‌ها</th>
            <th className="py-1 text-start font-normal">تفاوت</th>
            <th className="py-1 text-start font-normal">نیمهٔ اول / دوم</th>
            <th className="py-1 text-start font-normal">میانهٔ بازده</th>
          </tr>
        </thead>
        <tbody>
          {s.horizons.map((x) => (
            <tr key={x.h} className={`border-t border-line ${x.h === s.best_h ? "font-bold" : ""}`}>
              <td className="py-1">{faNumber(x.h)}</td>
              <td className="py-1">{pct(x.up)}</td>
              <td className="py-1 text-muted">{pct(x.up_all)}</td>
              <td
                className={`py-1 ${x.edge >= 0.03 ? "text-up" : x.edge <= -0.03 ? "text-down" : ""}`}
              >
                {faPercent(x.edge, 1, true)}
              </td>
              <td className="py-1">
                {(x.halves_edge ?? [])
                  .map((e) => (e == null ? "—" : faPercent(e, 1, true)))
                  .join(" / ")}
              </td>
              <td className="py-1">{x.median == null ? "—" : faPercent(x.median, 1, true)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What the path after the entry looked like: a drop below the entry soon after, and which came
 *  first of a gain and a loss. */
export function PathRisk({
  s,
  dip,
  within,
  win,
  loss,
  path,
}: {
  s: EntrySetup;
  dip: number;
  within: number;
  win: number;
  loss: number;
  path: number;
}) {
  const rows: [string, number | null | undefined, number | null | undefined, boolean][] = [
    [
      `در ${faNumber(within)} کندل بعد، پایانی ${pct(Math.abs(dip))} زیر قیمت خرید رفته`,
      s.dip_hit,
      s.dip_hit_all,
      false,
    ],
    [
      `در ${faNumber(path)} کندل، اول ${pct(win)} سود رسیده (پیش از ${pct(Math.abs(loss))} ضرر)`,
      s.win,
      s.win_all,
      true,
    ],
    [`در ${faNumber(path)} کندل، اول ${pct(Math.abs(loss))} ضرر رسیده`, s.loss, s.loss_all, false],
  ];
  return (
    <ul className="space-y-1 text-xs" data-testid="entry-path">
      {rows.map(([k, v, all, good]) => {
        const d = v != null && all != null ? v - all : null;
        const tone =
          d == null || Math.abs(d) < 0.02 ? "" : d > 0 === good ? "text-up" : "text-down";
        return (
          <li key={k} className="flex flex-wrap justify-between gap-2 border-b border-line py-1">
            <span>{k}</span>
            <span>
              <b className={tone}>{pct(v)}</b>
              <span className="text-muted"> در برابر {pct(all)}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

const YEAR_MIN = 50;

/** The setup Iranian year by Iranian year: one cell per year, green when it beat every other
 *  symbol on the same days by 3 points or more at ``h`` candles, red when it trailed by as much,
 *  grey in between; faded years had fewer than 50 entries and are not counted. */
export function YearStrip({ s, h }: { s: EntrySetup; h: number }) {
  const k = h <= 1 ? "e1" : h <= 5 ? "e5" : "e20";
  const hh = h <= 1 ? 1 : h <= 5 ? 5 : 20;
  const ys = s.years.filter((y) => y[k] != null);
  if (ys.length === 0) return null;
  const counted = ys.filter((y) => y.n >= YEAR_MIN);
  const better = counted.filter((y) => y[k]! >= 0.03).length;
  const worse = counted.filter((y) => y[k]! <= -0.03).length;
  return (
    <div className="space-y-1" data-testid="year-strip" data-h={hh}>
      <div className="flex flex-wrap gap-0.5" dir="ltr">
        {ys.map((y) => {
          const e = y[k]!;
          const bg = e >= 0.03 ? "bg-up" : e <= -0.03 ? "bg-down" : "bg-faint";
          const thin = y.n < YEAR_MIN;
          return (
            <span
              key={y.year}
              className={`h-4 w-3 rounded-sm ${bg} ${thin ? "opacity-30" : ""}`}
              title={`${faNumber(y.year)}: ${faPercent(e, 0, true)} (${faNumber(y.n)} بار)`}
              data-year={y.year}
            />
          );
        })}
      </div>
      <p className="text-xs text-muted">
        سال به سال ({hh === 1 ? "کندل بعد" : `${faNumber(hh)} کندل بعد`}): از{" "}
        {faNumber(counted.length)} سال، <b className="text-up">{faNumber(better)}</b> سال بهتر و{" "}
        <b className="text-down">{faNumber(worse)}</b> سال بدتر از بقیهٔ سهم‌ها؛ بقیه فرقی نداشته.
        از {faNumber(ys[0].year)} تا {faNumber(ys[ys.length - 1].year)}.
      </p>
    </div>
  );
}
