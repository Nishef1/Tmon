import type { Metadata } from "next";
import { GlossarySearch, type GlossaryItem } from "@/components/GlossarySearch";
import { CATEGORY_LABEL, GLOSSARY, GLOSSARY_KEYS } from "@/lib/glossary";
import { PLAIN } from "@/lib/glossary-plain";

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
    plain: PLAIN[k].plain,
  }));
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-3xl font-extrabold">واژه‌نامه</h1>
        <p className="mt-2 max-w-[68ch] leading-8 text-muted">
          هر عدد سایت به مدخل خودش پیوند دارد. هر مدخل اول به زبان ساده و با مثال توضیح می‌دهد، بعد
          تعریف دقیق، فرمول، دلیل اهمیت و محدودیت‌ها را می‌آورد.
        </p>
      </div>
      <GlossarySearch items={items} />
    </main>
  );
}
