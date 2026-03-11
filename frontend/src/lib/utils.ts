export function cn(...classes: (string | false | undefined | null)[]) {
  return classes.filter(Boolean).join(" ");
}

export function formatPrice(price: number | null | undefined): string {
  if (price == null) return "—";
  return price.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatPnl(pnl: number): string {
  const sign = pnl >= 0 ? "+" : "";
  return `${sign}${formatPrice(pnl)}`;
}

export function pnlColor(pnl: number): string {
  if (pnl > 0) return "text-green";
  if (pnl < 0) return "text-red";
  return "text-muted";
}

export function formatPercent(pct: number): string {
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

export function formatVolume(vol: number): string {
  if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(1)}M`;
  if (vol >= 1_000) return `${(vol / 1_000).toFixed(1)}K`;
  return vol.toString();
}

export function impulseColor(signal: string): string {
  switch (signal?.toLowerCase()) {
    case "bullish":
    case "green":
      return "#22c55e";
    case "bearish":
    case "red":
      return "#ef4444";
    default:
      return "#3b82f6";
  }
}
