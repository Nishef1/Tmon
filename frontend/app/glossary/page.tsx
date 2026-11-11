import Link from "next/link";
import type { Metadata } from "next";
import { CATEGORY_LABEL, GLOSSARY, GLOSSARY_KEYS, type Category } from "@/lib/glossary";

export const metadata: Metadata = { title: "واژه‌نامه" };

export default function GlossaryIndex() {
  const groups = (Object.keys(CATEGORY_LABEL) as Category[]).map((c) => ({
    category: c,
    keys: GLOSSARY_KEYS.filter((k) => GLOSSARY[k].category === c),
  }));
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold">واژه‌نامه</h1>
        <p className="mt-1 text-sm text-muted">
          هر عدد در سایت به مدخل خودش در این صفحه پیوند دارد: تعریف، فرمول، دلیل اهمیت و محدودیت‌ها.
        </p>
      </div>
      {groups.map((g) => (
        <section key={g.category} aria-labelledby={`g-${g.category}`}>
          <h2 id={`g-${g.category}`} className="mb-2 font-bold">
            {CATEGORY_LABEL[g.category]}
          </h2>
          <ul className="grid gap-2 sm:grid-cols-2">
            {g.keys.map((k) => (
              <li key={k}>
                <Link
                  href={`/glossary/${k}`}
                  className="block rounded-xl border border-line bg-surface px-4 py-2.5 hover:bg-accent-soft"
                >
                  <span className="font-semibold">{GLOSSARY[k].fa}</span>
                  <span className="block text-xs text-muted" dir="ltr">
                    {GLOSSARY[k].en}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
