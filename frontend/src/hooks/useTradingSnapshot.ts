import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, websocketUrl } from "../api/client";
import type { Account, KillSwitch, Order, Position, RuntimeHealth, TradingSnapshot } from "../types/api";

const optionalPaths = ["/market", "/market/sources", "/regime", "/signals", "/strategies", "/risk", "/margin", "/reviews", "/daily-reviews", "/learning", "/exchange-health", "/version"] as const;

const loading = { status: "loading" } as const;
const initial: TradingSnapshot = {
  health: loading, ready: loading, runtime: loading, account: loading, positions: loading,
  orders: loading, killswitch: loading, optional: {}, websocket: "connecting",
};

export function useTradingSnapshot() {
  const [snapshot, setSnapshot] = useState<TradingSnapshot>(initial);
  const retry = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    const [health, ready, runtime, account, positions, orders, killswitch, ...optionalResults] = await Promise.all([
      getJson<Record<string, unknown>>("/health"), getJson<Record<string, unknown>>("/ready"), getJson<RuntimeHealth>("/runtime"), getJson<Account>("/account"),
      getJson<Record<string, Position>>("/positions"), getJson<Order[]>("/orders"), getJson<KillSwitch>("/killswitch"),
      ...optionalPaths.map((path) => getJson(path)),
    ]);
    setSnapshot((previous) => ({
      ...previous, health, ready, runtime, account, positions, orders, killswitch,
      optional: Object.fromEntries(optionalPaths.map((path, index) => [path, optionalResults[index]])),
    }));
  }, []);

  useEffect(() => {
    void refresh();
    const poll = window.setInterval(() => void refresh(), 10_000);
    return () => window.clearInterval(poll);
  }, [refresh]);

  useEffect(() => {
    let socket: WebSocket | undefined;
    let cancelled = false;
    const connect = () => {
      if (cancelled) return;
      setSnapshot((previous) => ({ ...previous, websocket: "connecting" }));
      socket = new WebSocket(websocketUrl());
      socket.onopen = () => setSnapshot((previous) => ({ ...previous, websocket: "connected" }));
      socket.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data) as { event_type?: string; payload?: Record<string, unknown>; timestamp?: string };
          setSnapshot((previous) => ({ ...previous, lastEvent: parsed }));
        } catch { /* Ignore malformed backend frames without breaking the UI. */ }
      };
      socket.onclose = () => {
        setSnapshot((previous) => ({ ...previous, websocket: "disconnected" }));
        if (!cancelled) retry.current = window.setTimeout(() => { void refresh(); connect(); }, 2_000);
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => { cancelled = true; if (retry.current) window.clearTimeout(retry.current); socket?.close(); };
  }, [refresh]);

  return { snapshot, refresh };
}
