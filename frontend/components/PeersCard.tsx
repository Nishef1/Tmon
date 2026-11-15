import Link from "next/link";
import type { InstrumentDashboard } from "@/lib/api";
import { faNumber, faPercent } from "@/lib/format";
import { signedPct, signTone, verdictPill } from "@/lib/ui";

type P = NonNullable<InstrumentDashboard["peers"]>;
type Row = P["items"][number];

const VERDICT_FA: Record<Row["verdict"], string> = {
  buy: "خرید",
  hold: "صبر",
  sell: "فروش",
  none: "بدون امتیاز",
};

const TONE_CLS: Record<string, string> = { up: "text-up", down: "text-down", none: "" };

const dd = (x: number | null | undefined) =>
  x == null ? "—" : x > -0.01 ? "نزدیک سقف" : faPercent(x, 0);

/** One line of the verdict: where the symbol stands in its group. */
function Summary({ p }: { p: P }) {
  const me = p.items.find((x) => x.is_self);
  const best = p.items[0];
  if (!me || p.position == null) {
    return (
      <p className="mb-3">
        این نماد امتیاز ترکیبی ندارد، چون کم‌معامله است یا داده‌اش کافی نیست. بهترین‌های گروه را در
        جدول زیر ببینید.
      </p>
    );
  }
  if (p.position === 1) {
    return (
      <p className="mb-3">
        این نماد از میان {faNumber(p.scored)} سهم امتیازدار گروه، <b>بهترین امتیاز را دارد</b>.
      </p>
    );
  }
  return (
    <p className="mb-3">
      رتبهٔ <b>{faNumber(p.position)}</b> از {faNumber(p.scored)} سهم امتیازدار گروه. بالاترین
      امتیاز گروه مال <b>{best.symbol}</b> است ({faNumber(best.score ?? 0)}) و امتیاز این نماد{" "}
      {faNumber(me.score ?? 0)} است.
    </p>
  );
}

/** The symbol next to the best-scored stocks of its industry group, so the reader can pick. */
export function PeersCard({ p }: { p: P }) {
  return (
    <section className="card" data-testid="peers" data-position={p.position ?? ""}>
      <h2 className="mb-1 font-bold">
        بهترین نماد گروه{p.sector_name ? `: ${p.sector_name}` : ""}
      </h2>
      <Summary p={p} />
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="peers-table">
          <thead className="text-muted">
            <tr>
              <th className="py-1 text-start font-normal">نماد</th>
              <th className="py-1 font-normal">امتیاز</th>
              <th className="py-1 font-normal">حالت</th>
              <th
                className="py-1 font-normal"
                title="قیمت تقسیم بر سود هر سهم: اگر سود شرکت ثابت بماند، چند سال طول می‌کشد تا سود به اندازهٔ قیمت خرید شود؛ عدد کمتر یعنی ارزان‌تر"
              >
                P/E
              </th>
              <th className="py-1 font-normal">بازده ۶۰ روز</th>
              <th className="py-1 font-normal">تا سقف یک‌ساله</th>
            </tr>
          </thead>
          <tbody>
            {p.items.map((x) => (
              <tr
                key={x.id}
                className={`border-t border-line text-center ${x.is_self ? "bg-accent-soft font-semibold" : ""}`}
                data-self={x.is_self || undefined}
              >
                <td className="py-1.5 text-start">
                  {x.is_self ? (
                    <span>{x.symbol}</span>
                  ) : (
                    <Link
                      href={`/instruments/${x.id}`}
                      className="underline-offset-2 hover:underline"
                    >
                      {x.symbol}
                    </Link>
                  )}
                  {x.in_basket && (
                    <span
                      className="ms-1 text-xs text-muted"
                      title="در فهرست سهم‌های پرمعامله‌ای که مدل روی آن‌ها آزموده شده"
                    >
                      ●
                    </span>
                  )}
                </td>
                <td className="py-1.5">
                  <span className={verdictPill(x.verdict)}>
                    {x.score == null ? VERDICT_FA.none : faNumber(x.score)}
                  </span>
                </td>
                <td className={`py-1.5 ${TONE_CLS[x.turning_tone ?? "none"] ?? ""}`}>
                  {x.turning_title ?? "—"}
                </td>
                <td className="py-1.5">{x.pe == null ? "—" : faNumber(x.pe, 1)}</td>
                <td className={`py-1.5 ${signTone(x.ret60)}`}>{signedPct(x.ret60, 0)}</td>
                <td className="py-1.5">{dd(x.dd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">
        «امتیاز» همان امتیاز ترکیبی رتبه‌بندی (۰ تا ۱۰۰) است و رنگش خرید، صبر یا فروش را نشان
        می‌دهد. نقطهٔ ● یعنی نماد در فهرست سهم‌های پرمعامله‌ای است که مدل روی آن‌ها آزموده شده. P/E
        قیمت تقسیم بر سود هر سهم است و عدد کمتر یعنی ارزان‌تر. رنگ «حالت» سابقهٔ همان حالت را نشان
        می‌دهد: سبز یعنی در گذشته بهتر از بازار بوده، قرمز یعنی بدتر از بازار، و بی‌رنگ یعنی در هر
        دو نیمهٔ تاریخچه برتری یا ضعف پایداری بیش از کارمزد نداشته است. «تا سقف یک‌ساله» فقط فاصله
        را نشان می‌دهد و رنگ ندارد؛ دو سهمی که هر دو نزدیک سقف‌اند ممکن است حالت‌های متفاوتی داشته
        باشند (مثلاً «روند صعودی، نزدیک سقف» در برابر «رشد بسیار تند»). {faNumber(p.total)} سهم فعال
        در گروه هست. این مقایسه است، نه توصیهٔ خرید یا فروش.
      </p>
    </section>
  );
}
