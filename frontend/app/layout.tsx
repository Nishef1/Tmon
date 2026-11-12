import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Disclaimer } from "@/components/Disclaimer";
import { SiteHeader } from "@/components/SiteHeader";

export const metadata: Metadata = {
  title: { default: "Tmon", template: "%s | Tmon" },
  description: "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl">
      <body className="min-h-screen antialiased">
        <SiteHeader />
        <div className="mx-auto max-w-6xl px-4 py-6">{children}</div>
        <footer className="mx-auto max-w-6xl px-4 pb-10">
          <Disclaimer />
          <p className="mt-3 text-xs text-muted">
            خروجی‌ها برآورد آماری از داده‌های گذشته‌اند و هیچ بازده یا نتیجه‌ای را تضمین نمی‌کنند.
          </p>
        </footer>
      </body>
    </html>
  );
}
