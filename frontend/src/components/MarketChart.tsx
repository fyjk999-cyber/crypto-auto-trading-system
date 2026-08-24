import { useEffect, useRef } from "react";
import { CandlestickSeries, ColorType, createChart, HistogramSeries, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import type { ApiState, KlineResponse } from "../types/api";

type Props = {
  source: ApiState<KlineResponse>;
  websocket: "connecting" | "connected" | "disconnected";
};

const message: Record<ApiState<unknown>["status"], string> = {
  loading: "K线加载中",
  ready: "",
  empty: "暂无K线数据",
  unavailable: "K线接口尚未开放",
  offline: "后端离线，暂时无法加载K线",
  error: "K线数据异常",
};

export function MarketChart({ source, websocket }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<ReturnType<typeof createChart> | null>(null);
  const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeries = useRef<ISeriesApi<"Histogram"> | null>(null);
  const previousLastTime = useRef<number | null>(null);
  const previousLength = useRef(0);

  useEffect(() => {
    if (source.status !== "ready" || !source.data?.candles.length || !container.current || chart.current) return;
    chart.current = createChart(container.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#66736f", attributionLogo: true },
      grid: { vertLines: { color: "#edf1ef" }, horzLines: { color: "#edf1ef" } },
      rightPriceScale: { borderColor: "#dce4e0" },
      timeScale: { borderColor: "#dce4e0", timeVisible: true, secondsVisible: false },
      crosshair: { vertLine: { color: "#8aa198" }, horzLine: { color: "#8aa198" } },
    });
    candleSeries.current = chart.current.addSeries(CandlestickSeries, {
      upColor: "#168466", downColor: "#c45454", borderVisible: false,
      wickUpColor: "#168466", wickDownColor: "#c45454",
    });
    volumeSeries.current = chart.current.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume" });
    chart.current.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    return () => {
      chart.current?.remove();
      chart.current = null;
      candleSeries.current = null;
      volumeSeries.current = null;
      previousLastTime.current = null;
      previousLength.current = 0;
    };
  }, [source.status]);

  useEffect(() => {
    if (source.status !== "ready" || !source.data?.candles.length || !chart.current || !candleSeries.current || !volumeSeries.current) return;
    const candleData = source.data.candles.map((item) => ({
      time: Math.floor(new Date(item.open_time).getTime() / 1000) as UTCTimestamp,
      open: Number(item.open), high: Number(item.high), low: Number(item.low), close: Number(item.close),
    }));
    const volumeData = source.data.candles.map((item) => ({
      time: Math.floor(new Date(item.open_time).getTime() / 1000) as UTCTimestamp,
      value: Number(item.volume), color: Number(item.close) >= Number(item.open) ? "#16846655" : "#c4545455",
    }));
    const last = candleData.at(-1);
    const lastVolume = volumeData.at(-1);
    const lastTime = Number(last?.time ?? 0);
    const incremental = previousLength.current > 0 && source.data.candles.length >= previousLength.current
      && (lastTime === previousLastTime.current || source.data.candles.length === previousLength.current + 1);
    if (incremental && last && lastVolume) {
      candleSeries.current.update(last);
      volumeSeries.current.update(lastVolume);
    } else {
      candleSeries.current.setData(candleData);
      volumeSeries.current.setData(volumeData);
      chart.current.timeScale().fitContent();
    }
    previousLastTime.current = lastTime;
    previousLength.current = source.data.candles.length;
  }, [source]);

  if (source.status !== "ready" || !source.data?.candles.length) {
    const safeMessage = source.message === "Binance 行情受地区限制" || source.message === "K线暂不可用" ? source.message : message[source.status];
    return <div className={`chart-fallback ${source.status}`} role="status"><span className="chart-skeleton" />{safeMessage}</div>;
  }

  return <div className="chart-stage"><div ref={container} className="chart-canvas" data-testid="market-chart" />{websocket !== "connected" && <span className="sync-warning">实时同步中断</span>}</div>;
}
