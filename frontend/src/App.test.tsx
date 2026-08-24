import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

class TestWebSocket {
  static instances: TestWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(_url: string) { TestWebSocket.instances.push(this); }
  close() { this.onclose?.(); }
}

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

afterEach(() => { cleanup(); window.location.hash = ""; vi.restoreAllMocks(); TestWebSocket.instances = []; });

describe("trading control center", () => {
  it("renders backend truth, not fabricated portfolio data", async () => {
    vi.stubGlobal("WebSocket", TestWebSocket);
    vi.stubGlobal("fetch", vi.fn(async (input: string) => {
      if (input.endsWith("/account")) return json({ account_id: "default", mode: "PAPER", balances: {}, equity: "125.50", margin_used: "0" });
      if (input.endsWith("/positions")) return json({});
      if (input.endsWith("/orders")) return json([]);
      if (input.endsWith("/health")) return json({ overall: "OK" });
      if (input.endsWith("/ready")) return json({ ready: true, mode: "PAPER" });
      if (input.endsWith("/runtime")) return json({ engine: "not attached" });
      if (input.endsWith("/killswitch")) return json({ enabled: false });
      return json({ detail: "not found" }, 404);
    }));
    render(<App />);
    await waitFor(() => expect(screen.getByText("125.50")).toBeTruthy());
    expect(screen.getAllByText("No data").length).toBeGreaterThan(0);
    expect(screen.getByText("NOT AVAILABLE YET")).toBeTruthy();
    expect(screen.getAllByRole("link")).toHaveLength(10);
  });

  it("shows Backend Offline instead of a blank page", async () => {
    vi.stubGlobal("WebSocket", TestWebSocket);
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    render(<App />);
    await waitFor(() => expect(screen.getByText("Local API is unavailable")).toBeTruthy());
    expect(screen.getByText(/Expected API:/)).toBeTruthy();
  });

  it("keeps UNKNOWN orders explicit and preserves native page routing", async () => {
    window.location.hash = "#/orders";
    vi.stubGlobal("WebSocket", TestWebSocket);
    vi.stubGlobal("fetch", vi.fn(async (input: string) => input.endsWith("/orders")
      ? json([{ internal_order_id: "o-1", client_order_id: "c-1", symbol: "BTCUSDT", side: "BUY", order_type: "LIMIT", quantity: "1", filled_quantity: "0", status: "UNKNOWN", created_at: "2026-01-01", updated_at: "2026-01-01" }])
      : json({})));
    render(<App />);
    await waitFor(() => expect(screen.getByText(/Exchange reconciliation required/)).toBeTruthy());
    window.location.hash = "#/risk";
    fireEvent(window, new HashChangeEvent("hashchange"));
    expect(screen.getByRole("heading", { level: 1, name: "Risk" })).toBeTruthy();
  });
});
