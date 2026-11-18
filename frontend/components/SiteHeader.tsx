"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { SymbolSearch } from "@/components/SymbolSearch";

const NAV = [
  { href: "/", label: "امروز" },
  { href: "/market", label: "نمای بازار" },
  { href: "/industries", label: "صنایع و نمادها" },
  { href: "/model", label: "شانس ورود و مدل" },
  { href: "/picks", label: "خریدهای من" },
  { href: "/portfolios", label: "پرتفوی‌ها" },
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
    `nav-link block whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-semibold${active ? " is-on" : ""}`;

  return (
    <header ref={root} className="site-head sticky top-0 z-30">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
        <Link
          href="/"
          onClick={close}
          className="flex items-center gap-2"
          aria-label="Tmon، صفحهٔ اصلی"
        >
          <span className="logo-mark grid size-9 place-items-center rounded-xl text-lg font-black text-white">
            T
          </span>
          <span className="hidden text-xl font-extrabold tracking-tight text-accent sm:inline">
            Tmon
          </span>
        </Link>

        <nav aria-label="منوی اصلی" className="hidden items-center gap-0.5 xl:flex">
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

        <div className="ms-auto min-w-0 flex-1 xl:max-w-xs xl:flex-none">
          <SymbolSearch />
        </div>

        <ThemeToggle />

        <button
          type="button"
          aria-label={menu ? "بستن منو" : "باز کردن منو"}
          aria-expanded={menu}
          aria-controls="mobile-menu"
          onClick={() => setMenu(!menu)}
          className="btn size-11 shrink-0 p-0 xl:hidden"
          data-testid="menu-button"
        >
          <svg
            viewBox="0 0 24 24"
            width="22"
            height="22"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            {menu ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
          </svg>
        </button>
      </div>

      {menu && (
        <nav
          id="mobile-menu"
          aria-label="منوی موبایل"
          className="border-t border-line bg-surface xl:hidden"
        >
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
