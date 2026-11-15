"use client";

import { useEffect, useState } from "react";

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

  return (
    <nav
      aria-label="بخش‌های صفحه"
      data-testid="jump-nav"
      className="jump-nav sticky top-[3.9rem] z-20 -mx-4 overflow-x-auto border-b border-line bg-surface/95 px-4 backdrop-blur"
    >
      <ul className="flex w-max min-w-full gap-1 py-1.5">
        {items.map((i) => (
          <li key={i.id}>
            <a
              href={`#${i.id}`}
              aria-current={active === i.id ? "true" : undefined}
              className="block whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-semibold text-muted transition-colors hover:bg-accent-soft hover:text-ink aria-[current=true]:bg-accent-soft aria-[current=true]:text-accent"
            >
              {i.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
