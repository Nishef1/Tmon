"use client";

import { useEffect, useRef, useState } from "react";

export type JumpItem = { id: string; label: string };

/** A thin bar under the site header that stays in view: one tap goes to a section of this long
 *  page and the section being read is marked. On a phone it scrolls sideways. */
export function JumpNav({ items }: { items: JumpItem[] }) {
  const [active, setActive] = useState<string | null>(null);
  const key = items.map((i) => i.id).join(",");

  useEffect(() => {
    const els = key
      .split(",")
      .map((id) => document.getElementById(id))
      .filter((e): e is HTMLElement => !!e);
    if (els.length === 0) return;
    // the section whose top has most recently passed the line just under the two sticky bars
    const pick = () => {
      let cur: string | null = null;
      for (const el of els) {
        if (el.getBoundingClientRect().top <= 130) cur = el.id;
      }
      setActive(cur);
    };
    pick();
    window.addEventListener("scroll", pick, { passive: true });
    return () => window.removeEventListener("scroll", pick);
  }, [key]);

  // on a narrow screen the bar is wider than the page: slide it so the marked section is in view
  const nav = useRef<HTMLElement>(null);
  useEffect(() => {
    const bar = nav.current;
    const link = bar?.querySelector<HTMLElement>('[aria-current="true"]');
    if (!bar || !link || bar.scrollWidth <= bar.clientWidth) return;
    const b = bar.getBoundingClientRect();
    const l = link.getBoundingClientRect();
    bar.scrollBy({ left: l.left + l.width / 2 - (b.left + b.width / 2), behavior: "smooth" });
  }, [active]);

  return (
    <nav
      ref={nav}
      aria-label="بخش‌های صفحه"
      data-testid="jump-nav"
      className="jump-nav sticky top-[4.05rem] z-20 overflow-x-auto pb-1 pt-0.5 [scrollbar-width:none]"
    >
      <ul className="mx-auto flex w-max gap-1 rounded-full border border-line/60 bg-surface/55 p-1 shadow-sm shadow-black/5 ring-1 ring-inset ring-white/10 backdrop-blur-xl backdrop-saturate-150">
        {items.map((i) => (
          <li key={i.id}>
            <a
              href={`#${i.id}`}
              aria-current={active === i.id ? "true" : undefined}
              className="block whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm font-semibold text-muted transition-colors hover:bg-surface-2 hover:text-ink aria-[current=true]:bg-accent aria-[current=true]:text-white aria-[current=true]:shadow-sm"
            >
              {i.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
