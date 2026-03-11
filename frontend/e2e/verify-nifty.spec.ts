/**
 * Verify NIFTY data is loading and displaying in the frontend.
 * Uses broker reset + resilient waits.
 */
import { test, expect } from "@playwright/test";

test("NIFTY end-to-end verification", async ({ page, request }) => {
  test.setTimeout(120_000);

  // Reset broker offline state before test
  await request.post("http://localhost:8000/api/charts/reset-broker").catch(() => {});

  // Verify backend serves NIFTY data directly via API
  const apiCheck = await request.get(
    "http://localhost:8000/api/charts/candles?symbol=NIFTY&exchange=NFO&interval=1d&days=365"
  );
  expect(apiCheck.ok()).toBeTruthy();
  const apiData = await apiCheck.json();
  expect(apiData.count).toBeGreaterThan(100);
  expect(apiData.source).toBe("live");
  console.log(`API direct check: ${apiData.count} candles, source=${apiData.source}`);

  // Also verify indicators API returns live NIFTY data
  const indCheck = await request.get(
    "http://localhost:8000/api/indicators/compute?symbol=NIFTY&exchange=NFO&interval=1d&days=365"
  );
  expect(indCheck.ok()).toBeTruthy();
  const indData = await indCheck.json();
  expect(indData.symbol).toBe("NIFTY");
  expect(indData.count).toBeGreaterThan(100);
  const ema13 = (indData.data?.ema13 || []).filter((v: number | null) => v !== null);
  expect(ema13.length).toBeGreaterThan(50);
  const lastEma = ema13[ema13.length - 1];
  expect(lastEma).toBeGreaterThan(15000); // NIFTY range
  console.log(`Indicators direct check: symbol=${indData.symbol}, EMA-13 last=${lastEma}`);

  // Verify timestamps are real (2026), not demo
  const timestamps = indData.data?.timestamps || [];
  expect(timestamps[timestamps.length - 1]).toContain("2026");

  // ── Now test the frontend ───────────────────────────────

  // Reset broker again right before frontend load
  await request.post("http://localhost:8000/api/charts/reset-broker").catch(() => {});

  await page.goto("/");

  // Wait for dashboard
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({ timeout: 30000 });
  const dashText = await page.textContent("body");
  expect(dashText).toContain("NIFTY");
  await page.screenshot({ path: "e2e/proof-nifty-01-dashboard.png", fullPage: true });
  console.log("Dashboard: NIFTY visible");

  // Navigate to Charts
  await page.locator('button[title="Charts"]').click();

  // Wait for either canvas OR "No data" message (to know the page settled)
  const canvasOrNoData = await Promise.race([
    page.locator("canvas").first().waitFor({ state: "visible", timeout: 45000 }).then(() => "canvas"),
    page.getByText("No data").waitFor({ state: "visible", timeout: 45000 }).then(() => "nodata"),
  ]).catch(() => "timeout");

  console.log(`Charts view result: ${canvasOrNoData}`);

  if (canvasOrNoData === "canvas") {
    // Chart loaded! Verify it's showing
    await page.waitForTimeout(2000);

    const canvas = page.locator("canvas").first();
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(200);
    expect(box!.height).toBeGreaterThan(100);
    console.log(`Chart canvas: ${box!.width}x${box!.height}`);

    // Verify NIFTY:NFO visible
    await expect(page.getByText("NIFTY").first()).toBeVisible({ timeout: 3000 });
    const chartsText = await page.textContent("body");
    expect(chartsText).toContain("NFO");

    await page.screenshot({ path: "e2e/proof-nifty-02-charts.png", fullPage: true });
    await canvas.screenshot({ path: "e2e/proof-nifty-03-chart-canvas.png" });
    console.log("Charts: NIFTY chart rendered with canvas");

    // Try Three Screen
    const threeScreenBtn = page.locator("button", { hasText: "Three Screen" });
    if (await threeScreenBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await threeScreenBtn.click();
      // Wait for all 3 screens to show "bars" text (each screen shows "N bars" when loaded)
      // Stagger is 0/3/6s + data fetch time per screen
      await expect(async () => {
        const barsTexts = await page.locator("text=/\\d+ bars/").count();
        expect(barsTexts).toBeGreaterThanOrEqual(3);
      }).toPass({ timeout: 60000 });
      await page.waitForTimeout(2000); // Let subcharts finish rendering
      const canvasCount = await page.locator("canvas").count();
      console.log(`Three Screen: ${canvasCount} canvases`);
      await page.screenshot({ path: "e2e/proof-nifty-04-three-screen.png", fullPage: true });
    }
  } else {
    // "No data" shown — take screenshot, then reload and retry
    await page.screenshot({ path: "e2e/proof-nifty-02-nodata.png", fullPage: true });
    console.log("First load got 'No data' — retrying with fresh page...");

    // Reset and reload
    await request.post("http://localhost:8000/api/charts/reset-broker").catch(() => {});
    await page.waitForTimeout(2000);
    await page.reload();

    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({ timeout: 30000 });
    await page.locator('button[title="Charts"]').click();

    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible({ timeout: 45000 });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: "e2e/proof-nifty-02-charts-retry.png", fullPage: true });
    console.log("Charts loaded on retry");
  }

  console.log("NIFTY verification complete");
});
