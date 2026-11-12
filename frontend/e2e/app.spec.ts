import { expect, test } from "@playwright/test";

const DISCLAIMER = "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست";

test.describe("recommendations", () => {
  test("renders RTL Persian with the disclaimer and ranked cards", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator("html")).toHaveAttribute("lang", "fa");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      "توصیه‌های امروز بازار سهام",
    );
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

  test("lists the major shareholders with percent and change", async ({ page }) => {
    await page.goto("/instruments/1");
    const box = page.getByTestId("shareholders");
    await expect(box).toContainText("شرکت نمونه");
    await expect(box).toContainText("۱۶٫۷۰٪");
  });

  test("lists the Codal letters of the symbol", async ({ page }) => {
    await page.goto("/instruments/1");
    await expect(page.getByTestId("codal-letters")).toContainText(
      "افزایش سرمایه از محل سود انباشته",
    );
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
    await page.goto("/model");
    const history = page.locator("#history");
    await expect(history.getByRole("row")).toHaveCount(5);
    await expect(history.getByText(/ناخالص/).first()).toBeVisible();
    await history.getByRole("link", { name: "حد ضرر", exact: true }).click();
    await expect(page.locator("#history").getByRole("row")).toHaveCount(2);
    await page.goto("/history"); // old address still works
    await expect(page).toHaveURL(/\/model/);
  });

  test("calibration shows the gate reason, warnings and an empty live section", async ({
    page,
  }) => {
    await page.goto("/model");
    await expect(page.getByTestId("gate")).toContainText("سیگنال رده A منتشر نمی‌شود");
    await expect(page.getByText("تأیید نشده‌اند")).toBeVisible();
    await expect(page.getByTestId("no-live")).toBeVisible();
    await expect(page.locator("#calibration").getByRole("table").first()).toBeVisible();
  });
});

test("glossary index lists terms and each entry opens", async ({ page }) => {
  await page.goto("/glossary");
  await expect(page.getByRole("link", { name: /سود مورد انتظار/ })).toBeVisible();
  await page.getByRole("link", { name: /امتیاز بریر/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("امتیاز بریر");
});

test("model page is labelled a model ranking and shows the failed gates", async ({ page }) => {
  await page.goto("/model");
  await expect(page.getByTestId("disclaimer").first()).toHaveText(DISCLAIMER);
  await expect(page.getByTestId("ranking-status")).toContainText("توصیهٔ خرید نیست");
  await expect(page.getByTestId("ranking-status")).toContainText("معناداری آماری");
  await expect(page.getByTestId("ranking-evidence")).toContainText("سنجیده نشده‌اند");
});

test("home shows the full zone tables behind a fold and the old ranking address redirects", async ({
  page,
}) => {
  await page.goto("/ranking");
  await expect(page).toHaveURL(/\/$/);
  await page.getByTestId("zone-details").locator("summary").click();
  await expect(page.getByTestId("zone-buy")).toContainText("شکام");
  await expect(page.getByTestId("zone-buy")).toContainText("صف خرید");
  await expect(page.getByTestId("zone-avoid")).toContainText("خودرو");
  await expect(page.getByTestId("zone-other")).toContainText("اروند");
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

test("the old all-symbols address opens the industries page with the search filled in", async ({
  page,
}) => {
  await page.goto("/screener?q=فلزات");
  await expect(page).toHaveURL(/\/industries\?q=/);
  await expect(page.getByRole("searchbox").first()).toHaveValue("فلزات");
});

test("industries table shows one decision per symbol with its gauge and flow columns", async ({
  page,
}) => {
  await page.goto("/industries");
  const table = page.getByTestId("industry-table");
  await expect(table).toContainText("قدرت خریدار");
  await expect(table.getByTestId("gauge").first()).toBeVisible();
  await expect(table.locator('[data-verdict="hold"]').first()).toContainText("نگهداری");
});

test("header search finds a symbol by name or industry and opens its page", async ({ page }) => {
  await page.goto("/industries");
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

test("market page shows breadth, flow and movers, and says what it cannot show", async ({
  page,
}) => {
  await page.goto("/market");
  await expect(page.getByTestId("market-breadth")).toContainText("سهم‌های مثبت");
  await expect(page.getByTestId("market-bands")).toContainText("نزدیک صفر");
  await expect(page.getByTestId("market-flow")).toContainText("خالص ورود");
  await expect(page.getByTestId("market-gainers")).toContainText("الف");
  await expect(page.getByTestId("market-outflow")).toContainText("موردی نیست");
  await expect(page.getByTestId("market-gainers")).toContainText("نام الف");
  await expect(page.locator("main")).toContainText("پوشش نمی‌دهیم");
});

test("market page points to the groups on the industries page", async ({ page }) => {
  await page.goto("/market");
  await page.getByTestId("market-sectors").getByRole("link").click();
  await expect(page).toHaveURL(/\/industries/);
});

test("industries page groups stocks, searches and opens a symbol", async ({ page }) => {
  await page.goto("/industries");
  const table = page.getByTestId("industry-table");
  await expect(table).toContainText("فلزات اساسی");
  await expect(table).toContainText("وبانک");
  await page.getByRole("searchbox").first().fill("خودر");
  await expect(table).not.toContainText("وبانک");
  await expect(table).toContainText("خودرو");
  await table.getByText("خودرو").first().click();
  await expect(page).toHaveURL(/\/instruments\/2/);
});
