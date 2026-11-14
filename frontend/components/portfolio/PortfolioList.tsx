"use client";

import Link from "next/link";
import { useState } from "react";
import {
  call,
  forgetPortfolio,
  savePortfolio,
  useSaved,
  type Created,
  type Portfolio,
  type Saved,
} from "@/lib/portfolio";

export function PortfolioList() {
  const list: Saved[] = useSaved() ?? [];
  const [name, setName] = useState("");
  const [cash, setCash] = useState("");
  const [imp, setImp] = useState({ id: "", key: "" });
  const [created, setCreated] = useState<Created | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const c = await call<Created>("", null, {
        method: "POST",
        body: { name: name.trim(), cash: Number(cash.replace(/,/g, "")) * 10 || 0 },
      });
      savePortfolio({ id: c.id, key: c.key, name: c.name });
      setCreated(c);
      setName("");
      setCash("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function importOne(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const id = Number(imp.id);
    try {
      const p = await call<Portfolio>(`/${id}`, imp.key.trim());
      savePortfolio({ id, key: imp.key.trim(), name: p.name });
      setImp({ id: "", key: "" });
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="grid gap-4">
      {created && (
        <div className="alert-warn" role="status" data-testid="new-key">
          <b>پرتفوی «{created.name}» ساخته شد.</b> کلید آن فقط همین یک بار نمایش داده می‌شود و در
          همین مرورگر ذخیره شد. برای باز کردن از دستگاه دیگر آن را نگه دار:
          <div className="mt-2 font-mono text-sm" dir="ltr">
            id={created.id} key={created.key}
          </div>
        </div>
      )}
      {error && (
        <p className="text-down" role="alert">
          {error}
        </p>
      )}

      <section className="card">
        <h2 className="font-bold">پرتفوی‌های من</h2>
        {list.length === 0 ? (
          <p className="mt-2 text-muted">هنوز پرتفویی در این مرورگر نیست. یکی بساز یا وارد کن.</p>
        ) : (
          <ul className="mt-2 grid gap-2">
            {list.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2">
                <Link href={`/portfolios/${p.id}`} className="font-bold hover:text-accent">
                  {p.name}
                </Link>
                <button
                  type="button"
                  className="text-sm text-muted hover:text-down"
                  onClick={() => {
                    forgetPortfolio(p.id);
                  }}
                >
                  فراموش کن (از این مرورگر)
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2 className="font-bold">پرتفوی تازه</h2>
        <form onSubmit={create} className="mt-2 flex flex-wrap items-end gap-2">
          <label className="grid gap-1 text-sm">
            نام
            <input
              className="ctl"
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="grid gap-1 text-sm">
            نقد آزاد برای خرید (تومان)
            <input
              className="ctl"
              inputMode="numeric"
              dir="ltr"
              value={cash}
              onChange={(e) => setCash(e.target.value)}
            />
          </label>
          <button className="btn btn-primary" disabled={busy || !name.trim()}>
            بساز
          </button>
        </form>
      </section>

      <section className="card">
        <h2 className="font-bold">وارد کردن با کلید</h2>
        <form onSubmit={importOne} className="mt-2 flex flex-wrap items-end gap-2">
          <label className="grid gap-1 text-sm">
            شناسه
            <input
              className="ctl w-24"
              dir="ltr"
              inputMode="numeric"
              value={imp.id}
              onChange={(e) => setImp({ ...imp, id: e.target.value })}
            />
          </label>
          <label className="grid gap-1 text-sm">
            کلید
            <input
              className="ctl"
              dir="ltr"
              value={imp.key}
              onChange={(e) => setImp({ ...imp, key: e.target.value })}
            />
          </label>
          <button className="btn" disabled={!imp.id || !imp.key}>
            وارد کن
          </button>
        </form>
      </section>
    </div>
  );
}
