export function ErrorState({ message }: { message: string }) {
  return (
    <div role="alert" className="card card-down text-sm" data-testid="error-state">
      <p className="font-semibold text-down">دریافت اطلاعات ممکن نشد</p>
      <p className="mt-1 text-muted">{message}</p>
    </div>
  );
}
