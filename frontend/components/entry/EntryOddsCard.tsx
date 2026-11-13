import Link from "next/link";
import type { DashEntry, EntryOdds, EntrySetup } from "@/lib/api";
import { faDigits, faNumber, faPercent, jalali } from "@/lib/format";
import { HorizonTable, LabelChip, OddsBars, PathRisk } from "./EntryParts";

const RANK: Record<EntrySetup["label"], number> = {
  better: 0,
  worse: 1,
  mixed: 2,
  same: 3,
  too_few: 4,
};

/** "If I buy now": the candles of this symbol's current state, and how the candles after the
 *  same state went on the whole exchange, against buying any other symbol on those days. */
export function EntryOddsCard({ e, odds }: { e: DashEntry; odds: EntryOdds | null }) {
  const now = [...e.now].sort((a, b) => RANK[a.label] - RANK[b.label]);
  const path =
    odds?.available && odds.dip != null && odds.win != null && odds.loss != null
      ? {
          dip: odds.dip,
          within: odds.dip_within ?? 10,
          win: odds.win,
          loss: odds.loss,
          path: odds.path ?? 20,
        }
      : null;
  const recent = e.marks.filter((m) => m.ago <= 20);
  return (
    <section className="card space-y-3" data-testid="entry-odds">
      <div>
        <h2 className="font-bold">اگر امروز بخرم، کندل‌های بعدی معمولاً چه شده‌اند؟</h2>
        <p className="text-xs text-muted">
          تا {jalali(e.as_of)}. هر حالت روی همهٔ تاریخچهٔ بورس تهران آزموده شده و با خریدن هر سهم
          دیگری در همان روزها مقایسه شده است. این‌ها آمار گذشته‌اند، نه پیش‌بینی و نه توصیه.
        </p>
      </div>
      {e.lines.length > 0 && (
        <ul className="list-disc space-y-1 ps-5 text-sm">
          {e.lines.map((l) => (
            <li key={l}>{faDigits(l)}</li>
          ))}
        </ul>
      )}
      {now.length === 0 ? (
        <p className="text-sm text-muted">سهم امروز در هیچ‌کدام از حالت‌های آزموده‌شده نیست.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2" data-testid="entry-now">
          {now.map((s) => {
            const h1 = s.horizons.find((x) => x.h === 1);
            const h5 = s.horizons.find((x) => x.h === 5);
            return (
              <li key={s.key} className="rounded-lg border border-line p-3" data-key={s.key}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <b className="text-sm">{s.title}</b>
                  <LabelChip label={s.label} />
                </div>
                <p className="mt-1 text-xs">{faDigits(s.verdict)}</p>
                <div className="mt-2 space-y-2">
                  {h1 && (
                    <div>
                      <p className="text-xs text-muted">کندل بعدی بالاتر بسته شده</p>
                      <OddsBars x={h1} compact />
                    </div>
                  )}
                  {h5 && (
                    <div>
                      <p className="text-xs text-muted">۵ کندل بعد بالاتر از قیمت خرید</p>
                      <OddsBars x={h5} compact />
                    </div>
                  )}
                </div>
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-accent">
                    همهٔ بازه‌ها و ریسک مسیر
                  </summary>
                  <div className="mt-2 space-y-2">
                    <HorizonTable s={s} />
                    {path && <PathRisk s={s} {...path} />}
                  </div>
                </details>
                <p className="mt-2 text-xs text-muted">
                  {faNumber(s.n)} بار در {faNumber(s.symbols)} نماد
                  {s.locked_share != null &&
                    s.locked_share > 0.05 &&
                    `؛ ${faPercent(s.locked_share, 0)} از دفعه‌ها چون روز خرید صف بوده کنار گذاشته شده`}
                  .
                </p>
              </li>
            );
          })}
        </ul>
      )}
      {recent.length > 0 && (
        <p className="text-xs">
          کندل‌های ورودِ ۲۰ روز اخیر:{" "}
          {recent.map((m) => `${m.title} (${faNumber(m.ago)} روز پیش)`).join("، ")}. روی نمودار
          پایین با نشانه دیده می‌شوند.
        </p>
      )}
      <p className="text-xs text-muted">
        <Link href="/model#entry" className="underline">
          آزمایشگاه ورود
        </Link>{" "}
        همهٔ حالت‌ها را با هم مقایسه می‌کند. هیچ حالتی تضمین نمی‌کند کندل بعدی سبز باشد؛ بهترین
        حالت‌ها هم در نزدیک به نیمی از دفعه‌ها پایین‌تر رفته‌اند.
      </p>
    </section>
  );
}
