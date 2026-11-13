import type { InstrumentDashboard } from "@/lib/api";
import { faDigits, faNumber, faPercent, jalali } from "@/lib/format";
import { signedPct, signTone } from "@/lib/ui";

type D = NonNullable<InstrumentDashboard["drivers"]>;
type Move = D["moves"][number];

const KIND_FA: Record<Move["kind"], string> = {
  war: "جنگ",
  sanction: "تحریم",
  unrest: "اعتراض",
  deal: "توافق",
  politics: "سیاست",
  market: "بازار",
  other: "دیگر",
};

const SHOWN = 8;

function Moves({ d }: { d: D }) {
  if (d.moves.length === 0) return null;
  const rows = d.moves.slice(0, SHOWN);
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-sm" data-testid="drivers-moves">
        <thead className="text-muted">
          <tr>
            <th className="py-1 text-start font-normal">رویداد</th>
            <th className="py-1 font-normal">این سهم</th>
            <th className="py-1 font-normal">شاخص کل</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.date} className="border-t border-line text-center">
              <td className="py-1.5 text-start">
                <span className="text-muted">
                  {jalali(m.date, "short")} · {KIND_FA[m.kind]}
                </span>{" "}
                <a href={m.source} target="_blank" rel="noopener noreferrer" className="underline">
                  {m.title}
                </a>
              </td>
              <td className={`py-1.5 ${signTone(m.stock)}`}>{signedPct(m.stock, 0)}</td>
              <td className={`py-1.5 ${signTone(m.index)}`}>{signedPct(m.index, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-xs text-muted">
        تغییر قیمت (تعدیل‌شده) از آخرین روز معامله پیش از رویداد تا {faNumber(d.event_days)} روز
        معاملاتی بعد. اگر بورس بسته بوده، اولین روزِ بازگشایی حساب شده است.
      </p>
    </div>
  );
}

/** What moves the stock besides its own chart: the index, the dollar, world prices and shocks. */
export function DriversCard({ d }: { d: D }) {
  return (
    <section className="card" data-testid="drivers">
      <h2 className="mb-1 font-bold">چه چیزی این سهم را بالا و پایین می‌برد؟</h2>
      <ul className="list-disc space-y-1.5 ps-5">
        {d.lines.map((l) => (
          <li key={l}>{faDigits(l)}</li>
        ))}
        {d.dps != null && d.div_date && (
          <li>
            آخرین سود نقدی (از روی افت قیمت روز مجمع): {faNumber(d.dps)} ریال در{" "}
            {jalali(d.div_date)}، حدود {faPercent(d.div_yield ?? 0, 1)} قیمت آن روز.
          </li>
        )}
      </ul>
      <Moves d={d} />
      <p className="mt-3 text-xs text-muted">
        این‌ها توضیح گذشته‌اند، نه پیش‌بینی. در آزمون ما، اضافه‌کردن دلار، مس و ارزانی به دلار به
        مدل امتیاز، انتخاب سهم را بهتر نکرد؛ برای همین در امتیاز و تصمیم بالا وزنی ندارند.
      </p>
    </section>
  );
}
