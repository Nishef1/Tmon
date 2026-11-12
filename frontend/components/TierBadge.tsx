import Link from "next/link";

const STYLE: Record<string, string> = { A: "badge-tier-a", B: "badge-tier-b" };

export function TierBadge({ tier }: { tier: string }) {
  return (
    <Link
      href="/glossary/tier"
      title="رده اطمینان — توضیح در واژه‌نامه"
      className={`badge ${STYLE[tier] ?? "badge-tier"}`}
    >
      رده {tier}
    </Link>
  );
}
