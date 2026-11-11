import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tmon",
  description: "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl">
      <body className="min-h-screen bg-white text-neutral-900 antialiased">{children}</body>
    </html>
  );
}
