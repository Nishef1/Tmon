export const DISCLAIMER = "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست";

export function Disclaimer({ className = "" }: { className?: string }) {
  return (
    <p
      role="note"
      data-testid="disclaimer"
      className={`alert-warn ${className}`}
    >
      {DISCLAIMER}
    </p>
  );
}
