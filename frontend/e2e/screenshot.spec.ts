import { test } from "@playwright/test";
import { waitForDashboardReady, goToCharts, goToTrades, goToPortfolio } from "./helpers";

test("capture dashboard screenshot", async ({ page }) => {
  await page.goto("/");
  await waitForDashboardReady(page);
  await page.waitForTimeout(2000); // Let animations complete
  await page.screenshot({
    path: "e2e/proof-dashboard.png",
    fullPage: true,
  });
});

test("capture three-screen view", async ({ page }) => {
  await page.goto("/");
  await goToCharts(page);
  await page.locator("button", { hasText: "Three Screen" }).click();
  // Wait for all 3 screens to load (weekly + daily + hourly)
  await page.waitForTimeout(8000);
  await page.screenshot({
    path: "e2e/proof-three-screen.png",
    fullPage: true,
  });
});

test("capture trade panel", async ({ page }) => {
  await page.goto("/");
  await goToTrades(page);
  await page.waitForTimeout(1000);
  await page.screenshot({
    path: "e2e/proof-trade-panel.png",
    fullPage: true,
  });
});

test("capture funds panel", async ({ page }) => {
  await page.goto("/");
  await goToPortfolio(page);
  await page.waitForTimeout(2000);
  await page.screenshot({
    path: "e2e/proof-funds.png",
    fullPage: true,
  });
});
