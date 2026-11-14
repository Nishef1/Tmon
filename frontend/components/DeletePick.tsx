"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function DeletePick({ id }: { id: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      disabled={busy}
      className="text-sm text-muted hover:text-down"
      onClick={async () => {
        setBusy(true);
        await fetch(`/api/picks/${id}`, { method: "DELETE" }).catch(() => null);
        router.refresh();
        setBusy(false);
      }}
    >
      حذف
    </button>
  );
}
