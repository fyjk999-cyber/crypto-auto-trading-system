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
  return vi.fn(async (input: string | URL | Request, _init?: RequestInit) => {
    const url = String(input);
    const path = url.replace(/^.*\/local-api/, "");
    if (path in overrides) {
      const value = overrides[path];
      return value instanceof Response ? value : json(value);
    }
    if (path.startsWith("/market/klines")) return json({ detail: "not found" }, 404);
    if (path === "/market/sources") return json({ provider: "OKX", source: "OKX", status: "HEALTHY", sources: { ticker: { source: "OKX_PUBLIC", status: "HEALTHY" } } });
    if (path === "/market") return json({ symbol: "BTCUSDT", source: "OKX", data_source: "REAL", price: "63420.5", mark_price: "63418.3", funding_rate: "0.0001", open_interest: "18200000000", health: "HEALTHY" });
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
    if (path === "/llm/status") return json({ configured: false, health: "NOT_CONFIGURED", providers: 0, routes: 0, usage: { today_calls: 0, today_tokens: 0, failed_calls: 0, average_latency_ms: 0 } });
    if (path === "/llm/providers") return json({ providers: [] });
    if (path === "/llm/routes") return json({ routes: [] });
    if (path === "/llm/domain-models") return json({ domain_models: [
      { domain_model_id: "crypto-trader-live", display_name: "CryptoTrader-Live-v1", version: "v1", prompt_version: "live-prompt-v1", context_profile_version: "live-context-v1", output_schema_version: "trading-analysis-v1", routes: [{ provider_id: "deepseek", base_model: "deepseek-chat" }] },
      { domain_model_id: "crypto-trader-learning", display_name: "CryptoTrader-Learning-v1", version: "v1", prompt_version: "learning-prompt-v1", context_profile_version: "learning-context-v1", output_schema_version: "review-lesson-v1", routes: [] },
      { domain_model_id: "crypto-trader-evolution", display_name: "CryptoTrader-Evolution-v1", version: "v1", prompt_version: "evolution-prompt-v1", context_profile_version: "evolution-context-v1", output_schema_version: "research-hypothesis-candidate-v1", routes: [] },
    ] });
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
  it("默认进入交易页，并且显示六个一级导航", async () => {
    setup();
    const nav = screen.getByRole("navigation", { name: "主导航" });
    expect(within(nav).getAllByRole("link")).toHaveLength(6);
    expect(within(nav).getByRole("link", { name: "交易" }).getAttribute("aria-current")).toBe("page");
    await waitFor(() => expect(screen.getByText("$125.5")).toBeTruthy());
    expect(screen.getByRole("heading", { name: "BTCUSDT 行情" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "当前判断" })).toBeTruthy();
  });

  it("LLM 页面不持久化密钥，并可测试连接、保存 Provider 与六条语义路由", async () => {
    window.location.hash = "#/llm";
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = backend({
      "/llm/test": { ok: true, provider: "deepseek", model: "deepseek-chat", latency_ms: 88, error_code: null },
      "/llm/providers": { providers: [] },
      "/llm/routes": { routes: [] },
      "/llm/domain-models": { domain_models: [] },
      "/llm/status": { configured: false, health: "NOT_CONFIGURED", usage: { today_calls: 0 } },
    });
    setup(fetchMock);
    await waitFor(() => expect(screen.getByRole("heading", { name: "LLM Provider" })).toBeTruthy());
    const key = screen.getByLabelText("LLM API Key") as HTMLInputElement;
    expect(key.type).toBe("password");
    expect(screen.getByText("基础模型 / Base Model")).toBeTruthy();
    expect(screen.getByText("领域模型 / Domain Models")).toBeTruthy();
    fireEvent.change(key, { target: { value: "sk-browser-temporary" } });
    expect(setItem).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    await waitFor(() => expect(screen.getByText("连接成功 · 88 ms")).toBeTruthy());
    const testCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/local-api/llm/test"));
    expect(String(testCall?.[1]?.body)).toContain("sk-browser-temporary");
    expect(setItem).not.toHaveBeenCalled();
    expect(screen.getAllByText(/Live Analysis|Daily Review|Daily Lesson Extraction|Evolution Research|Evolution Hypothesis|Evolution Candidate Reasoning/)).toHaveLength(6);
  });

  it("本地开发直接连接后端 WebSocket，避免开发代理丢失升级请求", async () => {
    setup();
    await waitFor(() => expect(TestWebSocket.instances.length).toBeGreaterThan(0));
    expect(TestWebSocket.instances[0].url).toBe("ws://127.0.0.1:8000/ws");
  });

  it("Kline API 不存在时明确显示接口尚未开放", async () => {
    setup();
    await waitFor(() => expect(screen.getByText("K线接口尚未开放")).toBeTruthy());
    expect(chartMocks.createChart).not.toHaveBeenCalled();
  });

  it("Kline 后端返回不可用状态时显示真实不可用提示，不渲染空白图表", async () => {
    setup(backend({
      "/market/klines?symbol=BTCUSDT&interval=1m&limit=500": { symbol: "BTCUSDT", interval: "1m", source: "BINANCE_USDM", status: "UNAVAILABLE", candles: [] },
    }));
    await waitFor(() => expect(screen.getByText("K线暂不可用")).toBeTruthy());
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

  it("明确区分 OKX 实时行情与本地 PAPER 模拟执行", async () => {
    setup(backend({
      "/market": { symbol: "BTCUSDT", source: "OKX", status: "HEALTHY", price: "100", mark_price: "99", index_price: "98", best_bid: "99.5", best_ask: "100.5", spread: "1", basis: "0.01", health: "HEALTHY" },
      "/market/klines?symbol=BTCUSDT&interval=1m&limit=500": { symbol: "BTCUSDT", interval: "1m", source: "OKX", status: "HEALTHY", supported_intervals: ["1m"], candles: [candle()] },
      "/exchange-health": { market_data: { provider: "OKX", status: "HEALTHY" }, execution: { provider: "LOCAL_PAPER", status: "CONNECTED" }, adapter: "connected", mode: "PAPER" },
    }));
    await waitFor(() => expect(screen.getByText("行情：OKX · 实时")).toBeTruthy());
    expect(screen.getByText("执行：本地 PAPER 模拟成交")).toBeTruthy();
    expect(screen.getByText("指数价格")).toBeTruthy();
    expect(screen.getByText("买一")).toBeTruthy();
  });

  it("没有信号时显示暂无判断而不是观望", async () => {
    setup(backend({
      "/market": { symbol: "BTCUSDT", source: "OKX", status: "HEALTHY", price: "100", health: "HEALTHY" },
      "/market/sources": { provider: "OKX", status: "HEALTHY", sources: {} },
      "/signals": { signals: [] },
    }));
    await waitFor(() => expect(screen.getByText("暂无判断数据")).toBeTruthy());
    expect(screen.queryByText("观望")).toBeNull();
  });

  it("市场不可用时保留真实不可用状态，不展示假价格", async () => {
    setup(backend({ "/market": { symbol: "BTCUSDT", status: "UNAVAILABLE", price: "99999" }, "/market/sources": { status: "UNAVAILABLE", sources: {} } }));
    await waitFor(() => expect(screen.getByText("不可用")).toBeTruthy());
    const marketPanel = screen.getByRole("heading", { name: "BTCUSDT 行情" }).closest("section");
    expect(marketPanel?.textContent).not.toContain("99999");
  });

  it("OKX 凭据面板使用密码字段，仅将 DEMO 凭据提交至后端且不持久化浏览器", async () => {
    window.location.hash = "#/system";
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = backend({
      "/exchange/okx/status": { configured: false, authenticated: false, health: "NOT_CONFIGURED" },
      "/exchange/okx/credentials": { saved: true, demo: true, key_suffix: "demo" },
    });
    setup(fetchMock);
    await waitFor(() => expect(screen.getByRole("heading", { name: "OKX API 连接" })).toBeTruthy());
    expect(screen.getByText("模拟盘 DEMO")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "配置 API" }));
    const apiKey = screen.getByLabelText("OKX API Key") as HTMLInputElement;
    expect(apiKey.type).toBe("password");
    expect((screen.getByLabelText("OKX Secret Key") as HTMLInputElement).type).toBe("password");
    expect((screen.getByLabelText("OKX Passphrase") as HTMLInputElement).type).toBe("password");
    fireEvent.change(apiKey, { target: { value: "never-persist" } });
    expect(setItem).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("OKX Secret Key"), { target: { value: "secret" } });
    fireEvent.change(screen.getByLabelText("OKX Passphrase"), { target: { value: "passphrase" } });
    fireEvent.submit(screen.getByRole("button", { name: "保存配置" }).closest("form")!);
    await waitFor(() => expect(screen.getByText("DEMO 凭据已提交至受保护后端，浏览器未保存凭据。")).toBeTruthy());
    expect(setItem).not.toHaveBeenCalled();
    const credentialCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/local-api/exchange/okx/credentials"));
    expect(credentialCall?.[1]).toMatchObject({ method: "POST" });
    expect(String(credentialCall?.[1]?.body)).toContain('"demo":true');
  });

  it("OKX 验证保留 DEGRADED 并显示失败阶段和中文原因，不显示凭据", async () => {
    window.location.hash = "#/system";
    const fetchMock = backend({
      "/exchange/okx/status": { configured: true, key_suffix: "1234", health: "UNVERIFIED" },
      "/exchange/okx/validate": {
        authenticated: false, health: "DEGRADED", stage: "ACCOUNT_CONFIG", reason_code: "AUTH_FAILED", exchange_code: "50113", message: "Invalid signature",
      },
    });
    setup(fetchMock);
    await waitFor(() => expect(screen.getByRole("button", { name: "验证连接" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "验证连接" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("验证失败：ACCOUNT_CONFIG"));
    expect(screen.getByText("API 凭据验证失败")).toBeTruthy();
    expect(screen.queryByText("Invalid signature")).toBeNull();
  });

  it("OKX 验证请求期间立即显示进度", async () => {
    window.location.hash = "#/system";
    let finishValidation!: (response: Response) => void;
    const validation = new Promise<Response>((resolve) => { finishValidation = resolve; });
    const baseFetch = backend({
      "/exchange/okx/status": { configured: true, key_suffix: "1234", health: "UNVERIFIED" },
    });
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      if (String(input).endsWith("/local-api/exchange/okx/validate")) return validation;
      return baseFetch(input, init);
    });
    setup(fetchMock);
    await waitFor(() => expect(screen.getByRole("button", { name: "验证连接" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "验证连接" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("正在验证 OKX 连接"));
    expect((screen.getByRole("button", { name: "验证中…" }) as HTMLButtonElement).disabled).toBe(true);
    finishValidation(json({ authenticated: true, health: "HEALTHY", stage: "COMPLETE" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("OKX DEMO 验证成功"));
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
