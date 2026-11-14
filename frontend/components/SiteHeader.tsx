"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { SymbolSearch } from "@/components/SymbolSearch";

const NAV = [
  { href: "/", label: "امروز" },
  { href: "/market", label: "نمای بازار" },
  { href: "/industries", label: "صنایع و نمادها" },
  { href: "/model", label: "شانس ورود و مدل" },
  { href: "/picks", label: "خریدهای من" },
  { href: "/compare", label: "مقایسه" },
  { href: "/glossary", label: "واژه‌نامه" },
];

/** Sticky top bar: logo, main sections with the current one marked, search. */
export function SiteHeader() {
  const path = usePathname();
  const [menu, setMenu] = useState(false); // phone menu
  const here = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const close = () => {
    setMenu(false);
  };
  const root = useRef<HTMLElement>(null);
  // the phone menu closes on a click anywhere else, on Escape, and when focus leaves the header
  useEffect(() => {
    if (!menu) return;
    const away = (e: Event) => {
      if (root.current && !root.current.contains(e.target as Node)) {
        setMenu(false);
      }
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenu(false);
      }
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("focusin", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("focusin", away);
      document.removeEventListener("keydown", esc);
    };
  }, [menu]);
  const link = (active: boolean) =>
    `block whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors ${
      active ? "bg-accent text-surface" : "text-ink hover:bg-accent-soft"
    }`;

  return (
    <header
      ref={root}
      className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur"
    >
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
        <Link
          href="/"
          onClick={close}
          className="flex items-center gap-2"
          aria-label="Tmon، صفحهٔ اصلی"
        >
          <span className="grid size-9 place-items-center rounded-xl bg-accent text-lg font-black text-surface">
            T
          </span>
          <span className="hidden text-xl font-extrabold tracking-tight text-accent sm:inline">
            Tmon
          </span>
        </Link>

        <nav aria-label="منوی اصلی" className="hidden items-center gap-0.5 lg:flex">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              aria-current={here(n.href) ? "page" : undefined}
              className={link(here(n.href))}
            >
              {n.label}
            </Link>
          ))}
        </nav>

        <div className="ms-auto min-w-0 flex-1 lg:max-w-xs lg:flex-none">
          <SymbolSearch />
        </div>

        <button
          type="button"
          aria-label="منو"
          aria-expanded={menu}
          onClick={() => setMenu(!menu)}
          className="btn size-10 text-xl lg:hidden"
        >
          {menu ? "✕" : "☰"}
        </button>
      </div>

      {menu && (
        <nav aria-label="منوی موبایل" className="border-t border-line bg-surface lg:hidden">
          <ul className="mx-auto grid max-w-6xl gap-1 px-4 py-3 sm:grid-cols-2">
            {NAV.map((n) => (
              <li key={n.href}>
                <Link
                  href={n.href}
                  onClick={close}
                  aria-current={here(n.href) ? "page" : undefined}
                  className={`${link(here(n.href))} py-2.5`}
                >
                  {n.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </header>
  );
}
