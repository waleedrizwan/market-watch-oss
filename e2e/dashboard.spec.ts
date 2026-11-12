import { expect, test, type Page } from "@playwright/test";

const card = (page: Page, id: string) => page.locator(`#chain-${id}`);

test.describe("dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".card")).toHaveCount(5);
  });

  test("leads with what's likely to change price", async ({ page }) => {
    await expect(page.locator("h1")).toHaveText("1 thing is likely to cost more, and 1 is likely to cost less within 6 months.");
    await expect(page.locator("#hero-detail")).toContainText("Watching 5 product chains");
    await expect(page.locator("#updated")).toHaveText("Updated 2 h ago");
  });

  test("sorts chains into buckets in order", async ({ page }) => {
    const kinds = await page.locator(".bucket").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.kind));
    expect(kinds).toEqual(["rise", "fall", "fast", "steady", "weak"]);
    await expect(page.locator('.bucket[data-kind="rise"] h2')).toContainText("Likely to rise1");
    await expect(page.locator('.bucket[data-kind="rise"] .card')).toHaveAttribute("id", "chain-beef");
  });

  test("shows the forecast number only where there is one", async ({ page }) => {
    await expect(card(page, "beef").locator("[data-big-value]")).toHaveText("+7.2%");
    await expect(card(page, "gas").locator("[data-big-value]")).toHaveText("−5.1%");
    await expect(card(page, "eggs").locator("[data-big]")).toBeHidden();
    await expect(card(page, "computers").locator("[data-big]")).toBeHidden();
    await expect(card(page, "beef").locator("[data-track]")).toContainText("called the direction right 5 of 6 times");
  });

  test("a broken source is called out, not hidden", async ({ page }) => {
    const c = card(page, "computers");
    await expect(c.locator(".pill.stale")).toHaveText("Stale data");
    await expect(c.locator("[data-stale] li")).toContainText("not in table 'Wafer Spot Price'");
    await expect(c.locator("[data-gap]")).toContainText("not enough history yet");
    await expect(card(page, "beef").locator(".pill.stale")).toHaveCount(0);
  });

  test("filters by group and remembers the choice", async ({ page }) => {
    await page.locator('#filters [data-group="Food"]').click();
    await expect(page.locator(".card")).toHaveCount(3);
    await expect(page.locator('.bucket[data-kind="fall"] .empty')).toHaveText("Nothing is flagged to fall right now.");
    await page.reload();
    await expect(page.locator('#filters [data-group="Food"]')).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".card")).toHaveCount(3);
    await page.locator('#filters [data-group="All"]').click();
    await expect(page.locator(".card")).toHaveCount(5);
  });

  test("opens a chart with a series table, ranges and links", async ({ page }) => {
    const c = card(page, "computers");
    const toggle = c.locator("[data-toggle]");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toggle).toHaveText("Hide chart");
    await expect(c.locator("canvas")).toBeVisible();
    expect((await c.locator("canvas").boundingBox())!.height).toBeGreaterThan(200);
    await expect(c.locator("tbody tr")).toHaveCount(4);
    await expect(c.locator('tr[data-series="cpi_computers"] td').nth(3)).toContainText("1m");
    await expect(c.locator('tr[data-series="nand_wafer"] .stale-text')).toBeVisible();
    await expect(c.locator(".links a")).toHaveAttribute("href", "https://www.dramexchange.com/");
    await expect(c.locator(".detail")).not.toContainText("null");

    await c.locator('[data-range="10Y"]').click();
    await expect(c.locator('[data-range="10Y"]')).toHaveAttribute("aria-pressed", "true");
    await expect(c.locator('[data-range="3Y"]')).toHaveAttribute("aria-pressed", "false");

    await toggle.click();
    await expect(c.locator(".detail")).toBeHidden();
  });

  test("works from the keyboard", async ({ page }) => {
    const toggle = card(page, "beef").locator("[data-toggle]");
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const range = card(page, "beef").locator('[data-range="1Y"]');
    await range.focus();
    await page.keyboard.press("Space");
    await expect(range).toHaveAttribute("aria-pressed", "true");
  });

  test("links to the privacy policy", async ({ page }) => {
    await page.getByRole("link", { name: "Privacy policy" }).click();
    await expect(page).toHaveURL(/\/privacy$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Privacy policy");
  });
});

test("no console errors, CSP violations or requests to other sites", async ({ page, baseURL }) => {
  const problems: string[] = [];
  const origins = new Set<string>();
  page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("request", (r) => origins.add(new URL(r.url()).origin));
  await page.goto("/");
  await page.locator("#chain-beef [data-toggle]").click();
  await expect(page.locator("#chain-beef canvas")).toBeVisible();
  await page.goto("/privacy");
  expect(problems).toEqual([]);
  expect([...origins]).toEqual([new URL(baseURL!).origin]);
});

test("fits the screen without sideways scrolling, even with a chart open", async ({ page }) => {
  await page.goto("/");
  await page.locator("#chain-computers [data-toggle]").click();
  await expect(page.locator("#chain-computers canvas")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("explains a failed data load", async ({ page }) => {
  await page.route("**/data.json", (r) => r.fulfill({ status: 500, body: "" }));
  await page.goto("/");
  await expect(page.getByRole("alert")).toHaveText("The data request failed (HTTP 500). Reload the page to try again.");
  await expect(page.locator("#updated")).toHaveText("Data unavailable");
});

test("renders in dark mode", async ({ browser, baseURL }) => {
  const ctx = await browser.newContext({ colorScheme: "dark" });
  const page = await ctx.newPage();
  await page.goto(baseURL!);
  await expect(page.locator(".card").first()).toBeVisible();
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe("rgb(16, 22, 31)");
  await ctx.close();
});
