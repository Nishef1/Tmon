export function ErrorState({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-down/30 bg-surface p-5 text-sm"
      data-testid="error-state"
    >
      <p className="font-semibold text-down">دریافت اطلاعات ممکن نشد</p>
      <p className="mt-1 text-muted">{message}</p>
    </div>
  );
}
