import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getJson } from "../api/client";
import type { ApiState, KlineCandle, KlineInterval, KlineResponse, TradingSnapshot } from "../types/api";

const intervals: KlineInterval[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

function validCandle(value: unknown): value is KlineCandle {
  if (!value || typeof value !== "object") return false;
  const candle = value as Record<string, unknown>;
  return ["open_time", "open", "high", "low", "close", "volume"].every((key) => candle[key] !== undefined && candle[key] !== null);
}

function mergeCandle(candles: KlineCandle[], candle: KlineCandle) {
  const index = candles.findIndex((item) => item.open_time === candle.open_time);
  if (index < 0) return [...candles, candle].slice(-500);
  const next = [...candles];
  next[index] = candle;
  return next;
}

export function useKlines(lastEvent: TradingSnapshot["lastEvent"], websocket: TradingSnapshot["websocket"]) {
  const [interval, setInterval] = useState<KlineInterval>("1m");
  const [state, setState] = useState<ApiState<KlineResponse>>({ status: "loading" });
  const previousSocket = useRef(websocket);

  const refresh = useCallback(async () => {
    const result = await getJson<KlineResponse>(`/market/klines?symbol=BTCUSDT&interval=${interval}&limit=500`);
    if (result.status === "ready" && (!Array.isArray(result.data?.candles) || !result.data.candles.every(validCandle))) {
      setState({ status: "error", message: "K线数据格式异常" });
      return;
    }
    setState(result);
  }, [interval]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (previousSocket.current !== "connected" && websocket === "connected") void refresh();
    previousSocket.current = websocket;
  }, [refresh, websocket]);

  useEffect(() => {
    if (lastEvent?.event_type !== "kline" || !validCandle(lastEvent.payload)) return;
    const payload = lastEvent.payload as KlineCandle & { symbol?: string; interval?: string };
    if ((payload.symbol && payload.symbol !== "BTCUSDT") || (payload.interval && payload.interval !== interval)) return;
    setState((current) => current.status === "ready" && current.data
      ? { ...current, data: { ...current.data, candles: mergeCandle(current.data.candles, payload) } }
      : current);
  }, [interval, lastEvent]);

  const supportedIntervals = useMemo(() => {
    if (state.status !== "ready" || !state.data) return [];
    const supported = state.data.supported_intervals ?? [state.data.interval];
    return intervals.filter((item) => supported.includes(item));
  }, [state]);

  return { state, interval, setInterval, supportedIntervals, intervals, refresh };
}
