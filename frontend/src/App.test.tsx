import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const chartMocks = vi.hoisted(() => {
  const candles = { setData: vi.fn(), update: vi.fn() };
  const volume = { setData: vi.fn(), update: vi.fn() };
  const chart = {
    addSeries: vi.fn((kind: string) => kind === "candles" ? candles : volume),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    remove: vi.fn(),
  };
  return { candles, volume, chart, createChart: vi.fn(() => chart) };
});

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "candles",
  HistogramSeries: "volume",
  ColorType: { Solid: "solid" },
  createChart: chartMocks.createChart,
}));

class TestWebSocket {
  static instances: TestWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) { TestWebSocket.instances.push(this); }
  open() { this.onopen?.(); }
  message(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent); }
  disconnect() { this.onclose?.(); }
  close() { this.onclose?.(); }
}

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

const candle = (close = "101") => ({
  open_time: "2026-08-24T00:00:00Z", open: "100", high: "102", low: "99", close, volume: "12", close_time: "2026-08-24T00:00:59Z",
});

function backend(overrides: Record<string, unknown | Response> = {}) {
  return vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    const path = url.replace(/^.*\/local-api/, "");
    if (path in overrides) {
      const value = overrides[path];
      return value instanceof Response ? value : json(value);
    }
    if (path.startsWith("/market/klines")) return json({ detail: "not found" }, 404);
    if (path === "/market/sources") return json({ binance: { source: "BINANCE_USDM_PUBLIC", status: "HEALTHY" } });
    if (path === "/market") return json({ symbol: "BTCUSDT", price: "63420.5", mark_price: "63418.3", funding_rate: "0.0001", open_interest: "18200000000", health: "HEALTHY" });
    if (path === "/account") return json({ account_id: "default", mode: "PAPER", balances: {}, equity: "125.50", margin_used: "0" });
    if (path === "/positions") return json({});
    if (path === "/orders") return json([]);
    if (path === "/health") return json({ overall: "OK" });
    if (path === "/ready") return json({ ready: true, mode: "PAPER" });
    if (path === "/runtime") return json({ state: "RUNNING", mode: "PAPER" });
    if (path === "/killswitch") return json({ enabled: false });
    if (path === "/signals") return json({ signals: [] });
    if (path === "/strategies") return json({ strategies: [] });
    if (path === "/risk") return json({ risk_config: {}, kill_switch: { enabled: false } });
    if (path === "/regime") return json({ status: "NO_DATA", regime: null, reasons: [] });
    if (path === "/daily-reviews") return json({ daily_reviews: [], count: 0 });
    if (path === "/learning") return json({ status: "NO_ALPHA", fast_learning: {}, slow_learning_candidates: [] });
    if (path === "/reviews") return json({ reviews: [], count: 0 });
    if (path === "/exchange-health") return json({ adapter: "connected", mode: "PAPER" });
    if (path === "/version") return json({ git_sha: "abc123", environment: "local" });
    return json({ detail: "not found" }, 404);
  });
}

afterEach(() => {
  cleanup();
  window.location.hash = "";
  window.innerWidth = 1024;
  vi.useRealTimers();
  vi.restoreAllMocks();
  TestWebSocket.instances = [];
  chartMocks.createChart.mockClear();
  chartMocks.candles.setData.mockClear();
  chartMocks.candles.update.mockClear();
  chartMocks.volume.setData.mockClear();
  chartMocks.volume.update.mockClear();
});

function setup(fetchMock = backend()) {
  vi.stubGlobal("WebSocket", TestWebSocket);
  vi.stubGlobal("fetch", fetchMock);
  return render(<App />);
}

describe("中文加密交易终端 V2", () => {
  it("默认进入交易页，并且只有五个中文一级导航", async () => {
    setup();
    const nav = screen.getByRole("navigation", { name: "主导航" });
    expect(within(nav).getAllByRole("link")).toHaveLength(5);
    expect(within(nav).getByRole("link", { name: "交易" }).getAttribute("aria-current")).toBe("page");
    await waitFor(() => expect(screen.getByText("$125.5")).toBeTruthy());
    expect(screen.getByRole("heading", { name: "BTCUSDT 行情" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "当前判断" })).toBeTruthy();
  });

  it("Kline API 不存在时明确显示接口尚未开放", async () => {
    setup();
    await waitFor(() => expect(screen.getByText("K线接口尚未开放")).toBeTruthy());
    expect(chartMocks.createChart).not.toHaveBeenCalled();
  });

  it("真实 Kline 返回后使用 Lightweight Charts v5 渲染", async () => {
    setup(backend({
      "/market/klines?symbol=BTCUSDT&interval=1m&limit=500": { symbol: "BTCUSDT", interval: "1m", source: "BINANCE_USDM_PUBLIC", status: "HEALTHY", supported_intervals: ["1m"], candles: [candle()] },
    }));
    await waitFor(() => expect(screen.getByTestId("market-chart")).toBeTruthy());
    expect(chartMocks.createChart).toHaveBeenCalledOnce();
    expect(chartMocks.candles.setData).toHaveBeenCalledWith([expect.objectContaining({ open: 100, close: 101 })]);
  });

  it("收到真实 kline WebSocket 事件后增量更新当前 Candle", async () => {
    setup(backend({
      "/market/klines?symbol=BTCUSDT&interval=1m&limit=500": { symbol: "BTCUSDT", interval: "1m", source: "BINANCE_USDM_PUBLIC", status: "HEALTHY", supported_intervals: ["1m"], candles: [candle()] },
    }));
    await waitFor(() => expect(chartMocks.candles.setData).toHaveBeenCalled());
    act(() => TestWebSocket.instances[0].message({ event_type: "kline", payload: { ...candle("103"), symbol: "BTCUSDT", interval: "1m", closed: false } }));
    await waitFor(() => expect(chartMocks.candles.update).toHaveBeenCalledWith(expect.objectContaining({ close: 103 })));
  });

  it("WebSocket 断开时保留页面并显示同步中断", async () => {
    setup();
    act(() => TestWebSocket.instances[0].open());
    await waitFor(() => expect(screen.getAllByText("WebSocket 已连接").length).toBeGreaterThan(0));
    act(() => TestWebSocket.instances[0].disconnect());
    await waitFor(() => expect(screen.getAllByText("实时同步中断").length).toBeGreaterThan(0));
    expect(screen.getByRole("heading", { name: "BTCUSDT 行情" })).toBeTruthy();
  });

  it("WebSocket 断开后按既有客户端策略重连", async () => {
    vi.useFakeTimers();
    setup();
    act(() => TestWebSocket.instances[0].disconnect());
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(TestWebSocket.instances.length).toBeGreaterThan(1);
  });

  it("没有 Kline 数据时不会生成任何假 Candle", async () => {
    setup();
    await waitFor(() => expect(screen.getByText("K线接口尚未开放")).toBeTruthy());
    expect(chartMocks.candles.setData).not.toHaveBeenCalled();
    expect(screen.queryByTestId("market-chart")).toBeNull();
  });

  it("显示模拟行情来源标记", async () => {
    setup(backend({
      "/market": { symbol: "BTCUSDT", status: "SYNTHETIC", data_source: "PAPER_SYNTHETIC", price: "100" },
      "/market/sources": { status: "SYNTHETIC", sources: {} },
    }));
    await waitFor(() => expect(screen.getByText("模拟")).toBeTruthy());
  });

  it("地区限制时隐藏价格并显示中文来源状态", async () => {
    setup(backend({
      "/market": { symbol: "BTCUSDT", status: "GEO_RESTRICTED", price: "99999" },
      "/market/sources": { status: "GEO_RESTRICTED", sources: {} },
    }));
    await waitFor(() => expect(screen.getByText("地区限制")).toBeTruthy());
    const marketPanel = screen.getByRole("heading", { name: "BTCUSDT 行情" }).closest("section");
    expect(marketPanel?.textContent).not.toContain("99999");
  });

  it("移动端宽度仍保留价格、判断、持仓、PnL 和 K线区域", async () => {
    window.innerWidth = 390;
    fireEvent(window, new Event("resize"));
    setup();
    await waitFor(() => expect(screen.getByText("账户净值")).toBeTruthy());
    expect(screen.getByText("今日盈亏")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "当前判断" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "当前持仓" })).toBeTruthy();
    expect(screen.getByText("K线接口尚未开放")).toBeTruthy();
  });

  it("后端离线时显示中文错误而不是白屏", async () => {
    setup(vi.fn(async () => { throw new Error("offline"); }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("后端离线"));
    expect(screen.getByRole("navigation", { name: "主导航" })).toBeTruthy();
  });

  it("UNKNOWN 订单保持显式，长 ID 下沉到详情", async () => {
    window.location.hash = "#/orders";
    setup(backend({
      "/orders": [{ internal_order_id: "o-1", client_order_id: "c-1", symbol: "BTCUSDT", side: "BUY", order_type: "LIMIT", quantity: "1", filled_quantity: "0", status: "UNKNOWN", created_at: "2026-01-01", updated_at: "2026-01-01" }],
    }));
    await waitFor(() => expect(screen.getByText("状态未知")).toBeTruthy());
    expect(screen.getByText(/内部订单 ID：o-1/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "订单记录" })).toBeTruthy();
  });
});
