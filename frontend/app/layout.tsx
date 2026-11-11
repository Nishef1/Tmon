import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";
import { Disclaimer } from "@/components/Disclaimer";

export const metadata: Metadata = {
  title: { default: "Tmon", template: "%s | Tmon" },
  description: "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

const NAV = [
  { href: "/", label: "توصیه‌های امروز" },
  { href: "/history", label: "سابقه سیگنال‌ها" },
  { href: "/calibration", label: "کالیبراسیون" },
  { href: "/compare", label: "مقایسه با تورم" },
  { href: "/glossary", label: "واژه‌نامه" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl">
      <body className="min-h-screen antialiased">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-5xl items-center gap-4 px-4 py-3">
            <Link href="/" className="text-xl font-extrabold tracking-tight text-accent">
              Tmon
            </Link>
            <nav aria-label="منوی اصلی" className="-mx-1 flex-1">
              <ul className="flex flex-wrap gap-x-1 text-sm">
                {NAV.map((n) => (
                  <li key={n.href}>
                    <Link
                      href={n.href}
                      className="inline-block rounded-lg px-3 py-2 hover:bg-accent-soft"
                    >
                      {n.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </div>
        </header>
        <div className="mx-auto max-w-5xl px-4 py-6">{children}</div>
        <footer className="mx-auto max-w-5xl px-4 pb-10">
          <Disclaimer />
          <p className="mt-3 text-xs text-muted">
            خروجی‌ها برآورد آماری از داده‌های گذشته‌اند و هیچ بازده یا نتیجه‌ای را تضمین نمی‌کنند.
          </p>
        </footer>
      </body>
    </html>
  );
}
