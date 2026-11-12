import Link from "next/link";
import type { Signal } from "@/lib/api";
import { featureInfo } from "@/lib/glossary";
import { Num } from "./Num";
import { TierBadge } from "./TierBadge";

// The engine stores machine keys (engine/service.py `_risks`); unknown text is shown as it is.
export const RISK_LABEL: Record<string, string> = {
  defensive_mode: "بازار در حالت دفاعی است؛ آستانهٔ ورود سخت‌گیرانه‌تر شده است.",
  unverified_rules: "کارمزدها و قوانین بازار هنوز با منبع رسمی تأیید نشده‌اند.",
  tier_a_disabled: "سطح A فعال نیست، چون مدل هنوز خارج از نمونه از مبنا بهتر نشان داده نشده است.",
  thin_probability_bucket: "نمونهٔ تاریخیِ این بازهٔ احتمال کم است؛ برآورد کم‌اطمینان‌تر است.",
  gap_risk_next_open: "ورود در بازگشایی روز بعد است و ممکن است با شکاف قیمتی از قیمت مرجع دور شود.",
};

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-base font-semibold">{children}</dd>
    </div>
  );
}

export function SignalCard({ s }: { s: Signal }) {
  const stopPct = (s.stop_loss - s.entry_price) / s.entry_price;
  const tpPct = (s.take_profit - s.entry_price) / s.entry_price;
  return (
    <article data-testid="signal-card" className="card sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-lg font-bold">
            <Link href={`/instruments/${s.instrument.id}`} className="hover:text-accent">
              {s.instrument.symbol}
            </Link>
          </h3>
          {s.instrument.name && <p className="text-sm text-muted">{s.instrument.name}</p>}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted">
            رتبه <Num term="rank" value={s.rank} kind="count" />
          </span>
          <TierBadge tier={s.confidence_tier} />
        </div>
      </header>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        <Metric label="احتمال موفقیت">
          <Num term="p_win" value={s.p_win} kind="percent" digits={0} />
        </Metric>
        <Metric label="سود مورد انتظار (پس از هزینه)">
          <Num term="ev" value={s.ev} kind="percent" digits={1} signed />
        </Metric>
        <Metric label="سهم پیشنهادی از سرمایه">
          <Num term="position_pct" value={s.position_pct} kind="percent" digits={1} />
        </Metric>
        <Metric label="افق (روز معاملاتی)">
          <Num term="horizon" value={s.horizon_days} kind="count" />
        </Metric>
        <Metric label="قیمت مرجع (ریال)">
          <Num term="entry_price" value={s.entry_price} kind="price" />
        </Metric>
        <Metric label="حد سود (ریال)">
          <Num term="take_profit" value={s.take_profit} kind="price" />{" "}
          <span className="text-xs font-normal text-muted">
            (<Num term="take_profit" value={tpPct} kind="percent" signed />)
          </span>
        </Metric>
        <Metric label="حد ضرر (ریال)">
          <Num term="stop_loss" value={s.stop_loss} kind="price" />{" "}
          <span className="text-xs font-normal text-muted">
            (<Num term="stop_loss" value={stopPct} kind="percent" signed />)
          </span>
        </Metric>
      </dl>

      <p className="mt-3 text-xs text-muted">
        ورود فرضی: بازگشایی روز معاملاتی بعد. قیمت مرجع، پایانی روز سیگنال است.
      </p>

      {s.top_reasons.length > 0 && (
        <details className="mt-4 border-t border-line pt-3">
          <summary className="cursor-pointer text-sm font-semibold">
            چرا این نماد؟ (مهم‌ترین عوامل مدل)
          </summary>
          <ul className="mt-2 space-y-1.5 text-sm">
            {s.top_reasons.map((r) => {
              const info = featureInfo(r.feature);
              return (
                <li key={r.feature} className="flex flex-wrap items-baseline justify-between gap-2">
                  <span>
                    <Link href={`/glossary/${info.term}`} className="hover:text-accent">
                      {info.label}
                    </Link>
                    <span className="text-muted">
                      {" "}
                      = <Num term="feature_value" value={r.value} digits={2} />
                    </span>
                  </span>
                  <span className="text-muted">
                    {r.contribution >= 0 ? "افزایش" : "کاهش"} امتیاز{" "}
                    <Num term="shap" value={r.contribution} digits={2} signed />
                  </span>
                </li>
              );
            })}
          </ul>
        </details>
      )}

      {s.risks.length > 0 && (
        <div className="mt-3 border-t border-line pt-3">
          <p className="text-sm font-semibold">ملاحظات ریسک</p>
          <ul className="mt-1 list-inside list-disc text-sm text-muted">
            {s.risks.map((r) => (
              <li key={r}>{RISK_LABEL[r] ?? r}</li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}
