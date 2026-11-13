"use client";

import { useMemo, useState } from "react";
import type { EntryOdds, EntrySetup } from "@/lib/api";
import { faDigits, faNumber, faPercent, jalali } from "@/lib/format";
import { HorizonTable, LabelChip, OddsBars, PathRisk, YearStrip } from "./EntryParts";

type Group = "streak" | "base" | "uptrend";
const GROUPS: [Group, string][] = [
  ["streak", "شمع‌های پشت سر هم"],
  ["base", "ورود از کف چندماهه"],
  ["uptrend", "ورود در روند صعودی"],
];
const STREAK = ["r6", "r45", "r3", "r2", "r1", "g1", "g2", "g3", "g45", "g6"];
const STREAK_FA: Record<string, string> = {
  r6: "۶+ قرمز",
  r45: "۴–۵ قرمز",
  r3: "۳ قرمز",
  r2: "۲ قرمز",
  r1: "۱ قرمز",
  g1: "۱ سبز",
  g2: "۲ سبز",
  g3: "۳ سبز",
  g45: "۴–۵ سبز",
  g6: "۶+ سبز",
};
type Sort = "edge" | "up" | "n";

const at = (s: EntrySetup, h: number) => s.horizons.find((x) => x.h === h);

/** The streak ladder: after how many green or red candles in a row the price was higher h
 *  candles later, against every other symbol on the same days. */
function Ladder({ setups, h }: { setups: Map<string, EntrySetup>; h: number }) {
  const rows = STREAK.map((k) => setups.get(k)).filter((s): s is EntrySetup => !!s);
  const edges = rows.map((s) => at(s, h)?.edge ?? 0);
  const max = Math.max(0.05, ...edges.map(Math.abs));
  return (
    <figure className="space-y-1" data-testid="streak-ladder">
      <figcaption className="text-xs text-muted">
        تفاوتِ «بالاتر از قیمت خرید پس از {faNumber(h)} کندل» با خریدن بقیهٔ سهم‌ها در همان روزها؛
        راست یعنی بهتر، چپ بدتر. خط نازک: نیمهٔ اول و دوم تاریخچه.
      </figcaption>
      {rows.map((s) => {
        const x = at(s, h);
        if (!x) return null;
        const w = (Math.abs(x.edge) / max) * 50;
        const tone = x.edge >= 0 ? "bg-up" : "bg-down";
        return (
          <div key={s.key} className="flex items-center gap-2 text-xs" data-key={s.key}>
            <span className="w-16 shrink-0">{STREAK_FA[s.key]}</span>
            <span className="relative h-4 flex-1 rounded bg-surface-2">
              <span className="absolute inset-y-0 start-1/2 w-px bg-ink/40" aria-hidden />
              <span
                className={`absolute inset-y-0.5 rounded-sm ${tone} ${s.label === "better" || s.label === "worse" ? "" : "opacity-40"}`}
                style={
                  x.edge >= 0
                    ? { insetInlineStart: "50%", width: `${w}%` }
                    : { insetInlineEnd: "50%", width: `${w}%` }
                }
              />
              {(x.halves_edge ?? []).map((e, i) =>
                e == null ? null : (
                  <span
                    key={i}
                    className="absolute inset-y-0 w-0.5 bg-ink/70"
                    style={{
                      insetInlineStart: `${50 + (Math.max(-max, Math.min(max, e)) / max) * 50}%`,
                    }}
                    title={`نیمهٔ ${i === 0 ? "اول" : "دوم"}: ${faPercent(e, 1, true)}`}
                  />
                ),
              )}
            </span>
            <span className="w-24 shrink-0 text-end">
              <b>{faPercent(x.up, 0)}</b>
              <span className="text-muted"> / {faPercent(x.up_all, 0)}</span>
            </span>
          </div>
        );
      })}
    </figure>
  );
}

/** Every tested entry condition: pick a group and a horizon, read how often the price was above
 *  the entry afterwards and how that compares with buying anything else on the same days. */
export function EntryLab({ d }: { d: EntryOdds }) {
  const [group, setGroup] = useState<Group>("streak");
  const [h, setH] = useState(1);
  const [sort, setSort] = useState<Sort>("edge");
  const [onlyFirm, setOnlyFirm] = useState(false);
  const byKey = useMemo(() => new Map(d.setups.map((s) => [s.key, s])), [d.setups]);
  const horizons = d.setups[0]?.horizons.map((x) => x.h) ?? [1, 5];
  const any = byKey.get("any");
  const list = d.setups
    .filter((s) => s.group === group && (!onlyFirm || s.label === "better" || s.label === "worse"))
    .sort((a, b) => {
      const x = at(a, h);
      const y = at(b, h);
      if (sort === "n") return b.n - a.n;
      if (sort === "up") return (y?.up ?? 0) - (x?.up ?? 0);
      return (y?.edge ?? 0) - (x?.edge ?? 0);
    });
  const firm = d.setups.filter((s) => s.label === "better" || s.label === "worse");
  const path =
    d.dip != null && d.win != null && d.loss != null
      ? { dip: d.dip, within: d.dip_within ?? 10, win: d.win, loss: d.loss, path: d.path ?? 20 }
      : null;
  const anyH = any && at(any, h);

  return (
    <section id="entry" className="space-y-4" data-testid="entry-lab">
      <div>
        <h2 className="text-xl font-extrabold">
          آزمایشگاه ورود: بعد از کدام کندل، کندل‌های بعدی سبز بوده‌اند؟
        </h2>
        <p className="text-sm text-muted">
          {faNumber(d.setups.length)} حالت ورود روی همهٔ نمادهای بورس تهران از{" "}
          {jalali(d.history_first)} تا {jalali(d.history_last)} آزموده شده. خرید فرضاً با قیمت
          پایانی روز بعدِ کندل انجام شده، روزهای صف و نمادهای کم‌معامله کنار گذاشته شده‌اند و هر
          حالت با «خریدن هر سهم دیگری در همان روزها» مقایسه شده تا گاوی یا خرسی بودن بازار نتیجه را
          نسازد. حکم «بهتر» یا «بدتر» فقط وقتی داده شده که در هر دو نیمهٔ تاریخچه (پیش و پس از{" "}
          {jalali(d.split_date)}) دست‌کم {faPercent(d.dir_edge ?? 0.03, 0)} فاصله داشته باشد.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3" data-testid="entry-facts">
        <div className="rounded-lg border border-line p-3 text-sm">
          <p className="text-xs text-muted">مبنا: هر روز، هر سهم</p>
          {anyH && (
            <p>
              <b>{faPercent(anyH.up, 0)}</b> از دفعه‌ها {faNumber(h)} کندل بعد بالاتر از قیمت خرید
              بوده.
            </p>
          )}
        </div>
        <div className="rounded-lg border border-line p-3 text-sm">
          <p className="text-xs text-muted">حالت‌هایی که در هر دو نیمه پایدار ماندند</p>
          <p>
            {firm.length === 0
              ? "هیچ‌کدام"
              : firm
                  .map((s) => `${s.title} (${s.label === "better" ? "بهتر" : "بدتر"})`)
                  .join("، ")}
          </p>
        </div>
        <div className="rounded-lg border border-line p-3 text-sm">
          <p className="text-xs text-muted">خلاصهٔ صادقانه</p>
          <p>
            هیچ حالتی کندل سبز بعدی را تضمین نکرده؛ بهترین‌ها هم فقط در حدود نیمی از دفعه‌ها کندل
            بعد را بالاتر بسته‌اند. بیشتر ماشه‌های «خروج از کف» فقط پیش از{" "}
            {jalali(d.split_date, "short")} کار کرده‌اند.
          </p>
        </div>
      </div>

      <div className="chart-bar" role="toolbar" aria-label="تنظیم آزمایشگاه ورود">
        <div className="seg" role="group" aria-label="گروه">
          {GROUPS.map(([g, t]) => (
            <button key={g} type="button" aria-pressed={group === g} onClick={() => setGroup(g)}>
              {t}
            </button>
          ))}
        </div>
        <div className="seg" role="group" aria-label="چند کندل بعد">
          {horizons.map((x) => (
            <button key={x} type="button" aria-pressed={h === x} onClick={() => setH(x)}>
              {x === 1 ? "کندل بعد" : `${faNumber(x)} کندل`}
            </button>
          ))}
        </div>
        <div className="seg" role="group" aria-label="ترتیب">
          {(
            [
              ["edge", "برتری"],
              ["up", "درصد بالا"],
              ["n", "تعداد"],
            ] as [Sort, string][]
          ).map(([k, t]) => (
            <button key={k} type="button" aria-pressed={sort === k} onClick={() => setSort(k)}>
              {t}
            </button>
          ))}
        </div>
        <div className="seg" role="group">
          <button type="button" aria-pressed={onlyFirm} onClick={() => setOnlyFirm((v) => !v)}>
            فقط حکم‌دار
          </button>
        </div>
      </div>

      {group === "streak" && <Ladder setups={byKey} h={h} />}
      {group === "base" && d.base_dd != null && d.base_range != null && (
        <p className="text-xs text-muted">
          «کف چندماهه» یعنی دست‌کم {faPercent(Math.abs(d.base_dd), 0)} زیر سقف ۵۲ هفته و{" "}
          {faNumber(d.base_days ?? 60)} پایانی اخیر در دامنهٔ {faPercent(d.base_range, 0)}. هر ماشه
          فقط روز اولش شمرده شده؛ یعنی دقیقاً همان کندلی که می‌شد واردش شد.
        </p>
      )}

      {list.length === 0 ? (
        <p className="text-sm text-muted">در این گروه حالتِ حکم‌داری نیست.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2" data-testid="entry-setups">
          {list.map((s) => {
            const x = at(s, h);
            return (
              <li key={s.key} className="card space-y-2" data-key={s.key}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <b className="text-sm">{s.title}</b>
                  <LabelChip label={s.label} />
                </div>
                <p className="text-xs">{faDigits(s.verdict)}</p>
                {x && <OddsBars x={x} />}
                <YearStrip s={s} h={h} />
                <p className="text-xs text-muted">
                  {faNumber(s.n)} بار در {faNumber(s.symbols)} نماد
                  {s.event ? " · فقط کندل اول حالت شمرده شده" : " · هر روزِ حالت شمرده شده"}
                  {s.locked_share != null &&
                    s.locked_share > 0.05 &&
                    ` · ${faPercent(s.locked_share, 0)} به‌خاطر صف کنار گذاشته شده`}
                </p>
                <details>
                  <summary className="cursor-pointer text-xs text-accent">
                    همهٔ بازه‌ها، دو نیمه و ریسک مسیر
                  </summary>
                  <div className="mt-2 space-y-2">
                    <HorizonTable s={s} />
                    {path && <PathRisk s={s} {...path} />}
                  </div>
                </details>
              </li>
            );
          })}
        </ul>
      )}

      <p className="text-xs text-muted">
        {faNumber(d.setups.length)} حالت × {faNumber(horizons.length)} بازه آزموده شده؛ با این همه
        آزمون، چند تفاوت تصادفی حتماً پیدا می‌شود و برای همین فقط حالت‌هایی که در هر دو نیمه هم‌جهت
        بوده‌اند حکم گرفته‌اند. هزینهٔ رفت‌وبرگشت معامله ({faPercent(d.round_trip_cost ?? 0, 1)}) در
        «بالاتر از قیمت خرید» کم نشده است. این آمار گذشته است، نه توصیه به خرید یا فروش.
      </p>
    </section>
  );
}
