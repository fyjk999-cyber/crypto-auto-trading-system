import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AIFirstDecisionConsole } from "./AIFirstDecisionConsole";

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {
  status,
  headers: { "content-type": "application/json" },
});

function backend(overrides: Record<string, unknown> = {}) {
  return vi.fn(async (input: string | URL | Request) => {
    const path = String(input).replace(/^.*\/local-api/, "");
    if (path in overrides) return json(overrides[path]);
    if (path === "/decision-context") return json({ status: "NOT_AVAILABLE" });
    if (path === "/positions") return json({});
    if (path === "/risk") return json({ kill_switch: { enabled: false } });
    if (path === "/exchange-health") return json({ execution: { status: "CONNECTED" } });
    if (path === "/orders") return json([]);
    if (path === "/llm/status") return json({ configured: true, health: "HEALTHY" });
    return json({ detail: "not found" }, 404);
  });
}

afterEach(() => {
  cleanup();
  window.location.hash = "";
  vi.restoreAllMocks();
});

describe("AI-first decision console", () => {
  it("shows weak quant evidence as advisory without changing the AI action", async () => {
    vi.stubGlobal("fetch", backend({
      "/decision-context": {
        status: "OK",
        symbol: "ETHUSDT",
        action: "LONG",
        market_regime: "UNKNOWN",
        selected_strategy: "market_structure",
        strategy_fit_score: 0.1,
        evidence_adjusted_confidence: 0.2,
        reason_codes: ["LOW_STRATEGY_FIT_EVIDENCE", "LOW_CONFIDENCE_EVIDENCE", "REGIME_UNKNOWN"],
        factor_snapshot_id: "snap-1",
        llm_invocation_id: "llm-1",
        strategy_candidates: [
          { strategy_id: "market_structure", direction: "LONG", fit_score: 0.1 },
          { strategy_id: "mean_reversion", direction: "SHORT", fit_score: 0.08 },
        ],
      },
    }));

    render(<AIFirstDecisionConsole />);

    await waitFor(() => expect(screen.getByText("ETHUSDT")).toBeTruthy());
    expect(screen.getAllByText("LONG").length).toBeGreaterThan(0);
    expect(screen.getByText("AI-FIRST · QUANT-AS-EVIDENCE")).toBeTruthy();
    expect(screen.getByText("Advisory · 不阻止 AI")).toBeTruthy();
    expect(screen.getByText("LOW_STRATEGY_FIT_EVIDENCE")).toBeTruthy();
    expect(screen.getByText("LOW_CONFIDENCE_EVIDENCE")).toBeTruthy();
    expect(screen.getByText("REGIME_UNKNOWN")).toBeTruthy();
    expect(screen.getByText("YES")).toBeTruthy();
  });

  it("shows a current-symbol position as a real hard gate", async () => {
    vi.stubGlobal("fetch", backend({
      "/decision-context": {
        status: "OK",
        symbol: "ETHUSDT",
        action: "NO_TRADE",
        market_regime: "RANGE",
        selected_strategy: "market_structure",
        strategy_fit_score: 0.5,
        evidence_adjusted_confidence: 0.6,
        reason_codes: ["POSITION_ALREADY_OPEN"],
        factor_snapshot_id: "snap-2",
        llm_invocation_id: "NOT_AVAILABLE",
        strategy_candidates: [],
      },
      "/positions": {
        ETHUSDT: {
          symbol: "ETHUSDT",
          quantity: "1",
          cost_basis: "100",
          realized_pnl: "0",
        },
      },
    }));

    render(<AIFirstDecisionConsole />);

    await waitFor(() => expect(screen.getByText("当前币持仓锁")).toBeTruthy());
    const consoleRoot = screen.getByTestId("ai-first-console");
    expect(consoleRoot.textContent).toContain("BLOCK");
    expect(consoleRoot.textContent).toContain("POSITION_ALREADY_OPEN");
  });
});
