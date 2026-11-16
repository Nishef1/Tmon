import type { Autopilot, AutopilotEvent } from "@/lib/api";
import { faNumber, faPercent, jalali } from "@/lib/format";
import { methodLabel } from "@/components/model/methods";

const REASONS: Record<string, string> = {
  no_study: "هنوز مطالعه‌ای ثبت نشده است",
  old: "از مهلت بازآموزی گذشته است",
  regime: "بعد از تغییر رژیم بازار ساخته شده و باید دوباره انجام شود",
};

/** "gbm@5" -> "درخت تقویتی (GBM) در افق ۵ روز". */
function passedLabel(key: string): string {
  const [m, h] = key.split("@");
  return `${methodLabel(m)} در افق ${faNumber(Number(h))} روز`;
}

function eventText(e: AutopilotEvent): string {
  switch (e.kind) {
    case "champion":
      return `قهرمان افق ${faNumber(e.horizon ?? 0)} روز از «${methodLabel(e.before ?? "")}» به «${methodLabel(e.after ?? "")}» تغییر کرد`;
    case "regime":
      return e.after === "stress"
        ? "هشدار رژیم: شاخص کل وارد حالت افت شد؛ بازپخش و مطالعهٔ عمیق دوباره انجام می‌شوند"
        : "شاخص کل از حالت افت بیرون آمد؛ بازپخش و مطالعهٔ عمیق دوباره انجام می‌شوند";
    case "deep_refreshed":
      return e.passed.length
        ? `مطالعهٔ عمیق دوباره انجام شد؛ از آزمون پذیرش گذشت: ${e.passed.map(passedLabel).join("؛ ")}`
        : "مطالعهٔ عمیق دوباره انجام شد؛ هیچ روشی از آزمون پذیرش نگذشت";
    case "deep_passed":
      return `از آزمون پذیرش گذشت: ${e.methods.map(passedLabel).join("؛ ")}`;
    case "deep_lost":
      return `دیگر از آزمون پذیرش نمی‌گذرد: ${e.methods.map(passedLabel).join("؛ ")}`;
    case "deep_skipped":
      return "مطالعهٔ عمیق باید دوباره انجام شود، ولی این سرور کتابخانهٔ torch را ندارد؛ آن را باید روی رایانه‌ای با کارت گرافیک اجرا کرد";
    default:
      return e.kind;
  }
}

/** What the system saw when it last checked itself: the regime of the index, how current the deep
 *  study is and what changed. Redone every cycle, so nobody has to remember to look. */
export function AutopilotStatus({ a }: { a: Autopilot }) {
  const r = a.regime;
  const deep = a.deep;
  return (
    <div className="card space-y-3" data-testid="autopilot">
      <h3 className="text-lg font-bold">خودکار: سامانه خودش را زیر نظر دارد</h3>
      <p className="text-sm leading-7">
        هر چرخهٔ روزانه قهرمان‌ها و وضعیت بازار را با بررسی قبلی مقایسه می‌کند؛ هر تغییر در فهرست
        زیر می‌آید. مطالعهٔ عمیق (آزمون شبکه‌های عصبی) خودش بعد از {faNumber(deep?.refresh_days ?? 0)} روز، یا وقتی رژیم
        بازار عوض شود، دوباره انجام می‌شود. آخرین بررسی: {jalali(a.checked_at?.slice(0, 10))} (داده
        تا {jalali(a.as_of)}).
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
      {deep && (
        <p className="text-sm leading-7" data-testid="autopilot-deep">
          <b>مطالعهٔ عمیق:</b>{" "}
          {deep.present ? (
            <>
              آخرین اجرا: {jalali(deep.last)}، یعنی {faNumber(deep.age_days ?? 0)} روز قدیمی‌تر از داده.{" "}
              {deep.passed.length
                ? `از آزمون پذیرش گذشته: ${deep.passed.map(passedLabel).join("؛ ")}.`
                : "هیچ روشی از آزمون پذیرش نگذشته."}
            </>
          ) : (
            "هنوز اجرا نشده."
          )}{" "}
          {deep.due ? (
            <b className="text-down">
              منتظر بازآموزی است: {REASONS[deep.reason ?? ""] ?? deep.reason}.
              {!deep.can_run && " این سرور کتابخانهٔ torch را ندارد؛ باید روی رایانه‌ای با کارت گرافیک اجرا شود."}
            </b>
          ) : (
            <span className="text-muted">به‌روز است.</span>
          )}
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
