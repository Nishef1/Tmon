import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { TermTests } from "@/components/TermTests";
import { taSignals } from "@/lib/api";
import { GLOSSARY, GLOSSARY_KEYS, glossaryEntry, CATEGORY_LABEL } from "@/lib/glossary";
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
  const tests = shown ? await taSignals() : null;
  return (
    <main className="max-w-2xl space-y-5">
      <Link href="/glossary" className="text-sm text-accent">
        ← واژه‌نامه
      </Link>
      <header>
        <p className="text-xs text-muted">{CATEGORY_LABEL[e.category]}</p>
        <h1 className="text-2xl font-extrabold">{e.fa}</h1>
        <p className="text-sm text-muted" dir="ltr">
          {e.en}
        </p>
        {e.aliases && e.aliases.length > 0 && (
          <p className="mt-1 text-xs text-muted">نام‌های دیگر: {e.aliases.join("، ")}</p>
        )}
      </header>
      <Section title="تعریف">{e.definition}</Section>
      {e.formula && (
        <section>
          <h2 className="mb-1 font-bold">فرمول</h2>
          <p className="tile text-sm">{e.formula}</p>
        </section>
      )}
      <Section title="چرا مهم است؟">{e.why}</Section>
      <Section title="محدودیت‌ها">{e.limits}</Section>
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-1 font-bold">{title}</h2>
      <p className="text-sm leading-8">{children}</p>
    </section>
  );
}
