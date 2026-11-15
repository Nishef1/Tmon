import type { ReactNode } from "react";

/** A collapsed section: one line with the title and a short hint, the detail behind a click. */
export function Fold({
  id,
  title,
  hint,
  open = true,
  children,
}: {
  id: string;
  title: string;
  hint?: string;
  open?: boolean;
  children: ReactNode;
}) {
  return (
    <details className="group card p-0" data-fold={id} id={id} open={open}>
      <summary className="flex cursor-pointer list-none items-baseline gap-2 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="text-muted transition-transform group-open:-rotate-90">
          ‹
        </span>
        <span className="font-bold">{title}</span>
        {hint && <span className="text-sm text-muted">{hint}</span>}
      </summary>
      <div className="space-y-4 border-t border-line p-4">{children}</div>
    </details>
  );
}
