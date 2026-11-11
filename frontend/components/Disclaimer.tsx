export const DISCLAIMER = "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست";

export function Disclaimer({ className = "" }: { className?: string }) {
  return (
    <p
      role="note"
      data-testid="disclaimer"
      className={`rounded-lg border border-warn/30 bg-warn-soft px-4 py-2 text-sm text-warn ${className}`}
    >
      {DISCLAIMER}
    </p>
  );
}
