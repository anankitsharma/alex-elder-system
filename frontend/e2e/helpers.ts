/**
 * E2E Test Helpers — Deterministic waits replacing hardcoded timeouts.
 *
 * Updated for sidebar-based multi-view layout.
 */

import { Page, expect } from "@playwright/test";

const API = "http://localhost:8000";

/**
 * Login as admin via the login form (or set token directly).
 * Must be called before any page navigation that requires auth.
 */
export async function loginAsAdmin(page: Page) {
  // Get JWT token via API
  const res = await page.request.post(`${API}/api/auth/login`, {
    form: { username: "admin", password: "admin123" },
  });
  if (!res.ok()) return;
  const data = await res.json();
  const token = data.access_token;

  // Navigate to page, set token, then reload so app picks it up
  await page.goto("/");
  await page.evaluate((t) => {
    localStorage.setItem("elder_token", t);
  }, token);
  await page.reload({ waitUntil: "networkidle" });

  // Wait for auth to resolve — either we see the dashboard or we're still on login
  // Give the React app a moment to read localStorage and call checkAuth
  await page.waitForTimeout(2000);
}

/**
 * Wait for the dashboard overview to be fully ready:
 * - Health check responded
 * - Dashboard data loaded (funds, positions, risk)
 */
export async function waitForDashboardReady(page: Page, timeout = 20000) {
  // Wait for at least health and one of the dashboard API calls
  await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/api/health") && r.status() === 200,
      { timeout }
    ),
    page.waitForResponse(
      (r) => r.url().includes("/api/trading/funds") && r.status() === 200,
      { timeout }
    ),
  ]);
  // Wait for the loading spinner to disappear and Overview heading to render
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({ timeout: 15000 });
}

/**
 * Wait for indicator data to load.
 */
export async function waitForIndicators(page: Page, timeout = 15000) {
  await page.waitForResponse(
    (r) => r.url().includes("/api/indicators/compute") && r.status() === 200,
    { timeout }
  );
}

/**
 * Wait for chart canvas to be rendered and visible.
 */
export async function waitForChartReady(page: Page, timeout = 20000) {
  const chartCanvas = page.locator("canvas").first();
  await expect(chartCanvas).toBeVisible({ timeout });
}

/**
 * Navigate to dashboard and wait for it to be interactive.
 */
export async function goToDashboard(page: Page) {
  // Login first (multi-user auth)
  await loginAsAdmin(page);
  await waitForDashboardReady(page);
}

/**
 * Navigate to a view using the sidebar icon buttons.
 * Views: Overview, Charts, Trades, Signals, Risk, Portfolio, Settings
 */
export async function navigateToView(
  page: Page,
  viewLabel: string,
  timeout = 10000
) {
  await page.locator(`button[title="${viewLabel}"]`).click();
  // Small wait for view transition
  await page.waitForTimeout(300);
}

/**
 * Navigate to Charts view and wait for chart to load.
 */
export async function goToCharts(page: Page) {
  await navigateToView(page, "Charts");
  // Wait for candle data to load
  await page.waitForResponse(
    (r) => r.url().includes("/api/charts/candles") && r.status() === 200,
    { timeout: 15000 }
  ).catch(() => {});
  // Wait for chart canvas
  await waitForChartReady(page);
}

/**
 * Navigate to Trades view and wait for content.
 */
export async function goToTrades(page: Page) {
  await navigateToView(page, "Trades");
  await expect(page.getByRole("heading", { name: "Quick Order" })).toBeVisible({ timeout: 5000 });
}

/**
 * Navigate to Risk view and wait for content.
 */
export async function goToRisk(page: Page) {
  await navigateToView(page, "Risk");
  await expect(page.locator("text=Risk Management")).toBeVisible({ timeout: 5000 });
}

/**
 * Navigate to Portfolio view and wait for content.
 */
export async function goToPortfolio(page: Page) {
  await navigateToView(page, "Portfolio");
  await expect(page.locator("text=Funds & Margin")).toBeVisible({ timeout: 5000 });
}

/**
 * Switch to a sidebar tab and wait for its content to load.
 * @deprecated Use navigateToView() for sidebar navigation
 */
export async function switchToTab(
  page: Page,
  tabName: string,
  waitForText?: string,
  timeout = 8000
) {
  // Try sidebar navigation first (new layout)
  const sidebarBtn = page.locator(`button[title="${tabName}"]`);
  if (await sidebarBtn.isVisible().catch(() => false)) {
    await sidebarBtn.click();
  } else {
    // Fallback to text-based button click
    await page.locator(`button:text('${tabName}')`).click();
  }
  if (waitForText) {
    await expect(page.locator(`text=${waitForText}`).first()).toBeVisible({ timeout });
  }
}

/**
 * Wait for the Risk panel API response.
 */
export async function waitForRiskData(page: Page, timeout = 10000) {
  await page.waitForResponse(
    (r) => r.url().includes("/api/strategy/risk-summary") && r.status() === 200,
    { timeout }
  );
}
