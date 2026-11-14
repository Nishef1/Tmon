import type { Metadata } from "next";
import { PortfolioList } from "@/components/portfolio/PortfolioList";

export const metadata: Metadata = { title: "پرتفوی‌ها" };

export default function PortfoliosPage() {
  return (
    <main className="grid gap-4">
      <h1 className="page-title">پرتفوی‌ها</h1>
      <p className="lead">
        هر پرتفوی جدا با کلید خودش. در ساعت بازار هر ۲۰ ثانیه دیده‌بانی می‌شود و به محض صف فروش،
        افت، جهش حجم، خبر یا اطلاعیهٔ منفی هشدار می‌دهد و می‌پرسد خارج می‌شوی یا نه.
      </p>
      <PortfolioList />
    </main>
  );
}
