"use client";

import { useEffect, useState, useCallback } from "react";
import { Wallet, RefreshCw } from "lucide-react";
import { fetchFunds } from "@/lib/api";
import { formatPrice, cn } from "@/lib/utils";

interface FundRow {
  label: string;
  value: string | number;
}

export function FundsPanel() {
  const [funds, setFunds] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchFunds();
      const data = res?.data;
      if (data && typeof data === "object") {
        setFunds(data);
        setError(null);
      } else {
        setFunds(null);
        setError(res?.message || "No funds data");
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const rows: FundRow[] = funds
    ? [
        { label: "Available Cash", value: funds.availablecash || funds.net || "—" },
        { label: "Used Margin", value: funds.utilisedmargin || funds.utilised || "—" },
        { label: "Available Margin", value: funds.availableintradaypayin || funds.available || "—" },
        { label: "Collateral", value: funds.collateral || "—" },
        { label: "M2M Realised", value: funds.m2mrealized || "—" },
        { label: "M2M Unrealised", value: funds.m2munrealized || "—" },
      ]
    : [];

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <h3 className="text-xs font-semibold flex items-center gap-1.5">
          <Wallet className="w-3 h-3 text-accent" /> Funds
        </h3>
        <button
          onClick={load}
          disabled={loading}
          className="p-0.5 hover:text-accent transition-colors"
        >
          <RefreshCw className={cn("w-3 h-3", loading && "animate-spin")} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {error ? (
          <p className="text-xs text-amber">{error}</p>
        ) : !funds ? (
          <p className="text-xs text-muted">Loading...</p>
        ) : (
          <div className="space-y-2">
            {rows.map((r) => (
              <div key={r.label} className="flex justify-between text-[11px]">
                <span className="text-muted">{r.label}</span>
                <span className="font-mono font-medium">
                  {typeof r.value === "number"
                    ? formatPrice(r.value)
                    : r.value}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
