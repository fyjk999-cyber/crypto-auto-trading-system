import { useCallback, useEffect, useMemo, useState } from "react";

import { getJson } from "../api/client";
import type { ApiState, Order, Position } from "../types/api";
import "../styles/ai-first-console.css";

type JsonRecord = Record<string, unknown>;

type ConsoleSnapshot = {
  decision: ApiState<JsonRecord>;
  positions: ApiState<Record<string, Position>>;
  risk: ApiState<JsonRecord>;
  exchange: ApiState<JsonRecord>;
  orders: ApiState<Order[]>;
  llm: ApiState<JsonRecord>;
};

const loading = { status: "loading" } as const;
const initial: ConsoleSnapshot = {
  decision: loading,
  positions: loading,
  risk: loading,
  exchange: loading,
  orders: loading,
  llm: loading,
};

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
}

function records(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function text(value: unknown, fallback = "NOT_AVAILABLE") {
  return value === undefined || value === null || value === "" ? fallback : String(value);
}

function number(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function percent(value: unknown) {
  const parsed = number(value);
  if (parsed === null) return "NOT_AVAILABLE";
  return `${(Math.abs(parsed) <= 1 ? parsed * 100 : parsed).toFixed(2)}%`;
}

function available(value: unknown) {
  return value !== undefined && value !== null && value !== "" && value !== "NOT_AVAILABLE";
}

function actionTone(action: string) {
  if (action === "LONG") return "long";
  if (action === "SHORT") return "short";
  return "neutral";
}

function gateTone(status: string) {
  if (["PASS", "READY", "CONNECTED", "HEALTHY"].includes(status)) return "pass";
  if (["BLOCK", "STOPPED", "DISCONNECTED", "UNHEALTHY"].includes(status)) return "block";
  return "unknown";
}

function isTradePage() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  return hash === "" || hash === "trade";
}

export function AIFirstDecisionConsole() {
  const [open, setOpen] = useState(true);
  const [onTradePage, setOnTradePage] = useState(isTradePage);
  const [snapshot, setSnapshot] = useState<ConsoleSnapshot>(initial);

  const refresh = useCallback(async () => {
    const [decision, positions, risk, exchange, orders, llm] = await Promise.all([
      getJson<JsonRecord>("/decision-context"),
      getJson<Record<string, Position>>("/positions"),
      getJson<JsonRecord>("/risk"),
      getJson<JsonRecord>("/exchange-health"),
      getJson<Order[]>("/orders"),
      getJson<JsonRecord>("/llm/status"),
    ]);
    setSnapshot({ decision, positions, risk, exchange, orders, llm });
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const sync = () => setOnTradePage(isTradePage());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const decision = record(snapshot.decision.data);
  const reasonCodes = strings(decision.reason_codes);
  const symbol = text(decision.current_scan_symbol ?? decision.symbol, "等待扫描");
  const action = text(decision.action, "NOT_AVAILABLE").toUpperCase();
  const llmInvocation = decision.llm_invocation_id;
  const aiEvaluated = available(llmInvocation);
  const factorSnapshotReady = available(decision.factor_snapshot_id);
  const currentPosition = snapshot.positions.data?.[symbol];
  const positionLocked = currentPosition ? Number(currentPosition.quantity) !== 0 : false;
  const riskPayload = record(snapshot.risk.data);
  const killSwitch = record(riskPayload.kill_switch).enabled === true;
  const execution = record(record(snapshot.exchange.data).execution);
  const llmPayload = record(snapshot.llm.data);
  const providerHealth = text(llmPayload.health, snapshot.llm.status === "ready" ? "READY" : "NOT_AVAILABLE").toUpperCase();
  const executionHealth = text(execution.status ?? execution.health, snapshot.exchange.status === "ready" ? "READY" : "NOT_AVAILABLE").toUpperCase();

  const opportunityRows = useMemo(() => {
    const crossCoin = records(decision.opportunity_ranking);
    if (crossCoin.length) {
      return {
        title: "跨币 Opportunity Ranking",
        rows: crossCoin
          .slice()
          .sort((a, b) => (number(b.score) ?? -1) - (number(a.score) ?? -1)),
        scoreKey: "score",
      };
    }
    const candidates = records(decision.strategy_candidates);
    return {
      title: "策略候选证据排序",
      rows: candidates
        .slice()
        .sort((a, b) => (number(b.fit_score) ?? -1) - (number(a.fit_score) ?? -1)),
      scoreKey: "fit_score",
    };
  }, [decision.opportunity_ranking, decision.strategy_candidates]);

  const latestSameSymbolOrder = useMemo(() => {
    const rows = (snapshot.orders.data ?? []).filter((order) => order.symbol === symbol);
    return rows.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))[0];
  }, [snapshot.orders.data, symbol]);

  if (!onTradePage) return null;

  return (
    <aside className={`ai-first-console ${open ? "open" : "collapsed"}`} data-testid="ai-first-console" aria-label="AI 决策控制台">
      <header className="ai-first-console__header">
        <div>
          <span className="ai-first-console__eyebrow">AI-FIRST · QUANT-AS-EVIDENCE</span>
          <strong>AI 决策控制台</strong>
        </div>
        <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
          {open ? "收起" : "展开"}
        </button>
      </header>

      {open && (
        <div className="ai-first-console__body">
          <p className="ai-first-console__doctrine">
            量化分数、策略 fit、置信度和 Regime 只提供证据，不再拥有否决 AI LONG / SHORT 的权限。
          </p>

          <section className="ai-first-console__hero">
            <div><span>当前决策币种</span><strong>{symbol}</strong></div>
            <div><span>Chief Trader</span><strong className={actionTone(action)}>{action}</strong></div>
            <div><span>AI 实际评估</span><strong>{aiEvaluated ? "YES" : "NO"}</strong></div>
          </section>

          <section>
            <div className="ai-first-console__section-title">
              <strong>AI 证据</strong><span>Evidence ≠ Gate</span>
            </div>
            <dl className="ai-first-console__facts">
              <div><dt>Regime</dt><dd>{text(decision.market_regime)}</dd></div>
              <div><dt>Strategy Fit</dt><dd>{percent(decision.strategy_fit_score)}</dd></div>
              <div><dt>AI Confidence</dt><dd>{percent(decision.evidence_adjusted_confidence)}</dd></div>
              <div><dt>主策略</dt><dd>{text(decision.selected_strategy)}</dd></div>
            </dl>
            {reasonCodes.length > 0 && (
              <div className="ai-first-console__warnings" aria-label="AI 决策警告">
                {reasonCodes.map((code) => <span key={code}>{code}</span>)}
              </div>
            )}
          </section>

          <section>
            <div className="ai-first-console__section-title">
              <strong>{opportunityRows.title}</strong><span>Advisory · 不阻止 AI</span>
            </div>
            {opportunityRows.rows.length ? (
              <div className="ai-first-console__ranking">
                {opportunityRows.rows.slice(0, 10).map((item, index) => {
                  const name = text(item.symbol ?? item.strategy_id ?? item.name, `#${index + 1}`);
                  const direction = text(item.direction, "NEUTRAL").toUpperCase();
                  const score = percent(item[opportunityRows.scoreKey]);
                  return <div key={`${name}-${index}`}><b>{index + 1}</b><span>{name}</span><em className={actionTone(direction)}>{direction}</em><strong>{score}</strong></div>;
                })}
              </div>
            ) : <p className="ai-first-console__empty">当前没有可展示的量化证据；不会生成假排名。</p>}
          </section>

          <section>
            <div className="ai-first-console__section-title"><strong>真正的硬门槛</strong><span>Safety Gates</span></div>
            <div className="ai-first-console__gates">
              <div><span>真实 FactorSnapshot</span><b className={gateTone(factorSnapshotReady ? "PASS" : "BLOCK")}>{factorSnapshotReady ? "PASS" : "BLOCK"}</b></div>
              <div><span>LLM Provider Route</span><b className={gateTone(providerHealth)}>{providerHealth}</b></div>
              <div><span>当前币持仓锁</span><b className={gateTone(positionLocked ? "BLOCK" : "PASS")}>{positionLocked ? "BLOCK" : "PASS"}</b></div>
              <div><span>Entry Cooldown</span><b className={gateTone(reasonCodes.includes("ENTRY_COOLDOWN_ACTIVE") ? "BLOCK" : "NOT_AVAILABLE")}>{reasonCodes.includes("ENTRY_COOLDOWN_ACTIVE") ? "BLOCK" : "NOT_AVAILABLE"}</b></div>
              <div><span>RiskEngine / Kill Switch</span><b className={gateTone(killSwitch ? "BLOCK" : snapshot.risk.status === "ready" ? "READY" : "NOT_AVAILABLE")}>{killSwitch ? "BLOCK" : snapshot.risk.status === "ready" ? "READY" : "NOT_AVAILABLE"}</b></div>
              <div><span>Execution Runtime</span><b className={gateTone(executionHealth)}>{executionHealth}</b></div>
            </div>
          </section>

          <section>
            <div className="ai-first-console__section-title"><strong>最近一次链路</strong><span>只显示可验证数据</span></div>
            <dl className="ai-first-console__trace">
              <div><dt>DecisionEvidence</dt><dd>{text(decision.decision_id)}</dd></div>
              <div><dt>FactorSnapshot</dt><dd>{text(decision.factor_snapshot_id)}</dd></div>
              <div><dt>LLM Invocation</dt><dd>{text(llmInvocation)}</dd></div>
              <div><dt>最近同币订单</dt><dd>{latestSameSymbolOrder ? `${latestSameSymbolOrder.status} · ${latestSameSymbolOrder.client_order_id}` : "NOT_AVAILABLE"}</dd></div>
            </dl>
          </section>

          <p className="ai-first-console__footnote">PAPER_REAL_MARKET · RiskEngine 与 ExecutionAuthority 仍拥有最终安全权限。</p>
        </div>
      )}
    </aside>
  );
}
