import Link from "next/link";
import {
  apiGet,
  type GoldOil,
  type MarketIndex,
  type MarketOverview,
  type Ranking,
} from "@/lib/api";
import { jalali } from "@/lib/format";
import { ErrorState } from "@/components/ErrorState";
import { ExposureCard } from "@/components/ExposureCard";
import { IndexHero } from "@/components/market/IndexHero";
import { Heatmap } from "@/components/today/Heatmap";
import { MarketStrip } from "@/components/today/MarketStrip";
import { QuickLook } from "@/components/today/QuickLook";
import { StockTable } from "@/components/today/StockTable";

export const dynamic = "force-dynamic";

export default async function Home() {
  const [rank, market, gold, index] = await Promise.all([
    apiGet<Ranking>("/v2/ranking"),
    apiGet<MarketOverview>("/market/overview"),
    apiGet<GoldOil>("/macro/gold-oil"),
    apiGet<MarketIndex>("/market/index", { days: 300 }),
  ]);
  const ranked = rank.ok && rank.data.available ? rank.data : null;
  // what an ordinary buyer can act on: no funds, nothing stuck in a sell queue
  const rows = ranked
    ? ranked.rows.filter(
        (r) => !(r.name ?? "").startsWith("صندوق") && r.queue_state !== "sell_queue",
      )
    : [];

  return (
    <main className="space-y-5">
      <div className="space-y-1">
        <h1 className="page-title">امروز بازار چه شد؟</h1>
        <p className="lead">
          خلاصهٔ بازار، نقشهٔ سهم‌های پرمعامله و رتبهٔ هر سهم. رتبه‌بندی فقط یک ابزار کمکی است و توصیهٔ
          قطعی نیست.
        </p>
      </div>

      {index.ok && index.data.available && <IndexHero m={index.data} />}
      {market.ok && market.data.available && <MarketStrip m={market.data} />}
      <QuickLook gold={gold.ok ? gold.data : null} />

      {!rank.ok && <ErrorState message={rank.error} />}

      {ranked && (
        <>
          <Heatmap rows={rows} />
          {!ranked.recommendation_allowed && (
            <p className="alert-warn text-sm" data-testid="gate-note">
              رتبه‌بندی مدل، توصیه نیست: آزمون‌های پذیرش اعتبار مدل هنوز کامل نگذشته‌اند. داده تا{" "}
              {jalali(ranked.as_of, "weekday")}.
            </p>
          )}
          <StockTable rows={rows} />
          <p className="text-xs leading-6 text-muted" data-testid="today-note">
            رتبه‌بندی برای نگه‌داری حدود یک هفته یا بیشتر آزموده شده و برای یک روز، پس از کارمزد،
            سودی ندارد. هنوز همهٔ آزمون‌های پذیرش نگذشته‌اند؛ دلیل هر سهم در صفحهٔ خودش است.{" "}
            <Link href="/model#v2" className="text-accent underline">
              نتیجهٔ آزمون‌ها
            </Link>
          </p>
          <ExposureCard d={ranked} />
        </>
      )}
    </main>
  );
}
