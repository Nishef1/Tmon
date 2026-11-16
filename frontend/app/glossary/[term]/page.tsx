import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { TermTests } from "@/components/TermTests";
import { taSignals } from "@/lib/api";
import { GLOSSARY, GLOSSARY_KEYS, glossaryEntry, CATEGORY_LABEL } from "@/lib/glossary";
import { placesFor } from "@/lib/glossary-places";
import { PLAIN } from "@/lib/glossary-plain";
import { SHOWN_ON } from "@/lib/glossary-usage";

type Props = { params: Promise<{ term: string }> };

export const dynamicParams = false;

export function generateStaticParams() {
  return GLOSSARY_KEYS.map((term) => ({ term }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { term } = await params;
  const e = glossaryEntry(term);
  return { title: e ? e.fa : "واژه‌نامه" };
}

export default async function GlossaryTerm({ params }: Props) {
  const { term } = await params;
  const e = glossaryEntry(term);
  if (!e) notFound();
  const shown = SHOWN_ON[term];
  const places = placesFor(term);
  const tests = shown ? await taSignals() : null;
  const simple = PLAIN[e.key];
  return (
    <main className="gloss mx-auto max-w-3xl space-y-6">
      <Link href="/glossary" className="text-sm text-accent hover:underline">
        → همهٔ واژه‌ها
      </Link>
      <header className="space-y-2">
        <span className="chip">{CATEGORY_LABEL[e.category]}</span>
        <h1 className="text-3xl font-extrabold leading-tight">{e.fa}</h1>
        <p className="text-sm text-muted">
          <bdi dir="ltr">{e.en}</bdi>
        </p>
        {e.aliases && e.aliases.length > 0 && (
          <p className="text-xs text-muted">نام‌های دیگر: {e.aliases.join("، ")}</p>
        )}
      </header>

      <section className="gloss-simple" data-testid="term-plain">
        <h2 className="gloss-h">به زبان ساده</h2>
        <p className="gloss-lead">{simple.plain}</p>
        <div className="gloss-example">
          <h3 className="gloss-h">مثال</h3>
          <p>{simple.example}</p>
        </div>
      </section>

      <section className="card space-y-4" data-testid="term-technical">
        <h2 className="gloss-h">تعریف دقیق</h2>
        <p className="gloss-body">{e.definition}</p>
        {e.formula && (
          <div>
            <h3 className="gloss-h">فرمول</h3>
            <p className="gloss-formula">{e.formula}</p>
          </div>
        )}
      </section>

      <div className="grid gap-4 sm:grid-cols-2">
        <section className="card">
          <h2 className="gloss-h">چرا مهم است؟</h2>
          <p className="gloss-body">{e.why}</p>
        </section>
        <section className="card">
          <h2 className="gloss-h">محدودیت‌ها</h2>
          <p className="gloss-body">{e.limits}</p>
        </section>
      </div>

      {shown && (
        <section data-testid="term-shown-on">
          <h2 className="mb-1 font-bold">کجای سایت دیده می‌شود؟</h2>
          <ul className="list-disc space-y-1 ps-5 text-sm">
            {shown.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </section>
      )}
      {places.length > 0 && (
        <section data-testid="term-places">
          <h2 className="mb-1 font-bold">این عدد در کدام صفحه‌ها آمده است؟</h2>
          <ul className="flex flex-wrap gap-2 text-sm">
            {places.map((pl) => (
              <li key={pl.href}>
                <Link href={pl.href} className="tab tab-pill">
                  {pl.label}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <TermTests term={term} doc={tests} />
      {e.related && e.related.length > 0 && (
        <section>
          <h2 className="mb-1 font-bold">مدخل‌های مرتبط</h2>
          <ul className="flex flex-wrap gap-2 text-sm">
            {e.related
              .filter((k) => k in GLOSSARY)
              .map((k) => (
                <li key={k}>
                  <Link href={`/glossary/${k}`} className="tab tab-pill">
                    {GLOSSARY[k as keyof typeof GLOSSARY].fa}
                  </Link>
                </li>
              ))}
          </ul>
        </section>
      )}
    </main>
  );
}

