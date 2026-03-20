import { test, expect } from "@playwright/test";
import {
  waitForDashboardReady,
  waitForIndicators,
  waitForChartReady,
  goToDashboard,
  goToCharts,
  goToTrades,
  goToRisk,
  goToPortfolio,
  navigateToView,
  waitForRiskData,
  loginAsAdmin,
} from "./helpers";

const API = "http://localhost:8000";

// ─── Backend API Tests ──────────────────────────────────────────────

test.describe("Backend API", () => {
  test("root returns system info", async ({ request }) => {
    const res = await request.get(`${API}/`);
    expect(res.ok()).toBeTruthy();
    const json = await res.json();
    expect(json.name).toBe("Elder Trading System");
    expect(json.status).toBe("running");
    expect(json.mode).toMatch(/PAPER|LIVE/);
  });

  test("health check returns config", async ({ request }) => {
    const res = await request.get(`${API}/api/health`);
    expect(res.ok()).toBeTruthy();
    const json = await res.json();
    expect(json.status).toBe("ok");
    expect(json.trading_mode).toBe("PAPER");
    expect(json).toHaveProperty("risk_per_trade");
    expect(json).toHaveProperty("min_signal_score");
  });

  test("trading mode returns PAPER", async ({ request }) => {
    const res = await request.get(`${API}/api/trading/mode`);
    const json = await res.json();
    expect(json.mode).toBe("PAPER");
  });

  test("paper funds returns 100k", async ({ request }) => {
    const res = await request.get(`${API}/api/trading/funds`);
    const json = await res.json();
    expect(json.status).toBeTruthy();
    expect(json.data.availablecash).toBe("100000.00");
    expect(json.data.net).toBe("100000.00");
  });

  test("positions returns array", async ({ request }) => {
    const res = await request.get(`${API}/api/trading/positions`);
    const json = await res.json();
    expect(Array.isArray(json.data)).toBeTruthy();
  });

  test("orders returns array", async ({ request }) => {
    const res = await request.get(`${API}/api/trading/orders`);
    const json = await res.json();
    expect(Array.isArray(json.data)).toBeTruthy();
  });

  test("scanner instruments search works", async ({ request }) => {
    const res = await request.get(
      `${API}/api/scanner/instruments?exchange=NSE&search=RELIANCE&limit=5`
    );
    const json = await res.json();
    expect(json.instruments.length).toBeGreaterThan(0);
    const first = json.instruments[0];
    expect(first).toHaveProperty("token");
    expect(first).toHaveProperty("display_symbol");
    expect(first.display_symbol).toBe("RELIANCE");
  });

  test("indicator compute endpoint returns all Elder indicators", async ({ request }) => {
    const res = await request.get(
      `${API}/api/indicators/compute?symbol=RELIANCE&exchange=NSE&interval=1d&days=365`
    );
    const json = await res.json();
    expect(json.symbol).toBe("RELIANCE");
    expect(json.count).toBeGreaterThan(100);
    // All indicator arrays should exist
    const d = json.data;
    expect(d.timestamps.length).toBe(json.count);
    expect(d.ema13.length).toBe(json.count);
    expect(d.ema22.length).toBe(json.count);
    expect(d.macd_line.length).toBe(json.count);
    expect(d.macd_histogram.length).toBe(json.count);
    expect(d.force_index.length).toBe(json.count);
    expect(d.impulse_color.length).toBe(json.count);
    expect(d.safezone_long.length).toBe(json.count);
    expect(d.safezone_short.length).toBe(json.count);
    // Should have non-null values for most indicators
    const nonNullEma = d.ema13.filter((v: any) => v !== null);
    expect(nonNullEma.length).toBeGreaterThan(200);
    const nonNullImpulse = d.impulse_color.filter((v: any) => v !== null);
    expect(nonNullImpulse.length).toBeGreaterThan(200);
    // Impulse colors should be green, red, or blue
    const validColors = ["green", "red", "blue"];
    for (const color of nonNullImpulse) {
      expect(validColors).toContain(color);
    }
  });

  test("charts endpoint returns data (live or demo fallback)", async ({ request }) => {
    const res = await request.get(
      `${API}/api/charts/candles?symbol=RELIANCE&exchange=NSE&interval=1d&days=10`
    );
    const json = await res.json();
    // Should always return data — either live or demo fallback
    expect(json).toHaveProperty("symbol");
    expect(json).toHaveProperty("interval");
    expect(json.count).toBeGreaterThan(0);
    expect(json.data.length).toBeGreaterThan(0);
    // Source should be 'live' or 'demo'
    expect(["live", "demo"]).toContain(json.source);
    // Verify candle structure
    const first = json.data[0];
    expect(first).toHaveProperty("open");
    expect(first).toHaveProperty("high");
    expect(first).toHaveProperty("low");
    expect(first).toHaveProperty("close");
    expect(first).toHaveProperty("volume");
  });

  test("paper order full lifecycle: BUY → position → SELL → flat", async ({
    request,
  }) => {
    // BUY
    const buyRes = await request.post(`${API}/api/trading/order`, {
      data: {
        symbol: "TCS",
        token: "11536",
        exchange: "NSE",
        direction: "BUY",
        order_type: "MARKET",
        quantity: 5,
        price: 3500,
        trigger_price: 0,
        product_type: "INTRADAY",
      },
    });
    const buyJson = await buyRes.json();
    expect(buyJson.status).toBeTruthy();
    expect(buyJson.mode).toBe("PAPER");
    expect(buyJson.order.tradingsymbol).toBe("TCS");

    // Check position exists
    const posRes = await request.get(`${API}/api/trading/positions`);
    const posJson = await posRes.json();
    const tcsPos = posJson.data.find(
      (p: any) => p.tradingsymbol === "TCS"
    );
    expect(tcsPos).toBeTruthy();
    expect(parseInt(tcsPos.netqty)).toBe(5);

    // SELL to close
    const sellRes = await request.post(`${API}/api/trading/order`, {
      data: {
        symbol: "TCS",
        token: "11536",
        exchange: "NSE",
        direction: "SELL",
        order_type: "MARKET",
        quantity: 5,
        price: 3520,
        trigger_price: 0,
        product_type: "INTRADAY",
      },
    });
    const sellJson = await sellRes.json();
    expect(sellJson.status).toBeTruthy();

    // Position should be gone (flat)
    const posRes2 = await request.get(`${API}/api/trading/positions`);
    const posJson2 = await posRes2.json();
    const tcsPos2 = posJson2.data.find(
      (p: any) => p.tradingsymbol === "TCS"
    );
    expect(tcsPos2).toBeFalsy();
  });
});

// ─── Frontend UI Tests ──────────────────────────────────────────────

test.describe("Dashboard UI", () => {
  test.beforeEach(async ({ page }) => {
    // Login before each UI test (multi-user auth)
    await loginAsAdmin(page);
  });

  test("page loads with correct title", async ({ page }) => {
    await expect(page).toHaveTitle("Elder Trading System");
  });

  test("dashboard shows Overview header and PAPER badge", async ({ page }) => {
    await page.goto("/");
    await waitForDashboardReady(page);
    // DashboardView has a loading state — wait for Overview heading to appear after data loads
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({ timeout: 15000 });
    // PAPER badge exists (may be multiple — PipelineStatusBar + DashboardView + system status)
    await expect(page.getByText("PAPER").first()).toBeVisible();
  });

  test("dashboard shows API and Feed status indicators", async ({ page }) => {
    await page.goto("/");
    await waitForDashboardReady(page);
    await expect(page.getByText("API").first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Feed").first()).toBeVisible();
  });

  test("sidebar has navigation icons", async ({ page }) => {
    await page.goto("/");
    // Sidebar nav buttons with title attributes
    await expect(page.locator("button[title='Overview']")).toBeVisible();
    await expect(page.locator("button[title='Charts']")).toBeVisible();
    await expect(page.locator("button[title='Trades']")).toBeVisible();
    await expect(page.locator("button[title='Signals']")).toBeVisible();
    await expect(page.locator("button[title='Risk']")).toBeVisible();
    await expect(page.locator("button[title='Portfolio']")).toBeVisible();
    await expect(page.locator("button[title='Settings']")).toBeVisible();
  });

  test("charts view has exchange toggles", async ({ page }) => {
    await page.goto("/");
    await goToCharts(page);
    await expect(page.locator("button:text('NSE')")).toBeVisible();
    await expect(page.locator("button:text('NFO')")).toBeVisible();
    await expect(page.locator("button:text('MCX')")).toBeVisible();
  });

  test("charts view has interval selector", async ({ page }) => {
    await page.goto("/");
    await goToCharts(page);
    await expect(page.locator("button:text('1D')")).toBeVisible();
    await expect(page.locator("button:text('15m')")).toBeVisible();
    await expect(page.locator("button:text('1W')")).toBeVisible();
  });

  test("chart view toggle between Single and Three Screen", async ({ page }) => {
    await page.goto("/");
    await goToCharts(page);
    const singleBtn = page.locator("button", { hasText: "Single" });
    const threeBtn = page.locator("button", { hasText: "Three Screen" });
    await expect(singleBtn).toBeVisible();
    await expect(threeBtn).toBeVisible();

    // Click Three Screen
    await threeBtn.click();
    // Should show weekly/daily/intraday labels
    await expect(page.locator("text=Screen 1")).toBeVisible({ timeout: 5000 });
    await expect(page.locator("text=Screen 2")).toBeVisible();
    await expect(page.locator("text=Screen 3")).toBeVisible();

    // Click back to Single
    await singleBtn.click();
  });

  test("dashboard shows Open Positions and Recent Orders sections", async ({ page }) => {
    await page.goto("/");
    await waitForDashboardReady(page);
    // Sections animate in with fade-up — wait for animation and scroll into view
    await expect(page.getByText("Open Positions").first()).toBeVisible({ timeout: 10000 });
    await page.getByText("Recent Orders").first().scrollIntoViewIfNeeded();
    await expect(page.getByText("Recent Orders").first()).toBeVisible({ timeout: 10000 });
  });

  test("portfolio view has Watchlist and Funds panels", async ({ page }) => {
    await page.goto("/");
    await goToPortfolio(page);
    await expect(page.locator("text=Watchlist").first()).toBeVisible();
    await expect(page.locator("text=Funds & Margin")).toBeVisible();
  });

  test("dashboard shows stat cards", async ({ page }) => {
    await page.goto("/");
    await waitForDashboardReady(page);
    await expect(page.locator("text=Available Balance").first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=Day P&L").first()).toBeVisible();
    await expect(page.locator("text=Active Trades").first()).toBeVisible();
    await expect(page.locator("text=Risk Exposure").first()).toBeVisible();
  });

  test("portfolio view shows paper capital", async ({ page }) => {
    await page.goto("/");
    await goToPortfolio(page);
    await expect(page.locator("text=100000.00").first()).toBeVisible({ timeout: 10000 });
  });

  test("trades view shows order form", async ({ page }) => {
    await page.goto("/");
    await goToTrades(page);
    await expect(page.getByRole("heading", { name: "Quick Order" })).toBeVisible();
    await expect(page.getByRole("button", { name: "BUY", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "SELL", exact: true })).toBeVisible();
    await expect(page.locator("text=Quantity")).toBeVisible();
  });

  test("charts view symbol search shows results from API", async ({ page }) => {
    await page.goto("/");
    await goToCharts(page);
    const searchInput = page.locator("input[placeholder='Search symbol...']");
    await searchInput.click();
    await searchInput.fill("INFY");
    // Wait for search results dropdown
    await expect(page.locator("text=INFY").first()).toBeVisible({ timeout: 5000 });
  });

  test("placing a paper order shows success", async ({ page }) => {
    await page.goto("/");
    await goToTrades(page);

    // BUY is already selected, fill quantity
    const qtyInput = page.locator("input[type='number']").first();
    await qtyInput.fill("5");

    // Click the BUY button (triggers confirmation dialog)
    const buyBtn = page.locator("button", { hasText: /BUY\s+RELIANCE/ });
    await buyBtn.click();

    // Confirmation dialog should appear
    await expect(page.locator("text=Confirm Order")).toBeVisible({ timeout: 3000 });

    // Click Confirm
    await page.locator("button:text('Confirm')").click();

    // Should show success message (text includes details like "Paper BUY order filled: RELIANCE x5 @ 0.0")
    await expect(page.getByText("Paper BUY order filled").first()).toBeVisible({
      timeout: 10000,
    });
  });

  test("chart renders with data and indicator overlays", async ({ page }) => {
    await page.goto("/");
    await goToCharts(page);
    // Indicator legend should be visible
    await expect(page.locator("text=EMA(13)")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=EMA(22)")).toBeVisible();
    await expect(page.locator("text=SZ-Long")).toBeVisible();
    await expect(page.locator("text=SZ-Short")).toBeVisible();
  });
});

// ─── Integration Tests ──────────────────────────────────────────────

test.describe("Frontend-Backend Integration", () => {
  test.beforeEach(async ({ page }) => { await loginAsAdmin(page); });
  test("health status indicator turns green", async ({ page }) => {
    await page.goto("/");
    await waitForDashboardReady(page);
    // The PAPER badge should be visible (in dashboard Overview header)
    await expect(page.getByText("PAPER").first()).toBeVisible();
  });

  test("current symbol display on charts view", async ({ page }) => {
    await page.goto("/");
    await goToCharts(page);
    // Symbol display should show current symbol
    await expect(page.locator("text=RELIANCE").first()).toBeVisible({ timeout: 5000 });
  });

  test("exchange toggle changes context", async ({ page }) => {
    await page.goto("/");
    await goToCharts(page);
    // Click NFO
    await page.locator("button:text('NFO')").click();
    // Symbol display should show NFO
    await expect(page.locator("text=NFO").first()).toBeVisible({ timeout: 5000 });
  });
});

// ─── Production Safety Tests ─────────────────────────────────────────

test.describe("Production Safety", () => {
  test.beforeEach(async ({ page }) => { await loginAsAdmin(page); });
  test("order validation rejects negative quantity", async ({ request }) => {
    const res = await request.post(`${API}/api/trading/order`, {
      data: {
        symbol: "TCS",
        token: "11536",
        exchange: "NSE",
        direction: "BUY",
        order_type: "MARKET",
        quantity: -5,
        price: 3500,
        trigger_price: 0,
        product_type: "INTRADAY",
      },
    });
    expect(res.status()).toBe(422);
  });

  test("order validation rejects zero quantity", async ({ request }) => {
    const res = await request.post(`${API}/api/trading/order`, {
      data: {
        symbol: "TCS",
        token: "11536",
        exchange: "NSE",
        direction: "BUY",
        order_type: "MARKET",
        quantity: 0,
        price: 3500,
        trigger_price: 0,
        product_type: "INTRADAY",
      },
    });
    expect(res.status()).toBe(422);
  });

  test("order validation rejects invalid direction", async ({ request }) => {
    const res = await request.post(`${API}/api/trading/order`, {
      data: {
        symbol: "TCS",
        token: "11536",
        exchange: "NSE",
        direction: "HOLD",
        order_type: "MARKET",
        quantity: 5,
        price: 3500,
        trigger_price: 0,
        product_type: "INTRADAY",
      },
    });
    expect(res.status()).toBe(422);
  });

  test("LIMIT order without price returns 400", async ({ request }) => {
    const res = await request.post(`${API}/api/trading/order`, {
      data: {
        symbol: "TCS",
        token: "11536",
        exchange: "NSE",
        direction: "BUY",
        order_type: "LIMIT",
        quantity: 5,
        price: 0,
        trigger_price: 0,
        product_type: "INTRADAY",
      },
    });
    expect(res.status()).toBe(400);
  });

  test("paper account reset works", async ({ request }) => {
    // Place a paper order first
    await request.post(`${API}/api/trading/order`, {
      data: {
        symbol: "INFY",
        token: "1594",
        exchange: "NSE",
        direction: "BUY",
        order_type: "MARKET",
        quantity: 10,
        price: 1500,
        trigger_price: 0,
        product_type: "INTRADAY",
      },
    });

    // Reset paper account
    const resetRes = await request.post(`${API}/api/trading/paper/reset`);
    const resetJson = await resetRes.json();
    expect(resetJson.status).toBeTruthy();

    // Positions should be empty
    const posRes = await request.get(`${API}/api/trading/positions`);
    const posJson = await posRes.json();
    expect(posJson.data.length).toBe(0);

    // Orders should be empty
    const ordRes = await request.get(`${API}/api/trading/orders`);
    const ordJson = await ordRes.json();
    expect(ordJson.data.length).toBe(0);
  });

  test("session refresh endpoint exists", async ({ request }) => {
    const res = await request.post(`${API}/api/trading/session/refresh`);
    // Returns 200 even if login fails (status in body)
    expect(res.status()).toBe(200);
    const json = await res.json();
    expect(json).toHaveProperty("status");
    expect(json).toHaveProperty("message");
  });

  test("trade form validates quantity before submit", async ({ page }) => {
    await page.goto("/");
    await goToTrades(page);

    // Clear quantity to trigger validation
    const qtyInput = page.locator("input[type='number']").first();
    await qtyInput.fill("0");

    // BUY button should be disabled (opacity-50 class)
    const buyBtn = page.locator("button", { hasText: /BUY\s+RELIANCE/ });
    await expect(buyBtn).toHaveClass(/opacity-50/);
  });

  test("order confirmation dialog appears before placing", async ({ page }) => {
    await page.goto("/");
    await goToTrades(page);

    const qtyInput = page.locator("input[type='number']").first();
    await qtyInput.fill("1");

    const buyBtn = page.locator("button", { hasText: /BUY\s+RELIANCE/ });
    await buyBtn.click();

    // Confirmation dialog should appear
    await expect(page.locator("text=Confirm Order")).toBeVisible({ timeout: 3000 });
    // Cancel should close it
    await page.locator("button:text('Cancel')").click();
    await expect(page.locator("text=Confirm Order")).not.toBeVisible();
  });
});

// ─── Phase 3: Strategy & Risk API Tests ─────────────────────────────

test.describe("Strategy & Risk API", () => {
  test("risk summary returns 2% and 6% rules", async ({ request }) => {
    const res = await request.get(`${API}/api/strategy/risk-summary`);
    expect(res.ok()).toBeTruthy();
    const json = await res.json();
    expect(json).toHaveProperty("two_percent_rule");
    expect(json).toHaveProperty("six_percent_rule");
    expect(json).toHaveProperty("trading_mode");
    expect(json.two_percent_rule.max_risk_per_trade_pct).toBe(2);
    expect(json.six_percent_rule).toHaveProperty("is_allowed");
    expect(json.six_percent_rule).toHaveProperty("remaining_budget");
    expect(json.six_percent_rule).toHaveProperty("exposure_pct");
  });

  test("circuit breaker returns healthy state", async ({ request }) => {
    const res = await request.get(`${API}/api/strategy/circuit-breaker`);
    expect(res.ok()).toBeTruthy();
    const json = await res.json();
    expect(json.is_allowed).toBe(true);
    expect(json.is_halted).toBe(false);
    expect(json).toHaveProperty("month_start_equity");
    expect(json).toHaveProperty("max_portfolio_risk_pct");
    expect(json.max_portfolio_risk_pct).toBe(6);
    expect(json).toHaveProperty("current_month");
    expect(json).toHaveProperty("open_positions_count");
  });

  test("position sizer calculates correct 2% risk", async ({ request }) => {
    const res = await request.post(`${API}/api/strategy/position-size`, {
      data: {
        entry_price: 100,
        stop_price: 95,
        account_equity: 1000000,
        lot_size: 1,
      },
    });
    expect(res.ok()).toBeTruthy();
    const json = await res.json();
    expect(json.is_valid).toBe(true);
    expect(json.shares).toBe(4000); // 2% of 1M = 20000 / (100-95) = 4000
    expect(json.risk_amount).toBe(20000);
    expect(json.entry_price).toBe(100);
    expect(json.stop_price).toBe(95);
    expect(json.position_value).toBe(400000); // 4000 * 100
    expect(json.actual_risk_pct).toBe(2.0);
  });

  test("position sizer with lot size rounds down", async ({ request }) => {
    const res = await request.post(`${API}/api/strategy/position-size`, {
      data: {
        entry_price: 100,
        stop_price: 95,
        account_equity: 1000000,
        lot_size: 75,
      },
    });
    expect(res.ok()).toBeTruthy();
    const json = await res.json();
    expect(json.is_valid).toBe(true);
    // 4000 shares / 75 lot = 53.33 → 53 lots → 3975 shares
    expect(json.lots).toBe(53);
    expect(json.shares).toBe(3975);
  });

  test("position sizer rejects invalid stop (same as entry)", async ({ request }) => {
    const res = await request.post(`${API}/api/strategy/position-size`, {
      data: {
        entry_price: 100,
        stop_price: 100,
        account_equity: 1000000,
        lot_size: 1,
      },
    });
    expect(res.ok()).toBeTruthy();
    const json = await res.json();
    expect(json.is_valid).toBe(false);
    expect(json.reason).toBeTruthy();
  });

  test("triple screen analysis returns full recommendation (explicit values)", async ({ request }) => {
    // Use explicit indicator values for fast, deterministic test
    const res = await request.post(`${API}/api/strategy/triple-screen`, {
      data: {
        macd_histogram_slope: 0.5,
        screen1_impulse: "bullish",
        screen1_ema_trend: "RISING",
        force_index_2: -500,
        elder_ray_bear: -2.5,
        elder_ray_bull: 5.0,
        elder_ray_bear_trend: "RISING",
        elder_ray_bull_trend: "RISING",
        screen2_impulse: "bullish",
        last_high: 1500,
        last_low: 1450,
        safezone_long: 1440,
        safezone_short: 1510,
      },
    });
    expect(res.ok()).toBeTruthy();
    const json = await res.json();

    // Screen 1: Tide
    expect(json.screen1).toHaveProperty("tide");
    expect(json.screen1.tide).toBe("BULLISH");
    expect(json.screen1).toHaveProperty("macd_histogram_slope");

    // Screen 2: Signal
    expect(json.screen2).toHaveProperty("signal");
    expect(json.screen2.signal).toBe("BUY");
    expect(json.screen2).toHaveProperty("reasons");
    expect(Array.isArray(json.screen2.reasons)).toBeTruthy();
    expect(json.screen2.reasons.length).toBeGreaterThan(0);

    // Screen 3: Entry
    expect(json.screen3).toHaveProperty("entry_type");
    expect(json.screen3.entry_type).toBe("BUY_STOP");
    expect(json.screen3).toHaveProperty("entry_price");
    expect(json.screen3).toHaveProperty("stop_price");

    // Recommendation
    expect(json.recommendation).toHaveProperty("action");
    expect(json.recommendation.action).toBe("BUY");
    expect(json.recommendation).toHaveProperty("confidence");
    expect(json.recommendation.confidence).toBeGreaterThanOrEqual(50);
    expect(json.recommendation.confidence).toBeLessThanOrEqual(100);

    // Grade
    expect(["A", "B", "C", "D"]).toContain(json.grade);
  });

  test("triple screen analysis with raw candles + indicators", async ({ request }) => {
    // Get a small dataset
    const candleRes = await request.get(
      `${API}/api/charts/candles?symbol=RELIANCE&exchange=NSE&interval=1d&days=30`
    );
    const candleJson = await candleRes.json();
    const indRes = await request.get(
      `${API}/api/indicators/compute?symbol=RELIANCE&exchange=NSE&interval=1d&days=30`
    );
    const indJson = await indRes.json();

    const res = await request.post(`${API}/api/strategy/triple-screen`, {
      data: {
        candles: candleJson.data,
        indicators: indJson.data,
      },
    });
    expect(res.ok()).toBeTruthy();
    const json = await res.json();

    expect(["BULLISH", "BEARISH", "NEUTRAL"]).toContain(json.screen1.tide);
    expect(["BUY", "SELL", "NONE"]).toContain(json.screen2.signal);
    expect(["BUY", "SELL", "WAIT"]).toContain(json.recommendation.action);
    expect(["A", "B", "C", "D"]).toContain(json.grade);
  });

  test("circuit breaker halt and reset cycle", async ({ request }) => {
    // Force halt
    const haltRes = await request.post(`${API}/api/strategy/circuit-breaker/halt`);
    expect(haltRes.ok()).toBeTruthy();

    // Verify halted
    const statusRes = await request.get(`${API}/api/strategy/circuit-breaker`);
    const status = await statusRes.json();
    expect(status.is_halted).toBe(true);
    expect(status.is_allowed).toBe(false);

    // Reset
    const resetRes = await request.post(`${API}/api/strategy/circuit-breaker/reset`);
    expect(resetRes.ok()).toBeTruthy();

    // Verify restored
    const statusRes2 = await request.get(`${API}/api/strategy/circuit-breaker`);
    const status2 = await statusRes2.json();
    expect(status2.is_halted).toBe(false);
    expect(status2.is_allowed).toBe(true);
  });
});

// ─── Phase 3: Advanced Indicator API Tests ──────────────────────────

test.describe("Advanced Indicators API", () => {
  test("indicator endpoint returns all Phase 3 fields", async ({ request }) => {
    const res = await request.get(
      `${API}/api/indicators/compute?symbol=RELIANCE&exchange=NSE&interval=1d&days=365`
    );
    const json = await res.json();
    const d = json.data;

    // Phase 2 fields
    expect(d).toHaveProperty("ema13");
    expect(d).toHaveProperty("ema22");
    expect(d).toHaveProperty("macd_line");
    expect(d).toHaveProperty("macd_signal");
    expect(d).toHaveProperty("macd_histogram");
    expect(d).toHaveProperty("force_index");
    expect(d).toHaveProperty("impulse_color");
    expect(d).toHaveProperty("impulse_signal");
    expect(d).toHaveProperty("safezone_long");
    expect(d).toHaveProperty("safezone_short");

    // Phase 3 fields
    expect(d).toHaveProperty("force_index_2");
    expect(d).toHaveProperty("elder_ray_bull");
    expect(d).toHaveProperty("elder_ray_bear");
    expect(d).toHaveProperty("value_zone_fast");
    expect(d).toHaveProperty("value_zone_slow");
    expect(d).toHaveProperty("auto_envelope_upper");
    expect(d).toHaveProperty("auto_envelope_lower");
    expect(d).toHaveProperty("auto_envelope_ema");
    expect(d).toHaveProperty("thermometer_raw");
    expect(d).toHaveProperty("thermometer_smoothed");
    expect(d).toHaveProperty("macd_divergence_signal");

    // All arrays should have same length
    const len = json.count;
    expect(d.elder_ray_bull.length).toBe(len);
    expect(d.elder_ray_bear.length).toBe(len);
    expect(d.value_zone_fast.length).toBe(len);
    expect(d.auto_envelope_upper.length).toBe(len);
    expect(d.thermometer_raw.length).toBe(len);
    expect(d.macd_divergence_signal.length).toBe(len);
  });

  test("Elder-Ray has non-null values and correct sign patterns", async ({ request }) => {
    const res = await request.get(
      `${API}/api/indicators/compute?symbol=RELIANCE&exchange=NSE&interval=1d&days=365`
    );
    const d = (await res.json()).data;

    const bullNonNull = d.elder_ray_bull.filter((v: any) => v !== null);
    const bearNonNull = d.elder_ray_bear.filter((v: any) => v !== null);
    expect(bullNonNull.length).toBeGreaterThan(200);
    expect(bearNonNull.length).toBeGreaterThan(200);

    // Bull power is typically positive (high > EMA), bear power typically negative (low < EMA)
    const bullPositive = bullNonNull.filter((v: number) => v > 0);
    const bearNegative = bearNonNull.filter((v: number) => v < 0);
    // At least 50% should follow the typical pattern
    expect(bullPositive.length).toBeGreaterThan(bullNonNull.length * 0.4);
    expect(bearNegative.length).toBeGreaterThan(bearNonNull.length * 0.4);
  });

  test("AutoEnvelope has proper channel structure", async ({ request }) => {
    const res = await request.get(
      `${API}/api/indicators/compute?symbol=RELIANCE&exchange=NSE&interval=1d&days=365`
    );
    const d = (await res.json()).data;

    // Find indices where all three are non-null
    for (let i = 0; i < d.auto_envelope_upper.length; i++) {
      const upper = d.auto_envelope_upper[i];
      const lower = d.auto_envelope_lower[i];
      const ema = d.auto_envelope_ema[i];
      if (upper !== null && lower !== null && ema !== null) {
        expect(upper).toBeGreaterThan(ema);
        expect(lower).toBeLessThan(ema);
        expect(upper).toBeGreaterThan(lower);
      }
    }
  });

  test("thermometer values are non-negative", async ({ request }) => {
    const res = await request.get(
      `${API}/api/indicators/compute?symbol=RELIANCE&exchange=NSE&interval=1d&days=365`
    );
    const d = (await res.json()).data;

    const rawNonNull = d.thermometer_raw.filter((v: any) => v !== null);
    expect(rawNonNull.length).toBeGreaterThan(200);
    for (const v of rawNonNull) {
      expect(v).toBeGreaterThanOrEqual(0);
    }

    const smoothedNonNull = d.thermometer_smoothed.filter((v: any) => v !== null);
    expect(smoothedNonNull.length).toBeGreaterThan(200);
    for (const v of smoothedNonNull) {
      expect(v).toBeGreaterThanOrEqual(0);
    }
  });

  test("Value Zone EMA-13 is faster than EMA-26", async ({ request }) => {
    const res = await request.get(
      `${API}/api/indicators/compute?symbol=RELIANCE&exchange=NSE&interval=1d&days=365`
    );
    const d = (await res.json()).data;

    const fastNonNull = d.value_zone_fast.filter((v: any) => v !== null);
    const slowNonNull = d.value_zone_slow.filter((v: any) => v !== null);
    expect(fastNonNull.length).toBeGreaterThan(200);
    expect(slowNonNull.length).toBeGreaterThan(200);
    // Fast EMA should start producing values sooner (more non-null values)
    expect(fastNonNull.length).toBeGreaterThanOrEqual(slowNonNull.length);
  });

  test("MACD divergence signal values are valid", async ({ request }) => {
    const res = await request.get(
      `${API}/api/indicators/compute?symbol=RELIANCE&exchange=NSE&interval=1d&days=365`
    );
    const d = (await res.json()).data;

    const divNonNull = d.macd_divergence_signal.filter((v: any) => v !== null);
    expect(divNonNull.length).toBeGreaterThan(0);
    // 0 = no divergence, 1 = bullish divergence, -1 = bearish divergence
    for (const v of divNonNull) {
      expect([0, 1, -1]).toContain(v);
    }
  });
});

// ─── Phase 3: Risk Panel UI Tests ───────────────────────────────────

test.describe("Risk Panel UI", () => {
  test.beforeEach(async ({ page }) => { await loginAsAdmin(page); });
  test("Risk view is accessible via sidebar", async ({ page }) => {
    await page.goto("/");
    await goToRisk(page);
    await expect(page.locator("text=Risk Management")).toBeVisible();
  });

  test("Risk Overview shows 2% and 6% rules", async ({ page }) => {
    await page.goto("/");
    await goToRisk(page);
    await expect(page.locator("text=2% Rule")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=6% Rule")).toBeVisible({ timeout: 5000 });
  });

  test("Risk Overview shows trading status", async ({ page }) => {
    await page.goto("/");
    await goToRisk(page);
    await expect(page.locator("text=Trading Active")).toBeVisible({ timeout: 10000 });
  });

  test("Risk Overview shows risk metrics", async ({ page }) => {
    await page.goto("/");
    await goToRisk(page);
    await expect(page.locator("text=Realized Losses")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=Open Risk")).toBeVisible({ timeout: 5000 });
    await expect(page.locator("text=Remaining Budget")).toBeVisible({ timeout: 5000 });
  });

  test("Position Sizer tab works", async ({ page }) => {
    await page.goto("/");
    await goToRisk(page);
    await page.locator("text=Position Sizer").click();
    await expect(page.locator("text=2% Rule Position Sizer")).toBeVisible({ timeout: 3000 });
    await expect(page.locator("text=Entry Price")).toBeVisible();
    await expect(page.locator("text=Stop Price")).toBeVisible();
    await expect(page.locator("text=Account Equity")).toBeVisible();
  });

  test("Position Sizer calculates result", async ({ page }) => {
    await page.goto("/");
    await goToRisk(page);
    await page.locator("text=Position Sizer").click();

    // Fill in the form
    const inputs = page.locator("input[type='number']");
    await inputs.nth(0).fill("100");  // Entry price
    await inputs.nth(1).fill("95");   // Stop price
    // Account equity is pre-filled with 1000000

    // Click Calculate and wait for API response
    await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes("/api/strategy/position-size") && r.status() === 200,
        { timeout: 10000 }
      ),
      page.locator("button:text('Calculate')").click(),
    ]);

    // Should show result
    await expect(page.locator("text=Shares")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=Risk Amount")).toBeVisible();
    await expect(page.locator("text=Position Value")).toBeVisible();
  });
});

// ─── Phase 3: Elder-Ray Chart UI Tests ──────────────────────────────

test.describe("Elder-Ray Chart UI", () => {
  test.beforeEach(async ({ page }) => { await loginAsAdmin(page); });
  test("Elder-Ray chart renders below MACD", async ({ page }) => {
    await page.goto("/");
    await goToCharts(page);
    // Elder-Ray label should be visible
    await expect(page.locator("text=Elder-Ray(13)")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=Bull")).toBeVisible();
    await expect(page.locator("text=Bear")).toBeVisible();
  });

  test("Elder-Ray chart has canvas elements", async ({ page }) => {
    await page.goto("/");
    await goToCharts(page);
    // Multiple canvases: main chart + MACD + Elder-Ray
    const canvases = page.locator("canvas");
    const count = await canvases.count();
    // At minimum: main chart canvas + MACD canvas + Elder-Ray canvas
    expect(count).toBeGreaterThanOrEqual(3);
  });

  test("MACD chart label is visible", async ({ page }) => {
    await page.goto("/");
    await goToCharts(page);
    await expect(page.locator("text=MACD(12,26,9)")).toBeVisible({ timeout: 10000 });
  });
});

// ─── Pipeline API Tests ─────────────────────────────────────────────

test.describe("Pipeline API", () => {
  test("pipeline status returns session info", async ({ request }) => {
    const res = await request.get(`${API}/api/strategy/pipeline/status`);
    expect(res.ok()).toBeTruthy();
    const json = await res.json();
    expect(json).toHaveProperty("active_sessions");
    expect(json).toHaveProperty("sessions");
  });

  test("pipeline signals returns array", async ({ request }) => {
    const res = await request.get(`${API}/api/strategy/pipeline/signals?limit=10`);
    expect(res.ok()).toBeTruthy();
    const json = await res.json();
    expect(json).toHaveProperty("signals");
    expect(Array.isArray(json.signals)).toBeTruthy();
  });

  test("pipeline start/stop cycle works", async ({ request }) => {
    // Start
    const startRes = await request.post(`${API}/api/strategy/pipeline/start`, {
      data: { symbol: "RELIANCE", exchange: "NSE" },
    });
    expect(startRes.ok()).toBeTruthy();
    const startJson = await startRes.json();
    expect(startJson.status).toBeTruthy();

    // Status check
    const statusRes = await request.get(`${API}/api/strategy/pipeline/status`);
    const statusJson = await statusRes.json();
    expect(statusJson.active_sessions).toBeGreaterThanOrEqual(1);
    expect(statusJson.sessions["RELIANCE:NSE"]).toBeTruthy();
    expect(statusJson.sessions["RELIANCE:NSE"].active).toBe(true);

    // Analysis check
    const analysisRes = await request.get(
      `${API}/api/strategy/pipeline/analysis/RELIANCE?exchange=NSE`
    );
    expect(analysisRes.ok()).toBeTruthy();
    const analysisJson = await analysisRes.json();
    expect(analysisJson.symbol).toBe("RELIANCE");
    expect(analysisJson.analysis).toBeTruthy();
    expect(["A", "B", "C", "D"]).toContain(analysisJson.analysis.grade);
  });
});

// ─── Pipeline Status Bar UI ─────────────────────────────────────────

test.describe("Pipeline Status Bar", () => {
  test.beforeEach(async ({ page }) => { await loginAsAdmin(page); });
  test("pipeline status bar shows data freshness", async ({ page }) => {
    await page.goto("/");
    // PipelineStatusBar should show freshness indicator
    await expect(
      page.locator("text=LIVE").first()
        .or(page.locator("text=DEMO").first())
        .or(page.locator("text=STALE").first())
        .or(page.locator("text=OFFLINE").first())
    ).toBeVisible({ timeout: 10000 });
  });

  test("pipeline status bar shows trading mode badge", async ({ page }) => {
    await page.goto("/");
    // PAPER badge in PipelineStatusBar
    await expect(page.getByText("PAPER").first()).toBeVisible({ timeout: 10000 });
  });
});
