import { colTone, fmtCol, type ColumnItem, type InstrumentColumns } from "@/lib/columns";
import { jalali } from "@/lib/format";

/** One row: what it is, the symbol's value, and the same number for its industry and the market. */
function Line({ it, group }: { it: ColumnItem; group: string }) {
  const def = { key: it.key, group, kind: it.kind };
  const text = it.kind === "text";
  return (
    <li
      className="grid grid-cols-[1fr_auto] items-baseline gap-x-3 gap-y-0.5 border-b border-line/60 py-1.5 last:border-0"
      data-col={it.key}
    >
      <span className="text-sm" title={it.hint || undefined}>
        {it.label}
      </span>
      <span className={`text-sm font-bold tabular-nums ${colTone(def, it.value)}`} dir="ltr">
        {fmtCol(def, it.value)}
      </span>
      {!text && (it.industry_median != null || it.market_median != null) && (
        <span className="col-span-2 flex flex-wrap gap-x-3 text-xs text-muted">
          {it.industry_median != null && (
            <span>
              میانهٔ صنعت{" "}
              <span dir="ltr" className="tabular-nums">
                {fmtCol(def, it.industry_median)}
              </span>
            </span>
          )}
          {it.market_median != null && (
            <span>
              میانهٔ بازار{" "}
              <span dir="ltr" className="tabular-nums">
                {fmtCol(def, it.market_median)}
              </span>
            </span>
          )}
        </span>
      )}
    </li>
  );
}

/** Every derived column of the symbol, grouped, with the industry and market medians beside it.
 *  Display only: no verdict or weight reads these (OPEN_QUESTIONS 138). */
export function ColumnsCard({ c }: { c: InstrumentColumns }) {
  const hasFilings = c.statement_kind != null;
  return (
    <div className="space-y-4" data-testid="derived-columns">
      <p className="text-sm text-muted">
        ستون‌های ترکیبی از داده‌های ذخیره‌شده ساخته می‌شوند، نه از منبع تازه. قیمت‌ها تا{" "}
        {c.as_of ? jalali(c.as_of) : "—"}
        {c.flow_date ? ` و پول حقیقی و حقوقی تا ${jalali(c.flow_date)}` : ""}
        {c.book_date ? ` و تابلو تا ${jalali(c.book_date)}` : ""}.
        {hasFilings
          ? ` صورت مالی: ${c.statement_kind === "consolidated" ? "تلفیقی" : "جداگانه"}، دورهٔ منتهی به ${jalali(c.statement_period_end)}.`
          : ""}{" "}
        سهم شناور و وزن در شاخص برآورد ما هستند و رقم رسمی نیستند؛ امتیازها شمارش ساده‌اند و
        آزمون‌نشده. توصیه نیستند.
      </p>
      <div className="grid items-start gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {c.sections.map((s) => (
          <section key={s.key} className="rounded-xl border border-line/70 bg-surface-2/40 p-3">
            <h3 className="mb-1 text-sm font-bold">{s.label}</h3>
            {s.note ? (
              <p className="text-xs text-muted" role="status">
                {s.note}
              </p>
            ) : null}
            {!s.note || s.items.some((i) => i.value != null) ? (
              <ul>
                {s.items
                  .filter((i) => !s.note || i.value != null)
                  .map((i) => (
                    <Line key={i.key} it={i} group={s.key} />
                  ))}
              </ul>
            ) : null}
          </section>
        ))}
      </div>
    </div>
  );
}
