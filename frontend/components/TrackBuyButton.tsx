"use client";

import Link from "next/link";
import { useState } from "react";

/** "I bought this": freezes today's forecast so it can be checked against the candles after. */
export function TrackBuyButton({ id, symbol }: { id: number; symbol: string }) {
  const [open, setOpen] = useState(false);
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    const paid = Number(price.replace(/[^\d.]/g, ""));
    try {
      const res = await fetch("/api/picks", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ instrument_id: id, paid_price: paid > 0 ? paid : null }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setDone(true);
    } catch {
      setError("ثبت نشد؛ دوباره تلاش کنید.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <p className="text-sm" data-testid="track-done">
        ثبت شد. پیش‌بینی امروزِ {symbol} نگه داشته می‌شود و با کندل‌های بعدی سنجیده می‌شود.{" "}
        <Link href="/picks" className="font-semibold text-accent">
          دیدن خریدهای من
        </Link>
      </p>
    );
  }
  return (
    <div data-testid="track-buy">
      {!open ? (
        <button type="button" className="tab tab-pill" onClick={() => setOpen(true)}>
          این سهم را خریدم / می‌خرم
        </button>
      ) : (
        <div className="tile space-y-2">
          <p className="text-sm text-muted">
            پیش‌بینی امروز این سهم همین‌طور که هست ذخیره می‌شود. بعد از ۱، ۳، ۵، ۱۰ و ۲۰ کندل، با
            قیمت واقعی مقایسه می‌شود.
          </p>
          <label className="block text-sm">
            قیمتی که خریدید (اختیاری)
            <input
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              inputMode="decimal"
              className="ms-2 w-36 bg-surface-2 px-2 py-1"
              data-testid="track-price"
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="tab tab-pill"
              aria-current="page"
              disabled={busy}
              onClick={save}
              data-testid="track-save"
            >
              {busy ? "در حال ثبت…" : "ثبت"}
            </button>
            <button type="button" className="tab tab-pill" onClick={() => setOpen(false)}>
              انصراف
            </button>
            {error && <span className="text-sm text-down">{error}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
