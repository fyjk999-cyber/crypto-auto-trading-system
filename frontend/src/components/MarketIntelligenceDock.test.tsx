import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MarketIntelligenceDock } from "./MarketIntelligenceDock";

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {
  status,
  headers: { "content-type": "application/json" },
});

function backend() {
  return vi.fn(async (input: string | URL | Request) => {
    const path = String(input).replace(/^.*\/local-api/, "");
    if (path.startsWith("/market/analysis")) {
      return json({
        status: "OK",
        symbol: "BTCUSDT",
        source: "OKX",
        technical_indicator_authority: "ADVISORY",
        opportunity_authority: "ADVISORY",
        market: {
          price: "80000",
          mark_price: "79990",
          index_price: "79980",
          open_24h: "78000",
          high_24h: "81000",
          low_24h: "77500",
          price_change_24h: "2000",
          price_change_percent_24h: "0.025641",
          volume_24h: "123456",
          volume_ccy_24h: "3210.5",
          best_bid: "79999.9",
          best_ask: "80000.1",
          best_bid_size: "18",
          best_ask_size: "16",
          spread: "0.2",
          depth: "1234",
          imbalance: "0.08",
          funding_rate: "0.0001",
          open_interest: "2828235.28",
          open_interest_ccy: "20500",
          open_interest_usd: "1640000000",
          basis: "-0.0004",
          health: "HEALTHY",
          source: "OKX_PUBLIC",
        },
        technical_indicators: {
          authority: "ADVISORY",
          status: "OK",
          sample_count: 200,
          available_indicator_count: 5,
          indicators: {
            rsi_14: 62.5,
            macd_12_26: 120.4,
            ema_20: 79500,
            atr_14: 340.2,
            recent_support_20: null,
          },
        },
        opportunity_ranking: [
          { symbol: "ETHUSDT", score: 0.82, direction: "LONG_BIAS", reason: "advisory evidence" },
        ],
      });
    }
    if (path.startsWith("/market/history")) {
      return json({
        status: "HEALTHY",
        source: "OKX",
        dataset: "candles",
        symbol: "BTCUSDT",
        interval: "1m",
        next_after: "1000",
        rows: [
          {
            timestamp: "2026-08-28T14:00:00+00:00",
            timestamp_ms: "1000",
            open: "79000",
            high: "80100",
            low: "78900",
            close: "80000",
            volume: "100",
            volume_ccy: "2",
            volume_quote: "160000",
          },
        ],
      });
    }
    return json({ detail: "not found" }, 404);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("OKX market intelligence dock", () => {
  it("shows the full real-market fields and marks quant evidence advisory", async () => {
    vi.stubGlobal("fetch", backend());
    render(<MarketIntelligenceDock />);

    fireEvent.click(screen.getByRole("button", { name: "打开 OKX 市场分析" }));

    await waitFor(() => expect(screen.getByText("24H 最高")).toBeTruthy());
    expect(screen.getAllByText("ADVISORY · 仅供 AI 参考").length).toBeGreaterThan(0);
    expect(screen.getByText("24H 涨跌幅")).toBeTruthy();
    expect(screen.getByText("OI USD")).toBeTruthy();
    expect(screen.getByText("Orderbook Imbalance")).toBeTruthy();
    expect(screen.getByText("当前没有 Opportunity Ranking；不会因此阻止 AI 分析。")).toBeFalsy;
  });

  it("renders every technical indicator and keeps missing values explicit", async () => {
    vi.stubGlobal("fetch", backend());
    render(<MarketIntelligenceDock />);
    fireEvent.click(screen.getByRole("button", { name: "打开 OKX 市场分析" }));

    await waitFor(() => expect(screen.getByRole("button", { name: /技术指标/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /技术指标/ }));

    expect(screen.getByText("RSI 14")).toBeTruthy();
    expect(screen.getByText("MACD 12 26")).toBeTruthy();
    expect(screen.getByText("EMA 20")).toBeTruthy();
    expect(screen.getByText("ATR 14")).toBeTruthy();
    expect(screen.getByText("Recent Support 20")).toBeTruthy();
    expect(screen.getAllByText("NOT_AVAILABLE").length).toBeGreaterThan(0);
    expect(screen.getByText(/不能单独阻止 Chief Trader/)).toBeTruthy();
  });

  it("loads OKX history only when requested", async () => {
    const fetchMock = backend();
    vi.stubGlobal("fetch", fetchMock);
    render(<MarketIntelligenceDock />);
    fireEvent.click(screen.getByRole("button", { name: "打开 OKX 市场分析" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "OKX 历史数据" })).toBeTruthy());
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/market/history"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "OKX 历史数据" }));
    fireEvent.click(screen.getByRole("button", { name: "读取 OKX 历史" }));

    await waitFor(() => expect(screen.getByText("$80,000")).toBeTruthy());
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/market/history"))).toBe(true);
    expect(screen.getByRole("button", { name: "加载更早 100 条" })).toBeTruthy();
  });
});
