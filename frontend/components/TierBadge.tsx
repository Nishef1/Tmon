import Link from "next/link";

const STYLE: Record<string, string> = {
  A: "border-accent bg-accent text-surface",
  B: "border-accent text-accent",
  C: "border-line text-muted",
};

export function TierBadge({ tier }: { tier: string }) {
  return (
    <Link
      href="/glossary/tier"
      title="رده اطمینان — توضیح در واژه‌نامه"
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${
        STYLE[tier] ?? STYLE.C
      }`}
    >
      رده {tier}
    </Link>
  );
}
