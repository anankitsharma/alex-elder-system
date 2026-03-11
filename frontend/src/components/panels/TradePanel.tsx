"use client";

import { useState } from "react";
import { Send, AlertTriangle, ShieldCheck, Zap } from "lucide-react";
import { placeOrder, type OrderRequest } from "@/lib/api";
import { useTradingStore } from "@/store/useTradingStore";
import { cn } from "@/lib/utils";

interface TradePanelProps {
  symbol: string;
  exchange: string;
}

export function TradePanel({ symbol, exchange }: TradePanelProps) {
  const token = useTradingStore((s) => s.token);
  const tradingMode = useTradingStore((s) => s.tradingMode);
  const activeSignal = useTradingStore((s) => s.activeSignal);
  const refreshPositions = useTradingStore((s) => s.refreshPositions);
  const refreshOrders = useTradingStore((s) => s.refreshOrders);

  const [direction, setDirection] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<"MARKET" | "LIMIT">("MARKET");
  const [quantity, setQuantity] = useState("1");
  const [price, setPrice] = useState("");
  const [productType, setProductType] = useState<"INTRADAY" | "DELIVERY">(
    "INTRADAY"
  );
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(
    null
  );
  const [confirmOpen, setConfirmOpen] = useState(false);

  const qty = parseInt(quantity) || 0;
  const prc = parseFloat(price) || 0;

  // Validation
  const errors: string[] = [];
  if (qty <= 0) errors.push("Quantity must be > 0");
  if (qty > 999999) errors.push("Quantity too large");
  if (orderType === "LIMIT" && prc <= 0) errors.push("Limit price required");
  const isValid = errors.length === 0;

  const fillFromSignal = () => {
    if (!activeSignal) return;
    setDirection(activeSignal.action === "SELL" ? "SELL" : "BUY");
    if (activeSignal.shares) setQuantity(String(activeSignal.shares));
    if (activeSignal.entry_price) {
      setPrice(activeSignal.entry_price.toFixed(2));
      setOrderType("LIMIT");
    }
    setConfirmOpen(false);
    setResult(null);
  };

  const handleSubmit = async () => {
    if (!isValid) return;

    // Show confirmation first
    if (!confirmOpen) {
      setConfirmOpen(true);
      return;
    }

    setConfirmOpen(false);
    setSubmitting(true);
    setResult(null);
    try {
      const order: OrderRequest = {
        symbol,
        token: token || symbol,
        exchange,
        direction,
        order_type: orderType,
        quantity: qty,
        price: prc,
        trigger_price: 0,
        product_type: productType,
      };
      const res = await placeOrder(order);
      setResult({
        ok: res.status !== false,
        msg: res.message || `Paper ${direction} order filled`,
      });
      // Refresh positions/orders after trade
      refreshPositions();
      refreshOrders();
    } catch (e: any) {
      setResult({ ok: false, msg: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* Header with mode badge */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold">Quick Order</h3>
        <span
          className={cn(
            "px-1.5 py-0.5 rounded text-[9px] font-bold tracking-wide",
            tradingMode === "LIVE"
              ? "bg-green-500/10 text-green-500 border border-green-500/20"
              : "bg-amber-500/10 text-amber-500 border border-amber-500/20"
          )}
        >
          {tradingMode}
        </span>
      </div>

      {/* Fill from signal button */}
      {activeSignal && activeSignal.action !== "WAIT" && (
        <button
          onClick={fillFromSignal}
          className="flex items-center justify-center gap-1 py-1.5 rounded text-[10px] font-medium bg-accent/10 text-accent border border-accent/20 hover:bg-accent/20 transition-colors"
        >
          <Zap className="w-3 h-3" />
          Fill from Signal: {activeSignal.action} {activeSignal.symbol} (Grade {activeSignal.grade})
        </button>
      )}

      {/* Direction */}
      <div className="grid grid-cols-2 gap-1">
        <button
          className={cn(
            "py-1.5 rounded text-xs font-semibold transition-colors",
            direction === "BUY"
              ? "bg-green text-white"
              : "bg-surface-2 text-muted hover:text-foreground border border-border"
          )}
          onClick={() => {
            setDirection("BUY");
            setConfirmOpen(false);
          }}
        >
          BUY
        </button>
        <button
          className={cn(
            "py-1.5 rounded text-xs font-semibold transition-colors",
            direction === "SELL"
              ? "bg-red text-white"
              : "bg-surface-2 text-muted hover:text-foreground border border-border"
          )}
          onClick={() => {
            setDirection("SELL");
            setConfirmOpen(false);
          }}
        >
          SELL
        </button>
      </div>

      {/* Order type + Product */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[10px] text-muted mb-0.5 block">Type</label>
          <select
            className="w-full bg-surface-2 border border-border rounded px-2 py-1 text-xs outline-none"
            value={orderType}
            onChange={(e) => {
              setOrderType(e.target.value as "MARKET" | "LIMIT");
              setConfirmOpen(false);
            }}
          >
            <option value="MARKET">Market</option>
            <option value="LIMIT">Limit</option>
          </select>
        </div>
        <div>
          <label className="text-[10px] text-muted mb-0.5 block">Product</label>
          <select
            className="w-full bg-surface-2 border border-border rounded px-2 py-1 text-xs outline-none"
            value={productType}
            onChange={(e) => {
              setProductType(e.target.value as "INTRADAY" | "DELIVERY");
              setConfirmOpen(false);
            }}
          >
            <option value="INTRADAY">Intraday</option>
            <option value="DELIVERY">Delivery</option>
          </select>
        </div>
      </div>

      {/* Quantity */}
      <div>
        <label className="text-[10px] text-muted mb-0.5 block">Quantity</label>
        <input
          type="number"
          className={cn(
            "w-full bg-surface-2 border rounded px-2 py-1 text-xs outline-none font-mono",
            qty <= 0 && quantity !== ""
              ? "border-red/50"
              : "border-border"
          )}
          value={quantity}
          onChange={(e) => {
            setQuantity(e.target.value);
            setConfirmOpen(false);
          }}
          min={1}
          max={999999}
        />
      </div>

      {/* Price (for limit orders) */}
      {orderType === "LIMIT" && (
        <div>
          <label className="text-[10px] text-muted mb-0.5 block">Price</label>
          <input
            type="number"
            className={cn(
              "w-full bg-surface-2 border rounded px-2 py-1 text-xs outline-none font-mono",
              orderType === "LIMIT" && prc <= 0 && price !== ""
                ? "border-red/50"
                : "border-border"
            )}
            value={price}
            onChange={(e) => {
              setPrice(e.target.value);
              setConfirmOpen(false);
            }}
            step="0.05"
            min={0.05}
          />
        </div>
      )}

      {/* Validation errors */}
      {errors.length > 0 && quantity !== "" && (
        <div className="text-[10px] text-red space-y-0.5">
          {errors.map((e, i) => (
            <p key={i}>{e}</p>
          ))}
        </div>
      )}

      {/* Confirmation prompt */}
      {confirmOpen && (
        <div className="bg-surface-2 border border-amber/30 rounded p-2 text-[11px] space-y-1.5">
          <p className="flex items-center gap-1 font-medium text-amber">
            <ShieldCheck className="w-3 h-3" /> Confirm Order
          </p>
          <p className="text-muted">
            {direction} {qty} x {symbol} @ {orderType === "MARKET" ? "Market" : prc} ({productType})
          </p>
          <div className="flex gap-2">
            <button
              onClick={handleSubmit}
              className="px-2 py-0.5 bg-accent text-white rounded text-[10px] font-medium"
            >
              Confirm
            </button>
            <button
              onClick={() => setConfirmOpen(false)}
              className="px-2 py-0.5 text-muted hover:text-foreground text-[10px]"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Submit */}
      {!confirmOpen && (
        <button
          onClick={handleSubmit}
          disabled={submitting || !isValid}
          className={cn(
            "flex items-center justify-center gap-1.5 py-2 rounded text-xs font-semibold transition-colors",
            direction === "BUY"
              ? "bg-green hover:bg-green/90 text-white"
              : "bg-red hover:bg-red/90 text-white",
            (submitting || !isValid) && "opacity-50 cursor-not-allowed"
          )}
        >
          <Send className="w-3 h-3" />
          {submitting ? "Placing..." : `${direction} ${symbol}`}
        </button>
      )}

      {/* Result */}
      {result && (
        <div
          className={cn(
            "text-[11px] px-2 py-1.5 rounded",
            result.ok ? "bg-green/10 text-green" : "bg-red/10 text-red"
          )}
        >
          {result.msg}
        </div>
      )}

      <div className="flex items-start gap-1.5 text-[10px] text-muted mt-1">
        <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
        <span>
          Orders are routed based on trading mode (Paper/Live) set in backend
          config.
        </span>
      </div>
    </div>
  );
}
