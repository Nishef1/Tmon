import type { Autopilot, AutopilotEvent } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { methodLabel } from "@/components/model/methods";

function eventText(e: AutopilotEvent): string {
  switch (e.kind) {
    case "champion":
      return `قهرمان افق ${faNumber(e.horizon ?? 0)} روز از «${methodLabel(e.before ?? "")}» به «${methodLabel(e.after ?? "")}» تغییر کرد`;
    case "regime":
      return e.after === "stress"
        ? "هشدار رژیم: شاخص کل وارد حالت افت شد؛ بازپخش دوباره انجام می‌شود"
        : "شاخص کل از حالت افت بیرون آمد؛ بازپخش دوباره انجام می‌شود";
    default:
      return e.kind;
  }
}

/** What the system saw when it last checked itself: the regime of the index and what changed.
 *  Redone every cycle, so nobody has to remember to look. */
export function AutopilotStatus({ a }: { a: Autopilot }) {
  const r = a.regime;
  return (
    <div className="card space-y-3" data-testid="autopilot">
      <h3 className="text-lg font-bold">خودکار: سامانه خودش را زیر نظر دارد</h3>
      <p className="text-sm leading-7">
        هر چرخهٔ روزانه قهرمان‌ها و وضعیت بازار را با بررسی قبلی مقایسه می‌کند؛ هر تغییر در فهرست
        زیر می‌آید. آخرین بررسی: {jalali(a.checked_at?.slice(0, 10))} (داده تا {jalali(a.as_of)}).
      </p>
      {r && (
        <p className="text-sm leading-7" data-testid="autopilot-regime">
          <b>بازار (شاخص کل):</b> افت از قلهٔ تاریخی {faPercent(r.drawdown, 1)}، بازدهٔ{" "}
          {faNumber(r.recent_days)} روز اخیر {faPercent(r.return_recent, 0, true)}.{" "}
          {r.stress ? "اکنون در حالت افت است." : "اکنون در حالت افت نیست."}{" "}
          {r.bullish_only
            ? "در چهار سال اخیر هیچ پنجرهٔ ۲۵۰روزه‌ای با افت اسمی ۱۰٪ یا بیشتر پایان نیافته؛ پس نتیجه‌ها هنوز فقط در یک رژیم صعودی (اسمی، پرتورم) آزموده شده‌اند."
            : `${faNumber(r.bear_windows)} پنجرهٔ ۲۵۰روزه با افت اسمی ۱۰٪ یا بیشتر پایان یافته؛ داده فقط یک رژیم صعودی نیست.`}
        </p>
      )}
      <div>
        <h4 className="text-sm font-bold">تغییرات ثبت‌شده</h4>
        {a.events.length === 0 ? (
          <p className="text-sm text-muted" data-testid="autopilot-no-events">
            از شروع نظارت هیچ تغییری رخ نداده است: قهرمان‌ها و رژیم همان‌اند.
          </p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm leading-7" data-testid="autopilot-events">
            {a.events.slice(0, 8).map((e, i) => (
              <li key={`${e.at}-${e.kind}-${i}`}>
                <span className="text-muted">{jalali(e.at)}:</span> {eventText(e)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
