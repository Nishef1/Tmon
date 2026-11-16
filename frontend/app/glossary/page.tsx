import type { Metadata } from "next";
import { GlossarySearch, type GlossaryItem } from "@/components/GlossarySearch";
import { CATEGORY_LABEL, GLOSSARY, GLOSSARY_KEYS } from "@/lib/glossary";

export const metadata: Metadata = { title: "واژه‌نامه" };

function aliasesOf(e: object): readonly string[] {
  return "aliases" in e ? (e.aliases as readonly string[]) : [];
}

export default function GlossaryIndex() {
  const items: GlossaryItem[] = GLOSSARY_KEYS.map((k) => ({
    key: k,
    fa: GLOSSARY[k].fa,
    en: GLOSSARY[k].en,
    category: GLOSSARY[k].category,
    categoryLabel: CATEGORY_LABEL[GLOSSARY[k].category],
    text: [GLOSSARY[k].definition, ...aliasesOf(GLOSSARY[k])].join(" "),
  }));
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold">واژه‌نامه</h1>
        <p className="mt-1 text-sm text-muted">
          هر عدد در سایت به مدخل خودش در این صفحه پیوند دارد: تعریف، فرمول، دلیل اهمیت، محدودیت‌ها و
          صفحه‌هایی که آن را نشان می‌دهند.
        </p>
      </div>
      <GlossarySearch items={items} />
    </main>
  );
}
