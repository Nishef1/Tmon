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

  test("W1 and M1 are visibly not yet available", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("هفتگی (W1) · به‌زودی")).toBeVisible();
    await page.goto("/?tf=W1");
    await expect(page.getByTestId("unsupported")).toBeVisible();
  });

  test('"no recommendation" is shown plainly and explains why tier A is absent', async ({
    page,
  }) => {
    await page.goto("/?date=2025-02-20");
    await expect(page.getByTestId("no-recommendation")).toContainText("امروز توصیه‌ای وجود ندارد");
    await expect(page.getByTestId("signal-card")).toHaveCount(0);
    await expect(page.getByTestId("tier-a-gate")).toContainText("کمتر از حداقل");
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
