import Link from "next/link";
import type { InstrumentDetail } from "@/lib/api";
import { jalali } from "@/lib/format";

const STAGE_LABEL: Record<string, string> = {
  invitation: "دعوت به مجمع",
  decisions: "تصمیمات مجمع",
  decisions_summary: "خلاصهٔ تصمیمات مجمع",
  decisions_registered: "ثبت تصمیمات مجمع",
  dividend_schedule: "زمان‌بندی پرداخت سود",
  dividend_schedule_prior_years: "زمان‌بندی سود سال‌های قبل",
  ordinary_extraordinary_invitation: "دعوت مجمع عادی به‌طور فوق‌العاده",
  ordinary_extraordinary_decisions: "تصمیمات مجمع عادی به‌طور فوق‌العاده",
  ordinary_extraordinary_decisions_summary: "خلاصهٔ تصمیمات مجمع فوق‌العاده",
  egm_invitation: "دعوت مجمع فوق‌العاده",
  egm_decisions: "تصمیمات مجمع فوق‌العاده",
  meeting_cancelled: "لغو جلسه",
  board_proposal: "پیشنهاد هیئت‌مدیره به مجمع",
  auditor_opinion: "نظر حسابرس",
  documents: "مدارک و پیوست‌ها",
  registered: "ثبت شد",
  board_decision_delegated: "تصمیم هیئت‌مدیره (تفویض)",
  board_meeting_scheduled: "زمان جلسهٔ هیئت‌مدیره",
  board_decision: "تصمیم هیئت‌مدیره",
  rights_deadline_extended: "تمدید مهلت حق‌تقدم",
  public_subscription_extended: "تمدید پذیره‌نویسی",
};

const TYPE_LABEL: Record<string, string> = {
  agm_dividend: "مجمع عادی",
  egm_capital_increase: "افزایش سرمایه",
  rights_offering: "حق‌تقدم",
  other: "سایر",
};

type Item = {
  when: string | null;
  kind: "news" | "event" | "letter";
  tag: string;
  title: string;
  url: string | null;
};

const KIND: Record<Item["kind"], string> = {
  news: "خبر",
  event: "رویداد",
  letter: "کدال",
};

const SHOWN = 15;

/** News, Codal events and Codal letters of the symbol in one timeline, newest first. A letter
 *  that is also a read event is listed once, as the event. */
export function StockNews({ d }: { d: InstrumentDetail }) {
  const seen = new Set<string>();
  const items: Item[] = [];
  for (const e of d.events) {
    if (e.url) seen.add(e.url);
    items.push({
      when: e.announced_at ?? null,
      kind: "event",
      tag: `${TYPE_LABEL[e.type] ?? e.type}${e.stage ? ` · ${STAGE_LABEL[e.stage] ?? e.stage}` : ""}`,
      title: e.title ?? "نامهٔ کدال",
      url: e.url ?? null,
    });
  }
  for (const l of d.letters) {
    if (l.url && seen.has(l.url)) continue;
    items.push({
      when: l.published_at ?? null,
      kind: "letter",
      tag: l.letter_code ?? "",
      title: l.title,
      url: l.url ?? null,
    });
  }
  for (const n of d.news) {
    items.push({
      when: n.published_at ?? null,
      kind: "news",
      tag: n.source,
      title: n.title,
      url: n.url ?? null,
    });
  }
  items.sort((a, b) => (b.when ?? "").localeCompare(a.when ?? ""));
  const shown = items.slice(0, SHOWN);
  return (
    <section className="card scroll-mt-28" data-testid="codal-letters" id="news">
      <h2 className="mb-1 font-bold">
        خبرها و{" "}
        <Link href="/glossary/codal_event" className="hover:text-accent">
          کدال
        </Link>
      </h2>
      <p className="mb-2 text-xs text-muted">
        در این بخش تازه‌ترین اطلاعیه‌های ناشر در کدال و خبرهایی را می‌بینید که نام نماد در تیترشان
        آمده است؛ به ترتیب تاریخ. با کلیک روی هر مورد، متن اصلی باز می‌شود.
      </p>
      {shown.length === 0 ? (
        <p className="text-sm text-muted" data-testid="news-empty">
          برای این نماد اطلاعیهٔ کدال یا خبر تازه‌ای ثبت نشده است. نبود خبر یعنی چیزی دریافت نشده،
          نه اینکه حتماً خبری نبوده؛ پیش از خرید، کدال را هم ببینید.
        </p>
      ) : (
        <ul className="divide-y divide-line text-sm">
          {shown.map((x, i) => (
            <li
              key={`${x.url ?? ""}-${i}`}
              className="flex flex-wrap gap-x-3 gap-y-1 py-2"
              data-kind={x.kind}
            >
              <span className="text-muted">{x.when ? jalali(x.when, "short") : "—"}</span>
              <span className="chip">{KIND[x.kind]}</span>
              {x.tag && <span className="font-semibold">{x.tag}</span>}
              {x.url ? (
                <a
                  href={x.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-w-0 break-words text-accent underline"
                >
                  {x.title}
                </a>
              ) : (
                <span className="min-w-0 break-words">{x.title}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {items.length > SHOWN && (
        <p className="mt-2 text-xs text-muted">
          {items.length - SHOWN} مورد قدیمی‌تر نمایش داده نشد.
        </p>
      )}
    </section>
  );
}
