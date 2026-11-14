import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PortfolioView } from "@/components/portfolio/PortfolioView";

export const metadata: Metadata = { title: "پرتفوی" };

export default async function PortfolioPage({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id);
  if (!Number.isInteger(id) || id <= 0) notFound();
  return (
    <main>
      <PortfolioView id={id} />
    </main>
  );
}
