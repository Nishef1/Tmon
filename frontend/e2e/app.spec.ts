import { expect, test } from "@playwright/test";

const DISCLAIMER = "ابزار تحلیل و آموزش؛ توصیه سرمایه‌گذاری نیست";

test.describe("home", () => {
  test("renders RTL Persian with the disclaimer", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator("html")).toHaveAttribute("lang", "fa");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("امروز بازار چه شد؟");
    await expect(page.getByTestId("disclaimer").first()).toHaveText(DISCLAIMER);
  });

  test("has no horizontal scroll", async ({ page }) => {
    await page.goto("/");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

test.describe("instrument page", () => {
  test("draws the chart and lists indicators", async ({ page }) => {
    await page.goto("/instruments/1");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("فولاد");
    await expect(page.locator('[role="img"] canvas').first()).toBeVisible();
    await expect(page.getByTestId("technical")).toContainText("RSI ۱۴ روزه");
    await expect(page.getByTestId("disclaimer").first()).toBeVisible();
  });

  test("gives one verdict at the 60-day horizon with the grade of its zone", async ({ page }) => {
    await page.goto("/instruments/1");
    const hz = page.getByTestId("horizons");
    await expect(hz).toHaveAttribute("data-horizon", "Q1");
    await expect(hz).toHaveAttribute("data-verdict", "candidate");
    await expect(page.getByTestId("horizon-D1")).toHaveCount(0);
    await expect(page.getByTestId("verdict-word")).toHaveText("نامزد خرید");
    await expect(page.getByTestId("verdict-grade")).toContainText("ثابت‌نشده");
    await expect(page.getByTestId("checks")).toContainText("بعد از کارمزد و مالیات");
  });

  test("shows one final decision with its reasons and the per-symbol numbers", async ({ page }) => {
    await page.goto("/instruments/1");
    const decision = page.getByTestId("symbol-decision");
    await expect(decision).toHaveAttribute("data-verdict", "candidate");
    await expect(decision).toContainText("نامزد خرید");
    await expect(decision).toContainText("رتبهٔ ۲۰");
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
    // the long table is gone: the header and the flow bars carry the numbers, one line keeps the rest
    const facts = page.locator('[data-fold="facts"]');
    await expect(facts.getByTestId("facts-table")).toHaveCount(0);
    await expect(facts.getByTestId("facts-line")).toContainText("دامنهٔ مجاز نوسان");
    await expect(facts.getByTestId("facts-line")).toContainText("میانگین حجم ۱۰ روزه");
  });

  test("lists the major shareholders with percent and change", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await page.goto("/instruments/1");
    const box = page.getByTestId("shareholders");
    await expect(box).toContainText("شرکت نمونه");
    await expect(box).toContainText("۱۶٫۷۰٪");
    // several holders can share one name; the list must still render without key warnings
    await expect(box.getByText("شخص حقیقی")).toHaveCount(2);
    expect(errors.filter((e) => e.includes("same key"))).toEqual([]);
  });

  test("shows what moves the stock outside its chart", async ({ page }) => {
    await page.goto("/instruments/1");
    const box = page.getByTestId("drivers");
    await expect(box).toContainText("تندتر از بازار");
    await expect(box).toContainText("۳۷۰ ریال");
    await expect(box.getByTestId("drivers-moves")).toContainText("جنگ ۱۲ روزه");
  });

  test("technical card reads every indicator and the tested history", async ({ page }) => {
    await page.goto("/instruments/1");
    const box = page.getByTestId("technical");
    await expect(box.getByTestId("ta-values")).toContainText("اشباع فروش");
    await expect(box.getByTestId("ta-fired")).toContainText("در گذشته جواب داده است");
    await expect(box.getByTestId("ta-risk")).toContainText("۱٫۲۵");
    await expect(box.locator('a[href="/glossary/rsi"]')).toBeVisible();
  });

  test("chart draws glossary overlays and a lower pane", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/instruments/1");
    await page.getByRole("button", { name: "ایچیموکو", exact: true }).click();
    await page.getByRole("button", { name: "MACD", exact: true }).click();
    const terms = page.getByTestId("chart-terms");
    await expect(terms.locator('a[href="/glossary/ichimoku"]')).toBeVisible();
    await expect(terms.locator('a[href="/glossary/macd"]')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("shows the tested sell warning once, in the technical card", async ({ page }) => {
    await page.goto("/instruments/1");
    const w = page.getByTestId("ta-fired");
    await expect(w).toContainText("حجم مشکوک با افت و خروج حقیقی");
    await expect(w).toContainText("۴ روز پیش");
    // the same warning is not repeated in the turning card beside it
    await expect(page.getByTestId("turning-warning")).toHaveCount(0);
    await expect(page.getByTestId("turning")).toBeVisible();
  });

  test("lists the Codal letters of the symbol", async ({ page }) => {
    await page.goto("/instruments/1");
    const box = page.getByTestId("codal-letters");
    await expect(box).toContainText("افزایش سرمایه از محل سود انباشته");
    // news whose headline names the symbol sits in the same timeline, newest first
    await expect(box.locator("li").first()).toHaveAttribute("data-kind", "news");
    await expect(box).toContainText("رکورد تولید ماهانه");
  });

  test("shows the live price, five order-book levels and the data age while the market is open", async ({
    page,
  }) => {
    // Sunday 09:30 in Tehran: inside the session
    await page.clock.setFixedTime(new Date("2026-11-15T09:30:00+03:30"));
    await page.goto("/instruments/1");
    const live = page.getByTestId("live-quote");
    await expect(live.getByTestId("order-book").getByRole("row")).toHaveCount(6); // head + 5
    await expect(live.getByText("۱٬۰۱۲").first()).toBeVisible();
    await expect(live.getByTestId("live-age")).toContainText("آخرین به‌روزرسانی");
    await expect(live.getByTestId("live-age")).not.toContainText("قدیمی");
  });

  test("hides the live price when the market is closed", async ({ page }) => {
    // Friday: the exchange does not trade
    await page.clock.setFixedTime(new Date("2026-11-20T10:00:00+03:30"));
    await page.goto("/instruments/1");
    await expect(page.getByTestId("stock-header")).toBeVisible();
    await expect(page.getByTestId("live-quote")).toHaveCount(0);
  });

  test("puts the verdict before the chart and keeps the meeting and its calculator together", async ({
    page,
  }) => {
    await page.goto("/instruments/1");
    const verdict = await page.getByTestId("symbol-decision").boundingBox();
    const chart = await page.getByTestId("chart-section").boundingBox();
    expect(verdict && chart && verdict.y < chart.y).toBe(true);
    const agm = page.locator('[data-fold="agm"]');
    await expect(agm.getByTestId("company")).toContainText("مجمع بعدی");
    await expect(agm.locator("form")).toBeVisible();
  });

  test("unknown instrument is a 404", async ({ page }) => {
    const res = await page.goto("/instruments/999");
    expect(res?.status()).toBe(404);
  });

  test("the address is industry and symbol, and the old number leads there", async ({ page }) => {
    await page.goto("/instruments/1");
    await expect(page).toHaveURL(
      /\/instruments\/%D9%81%D9%84%D8%B2%D8%A7%D8%AA-%D8%A7%D8%B3%D8%A7%D8%B3%DB%8C\/%D9%81%D9%88%D9%84%D8%A7%D8%AF$/,
    );
    await expect(page.getByTestId("chart-section")).toBeVisible();
    // a typed Arabic yeh or kaf still finds the page and is sent to the one address
    await page.goto(
      `/instruments/${encodeURIComponent("فلزات-اساسي")}/${encodeURIComponent("فولاد")}`,
    );
    await expect(page.getByTestId("chart-section")).toBeVisible();
    const res = await page.goto(
      `/instruments/${encodeURIComponent("فلزات-اساسی")}/${encodeURIComponent("نامعلوم")}`,
    );
    expect(res?.status()).toBe(404);
  });
});

test("old signal pages lead to the model page", async ({ page }) => {
  for (const old of ["/history", "/calibration", "/accuracy"]) {
    await page.goto(old);
    await expect(page).toHaveURL(/\/model$/);
  }
});

test("a bought symbol is checked against the candles after it", async ({ page }) => {
  await page.goto("/instruments/1");
  await page.getByTestId("track-buy").getByRole("button").first().click();
  await page.getByTestId("track-price").fill("1000");
  await page.getByTestId("track-save").click();
  await expect(page.getByTestId("track-done")).toContainText("ثبت شد");

  await page.goto("/picks");
  const pick = page.getByTestId("pick");
  await expect(pick).toContainText("فولاد");
  const rows = pick.getByTestId("pick-candles").locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toHaveAttribute("data-status", "inside");
  await expect(rows.nth(1)).toHaveAttribute("data-status", "above");
  await expect(rows.nth(2)).toHaveAttribute("data-status", "pending");
  await expect(pick.getByTestId("pick-score")).toContainText("۱ تا داخل بازه");
  await expect(pick.getByTestId("pick-verdicts")).toContainText("تصمیم درست بود");
});

test("a chart term's glossary entry shows where it is and how it tested", async ({ page }) => {
  await page.goto("/glossary/gap_fill");
  await expect(page.getByTestId("term-shown-on")).toContainText("تحلیل تکنیکال");
  const t = page.getByTestId("term-tests");
  await expect(t).toContainText("گشایش با شکاف منفی ۳٪");
  await expect(t).toContainText("کمی برعکس");
  await expect(t.getByTestId("term-test").getByRole("row")).toHaveCount(7);
  // a term with no tested reading has neither section
  await page.goto("/glossary/pb");
  await expect(page.getByTestId("term-tests")).toHaveCount(0);
});

test("glossary index lists terms and each entry opens", async ({ page }) => {
  await page.goto("/glossary");
  await expect(page.getByRole("link", { name: /سود مورد انتظار/ }).first()).toBeVisible();
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

test("home has one ranking table, the gate note and the market map; old ranking address redirects", async ({
  page,
}) => {
  await page.goto("/ranking");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("zone-details")).toHaveCount(0);
  await expect(page.getByTestId("gate-note")).toContainText("توصیه نیست");
  await expect(page.getByTestId("today-note")).toContainText("یک هفته");
  await expect(page.getByTestId("stock-table")).toContainText("وبانک");
  // the market card: share of capital in equities, why, and the funds, labelled untested
  const card = page.getByTestId("market-card");
  await expect(card).toContainText("۹۹٫۰٪");
  await expect(card.getByTestId("market-reasons")).toContainText("روند");
  await expect(card.getByTestId("market-funds")).toContainText("آزموده نشده");
  await expect(card.getByTestId("market-funds")).toContainText("اهرم");
  await expect(page.getByTestId("heatmap")).toBeVisible();
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
  await expect(table.locator('[data-verdict="hold"]').first()).toContainText("همراه بازار");
});

test("header search finds a symbol by name or industry and opens its page", async ({ page }) => {
  await page.goto("/industries");
  const box = page.getByTestId("symbol-search");
  await box.fill("فلزات");
  const hits = page.getByTestId("search-hit");
  await expect(hits).toHaveCount(2);
  await expect(hits.first()).toContainText("فلزات اساسی");
  await expect(hits.first()).toContainText("P/E");
  await expect(hits.first()).toContainText("همراه بازار");
  await box.fill("فولاد");
  await expect(hits).toHaveCount(1);
  await box.press("Enter");
  await expect(page).toHaveURL(new RegExp("/instruments/[^/]+/%D9%81%D9%88%D9%84%D8%A7%D8%AF$"));
});

test("search marks a stopped symbol and can hide stopped symbols", async ({ page }) => {
  await page.goto("/industries");
  const box = page.getByTestId("symbol-search");
  await box.fill("متوقف");
  const hits = page.getByTestId("search-hit");
  await expect(hits).toHaveCount(1);
  await expect(hits.first().getByTestId("trade-badge")).toContainText("متوقف");
  await page.getByLabel(/فقط نمادهای در حال معامله/).check();
  await expect(hits).toHaveCount(0);
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

test.describe("entry odds and the chart", () => {
  test("chart keeps the zoom when overlays, panes and parameters change", async ({ page }) => {
    await page.goto("/instruments/1");
    const box = page.locator("[data-view]");
    await page.getByRole("button", { name: "۱ ماه", exact: true }).click();
    await expect(box).toHaveAttribute("data-view", /\d+:\d+/);
    const view = await box.getAttribute("data-view");
    await page.getByRole("button", { name: "ایچیموکو", exact: true }).click();
    await page.getByRole("button", { name: "MACD", exact: true }).click();
    await expect(box).toHaveAttribute("data-view", view!);
    await page.getByRole("button", { name: "پارامترها", exact: true }).click();
    const params = page.getByTestId("chart-params");
    await params.getByLabel("میانگین ۱", { exact: true }).fill("30");
    await expect(page.getByRole("button", { name: /۳۰/ }).first()).toBeVisible();
    await expect(box).toHaveAttribute("data-view", view!);
  });

  test("symbol page keeps the entry lab to one line when no state beat or trailed the market", async ({
    page,
  }) => {
    await page.goto("/instruments/1");
    // every state of today made no difference, so there is no card, only the one line
    await expect(page.getByTestId("entry-odds")).toHaveCount(0);
    await expect(page.getByTestId("entry-none")).toContainText("بهتر یا بدتر نبوده");
    // the price range is its own card, open by default, apart from the verdict
    const range = page.getByTestId("price-range");
    await expect(range.getByTestId("candles-vs-verdict")).toContainText(
      "از حکم «چه کنم؟» مستقل است",
    );
    const next = range.getByTestId("next-candles");
    // this year is the default; each row is one plain range with one percentage
    await expect(next).toHaveAttribute("data-window", "year");
    await expect(next.locator('tr[data-h="5"]')).toContainText("۹۴۰ تا ۱٬۰۹۰");
    await expect(next).toContainText("۸ مورد از هر ۱۰ مورد گذشته");
    await expect(next).not.toContainText("بالاتر از قیمت خرید");
    await next.getByRole("button", { name: "۳ سال" }).click();
    await expect(next).toHaveAttribute("data-window", "y3");
  });

  test("model page leads with the entry lab", async ({ page }) => {
    await page.goto("/model");
    const lab = page.getByTestId("entry-lab");
    await expect(lab.getByTestId("streak-ladder").locator("[data-key]")).toHaveCount(3);
    await expect(lab.getByTestId("entry-facts")).toContainText("شش شمع سبز یا بیشتر (بهتر)");
    await lab.getByRole("button", { name: "ورود از کف چندماهه" }).click();
    await expect(lab.getByTestId("entry-setups").locator("> li")).toHaveCount(2);
    await lab.getByRole("button", { name: "فقط حکم‌دار" }).click();
    await expect(lab.getByTestId("entry-setups").locator("> li")).toHaveCount(1);
    await expect(lab.locator('[data-key="base_rsi30"]')).toContainText("بهتر از بقیهٔ سهم‌ها");
    const years = lab.locator('[data-key="base_rsi30"]').getByTestId("year-strip");
    await expect(years.locator("[data-year]")).toHaveCount(5);
    await expect(years).toContainText("از ۴ سال، ۲ سال بهتر و ۱ سال بدتر");
  });

  test("compare puts symbols side by side and keeps the inflation table", async ({ page }) => {
    await page.goto("/compare?s=1");
    const sec = page.getByTestId("compare-symbols");
    await expect(sec.getByTestId("compare-legend")).toContainText("فولاد");
    await expect(sec.getByTestId("compare-table")).toContainText("دو شمع قرمز پشت سر هم");
    await expect(sec.getByTestId("compare-table")).toContainText("۲ قرمز پشت سر هم");
    await expect(page.locator("#inflation")).toBeVisible();
    await sec.getByRole("button", { name: "حذف فولاد از مقایسه" }).click();
    await expect(page).toHaveURL(/\/compare\?months=12/);
    await expect(sec).toContainText("نماد اضافه کنید");
  });
});

test("home opens on the market strip and a sortable stock table", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("market-strip")).toBeVisible();
  const table = page.getByTestId("stock-table");
  await expect(table).toContainText("وبانک");
  await table.getByRole("tab", { name: /پرهیز/ }).click();
  await expect(table).toContainText("خودرو");
  await expect(table).not.toContainText("وبانک");
});
