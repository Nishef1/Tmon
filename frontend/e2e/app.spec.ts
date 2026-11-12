import { expect, test } from "@playwright/test";

const DISCLAIMER = "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست";

test.describe("recommendations", () => {
  test("renders RTL Persian with the disclaimer and ranked cards", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator("html")).toHaveAttribute("lang", "fa");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("توصیه‌های بازار سهام");
    await expect(page.getByTestId("disclaimer").first()).toHaveText(DISCLAIMER);
    const cards = page.getByTestId("signal-card");
    await expect(cards).toHaveCount(2);
    await expect(cards.first()).toContainText("فولاد");
    await expect(cards.first()).toContainText("۶۶٪");
  });

  test("has no horizontal scroll", async ({ page }) => {
    await page.goto("/");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("a number links to its glossary entry", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("signal-card").first().locator('a[href="/glossary/p_win"]').click();
    await expect(page).toHaveURL(/\/glossary\/p_win$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("احتمال موفقیت");
    await expect(page.getByRole("heading", { name: "محدودیت‌ها" })).toBeVisible();
  });

  test("W1 and M1 are selectable and show the same honest no-recommendation state", async ({
    page,
  }) => {
    await page.goto("/");
    for (const [tf, label] of [
      ["W1", "هفتگی (W1)"],
      ["M1", "ماهانه (M1)"],
    ]) {
      await page.getByRole("link", { name: label }).click();
      await expect(page).toHaveURL(new RegExp(`tf=${tf}`));
      await expect(page.getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
      await expect(page.getByTestId("no-recommendation")).toContainText(
        "امروز توصیه‌ای وجود ندارد",
      );
      await expect(page.getByTestId("signal-card")).toHaveCount(0);
      await expect(page.getByTestId("unsupported")).toHaveCount(0);
    }
  });

  test('"no recommendation" is shown plainly and explains why tier A is absent', async ({
    page,
  }) => {
    await page.goto("/?date=2025-02-20");
    await expect(page.getByTestId("no-recommendation")).toContainText("امروز توصیه‌ای وجود ندارد");
    await expect(page.getByTestId("signal-card")).toHaveCount(0);
    await expect(page.getByTestId("why-gate")).toContainText("کمتر از حداقل");
  });

  test("API failure shows a Persian error, not a crash", async ({ page }) => {
    await page.goto("/?date=2000-01-01");
    await expect(page.getByTestId("error-state")).toContainText("دریافت اطلاعات ممکن نشد");
    await expect(page.getByTestId("disclaimer").first()).toBeVisible();
  });
});

test.describe("instrument page", () => {
  test("draws the chart and lists indicators", async ({ page }) => {
    await page.goto("/instruments/1");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("فولاد");
    await expect(page.locator('[role="img"] canvas').first()).toBeVisible();
    await expect(page.getByText("RSI (۱۴ روزه)").first()).toBeVisible();
    await expect(page.getByTestId("disclaimer").first()).toBeVisible();
  });

  test("shows one final decision with its reasons and the per-symbol numbers", async ({ page }) => {
    await page.goto("/instruments/1");
    const decision = page.getByTestId("symbol-decision");
    await expect(decision).toHaveAttribute("data-verdict", "hold");
    await expect(decision).toContainText("نگهداری");
    await expect(decision).toContainText("رتبهٔ ۲۰ از ۱۰۰");
    await expect(decision.getByTestId("gauge")).toHaveAttribute("data-value", "81.0");
    await expect(decision.getByTestId("signal-bars")).toContainText("قدرت خریدار حقیقی");
    await expect(decision.getByTestId("holding")).toContainText("نه برای خرید و فروش در همان روز");
    const fa = page.getByTestId("fundamental");
    await expect(fa).toHaveAttribute("data-verdict", "cheap");
    await expect(fa).toContainText("سود هر سهم (EPS)");
    await expect(fa).toContainText("P/E گروه");
    const co = page.getByTestId("company");
    await expect(co).toContainText("مجمع بعدی");
    await expect(co).toContainText("۱۱ روز دیگر");
    await expect(co).toContainText("حجم مبنا");
    // candles are Heikin-Ashi by default, with a switch back to the real ones
    const ha = page.getByRole("button", { name: "شمع هایکن‌آشی" });
    await expect(ha).toHaveAttribute("aria-pressed", "true");
    await ha.click();
    await expect(ha).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("chart-legend")).toContainText("قیمت واقعی");
    const dash = page.getByTestId("symbol-dashboard");
    await expect(dash.getByText("قدرت خریدار (امروز)")).toBeVisible();
    await expect(dash.getByText("گروه صنعت")).toBeVisible();
  });

  test("shows the live price, five order-book levels and the data age", async ({ page }) => {
    await page.goto("/instruments/1");
    const live = page.getByTestId("live-quote");
    await expect(live.getByTestId("order-book").getByRole("row")).toHaveCount(6); // head + 5
    await expect(live.getByText("۱٬۰۱۲").first()).toBeVisible();
    await expect(live.getByTestId("live-age")).toContainText("آخرین به‌روزرسانی");
    await expect(live.getByTestId("live-age")).not.toContainText("قدیمی");
  });

  test("unknown instrument is a 404", async ({ page }) => {
    const res = await page.goto("/instruments/999");
    expect(res?.status()).toBe(404);
  });
});

test.describe("history and calibration", () => {
  test("history lists outcomes, filters, and labels returns as gross", async ({ page }) => {
    await page.goto("/history");
    await expect(page.getByRole("row")).toHaveCount(5);
    await expect(page.getByText(/ناخالص/).first()).toBeVisible();
    await page.getByRole("link", { name: "حد ضرر", exact: true }).click();
    await expect(page.getByRole("row")).toHaveCount(2);
  });

  test("calibration shows the gate reason, warnings and an empty live section", async ({
    page,
  }) => {
    await page.goto("/calibration");
    await expect(page.getByTestId("gate")).toContainText("سیگنال رده A منتشر نمی‌شود");
    await expect(page.getByText("تأیید نشده‌اند")).toBeVisible();
    await expect(page.getByTestId("no-live")).toBeVisible();
    await expect(page.getByRole("table")).toBeVisible();
  });
});

test("glossary index lists terms and each entry opens", async ({ page }) => {
  await page.goto("/glossary");
  await expect(page.getByRole("link", { name: /سود مورد انتظار/ })).toBeVisible();
  await page.getByRole("link", { name: /امتیاز بریر/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("امتیاز بریر");
});

test("ranking page is labelled a model ranking and shows the failed gates", async ({ page }) => {
  await page.goto("/ranking");
  await expect(page.getByTestId("disclaimer").first()).toHaveText(DISCLAIMER);
  await expect(page.getByTestId("ranking-status")).toContainText("توصیهٔ خرید نیست");
  await expect(page.getByTestId("ranking-status")).toContainText("معناداری آماری");
  await expect(page.getByTestId("zone-buy")).toContainText("شکام");
  await expect(page.getByTestId("zone-buy")).toContainText("صف خرید");
  await expect(page.getByTestId("zone-avoid")).toContainText("خودرو");
  await expect(page.getByTestId("zone-other")).toContainText("اروند");
  await expect(page.getByTestId("ranking-evidence")).toContainText("سنجیده نشده‌اند");
});

test("home lists only tradable v2 stocks and says what was left out", async ({ page }) => {
  await page.goto("/");
  const t = page.getByTestId("tradable-ranking");
  await expect(t).toContainText("توصیه نیست");
  await expect(t).not.toContainText("شکام ۰"); // in a buy queue: counted as left out, not listed
  await expect(t).toContainText("وبانک");
  await expect(t).toContainText("کنار گذاشته‌شده");
  await expect(page.getByTestId("gate-note")).toContainText("توصیهٔ مطمئن نیست");
  await expect(page.getByTestId("decision-hold")).toContainText("وبانک");
  await expect(page.getByTestId("decision-avoid")).toContainText("خودرو");
  await expect(page.getByTestId("decision-buy")).toContainText("امروز سهم عادیِ بدون صف");
});

test("screener shows flow columns, one decision per symbol and filters by decision", async ({
  page,
}) => {
  await page.goto("/screener");
  const table = page.getByTestId("screener-table");
  await expect(table).toContainText("سرانهٔ خرید");
  await expect(table).toContainText("قدرت خریدار");
  await expect(table.getByTestId("gauge")).toHaveCount(2);
  await expect(table.locator('[data-verdict="hold"]')).toContainText("نگهداری");
  await expect(page.getByTestId("verdict-counts")).toContainText("فروش");
  await page.goto("/screener?v=sell");
  await expect(page.getByTestId("screener-table").getByRole("row")).toHaveCount(2);
});

test("header search finds a symbol by name or industry and opens its page", async ({ page }) => {
  await page.goto("/screener");
  const box = page.getByTestId("symbol-search");
  await box.fill("فلزات");
  const hits = page.getByTestId("search-hit");
  await expect(hits).toHaveCount(2);
  await expect(hits.first()).toContainText("فلزات اساسی");
  await expect(hits.first()).toContainText("P/E");
  await expect(hits.first()).toContainText("نگهداری");
  await box.fill("فولاد");
  await expect(hits).toHaveCount(1);
  await box.press("Enter");
  await expect(page).toHaveURL(/\/instruments\/1$/);
});

test("screener shows industry, EPS and P/E per symbol", async ({ page }) => {
  await page.goto("/screener");
  const table = page.getByTestId("screener-table");
  await expect(table).toContainText("P/E گروه");
  await expect(table).toContainText("فلزات اساسی");
});

test("market page shows breadth, flow and movers, and says what it cannot show", async ({
  page,
}) => {
  await page.goto("/market");
  await expect(page.getByTestId("market-breadth")).toContainText("سهم‌های مثبت");
  await expect(page.getByTestId("market-bands")).toContainText("نزدیک صفر");
  await expect(page.getByTestId("market-flow")).toContainText("خالص ورود");
  await expect(page.getByTestId("market-gainers")).toContainText("الف");
  await expect(page.getByTestId("market-outflow")).toContainText("موردی نیست");
  await expect(page.getByTestId("market-sectors")).toContainText("کد گروه");
  await expect(page.locator("main")).toContainText("پوشش نمی‌دهیم");
});
