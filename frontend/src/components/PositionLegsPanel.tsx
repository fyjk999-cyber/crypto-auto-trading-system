import type { ApiState, TradingSnapshot } from "../types/api";

type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord {
  if (value && typeof value === "object") return Array.isArray(value) ? {} : value as JsonRecord;
  return {};
}

function list(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function pick(source: JsonRecord, ...keys: string[]) {
  for (const key of keys) if (source[key] !== undefined && source[key] !== null && source[key] !== "") return source[key];
  return undefined;
}

function text(value: unknown, fallback = "--") {
  if (value === undefined || value === null || value === "") return fallback;
  return String(value);
}

function numberText(value: unknown, digits = 6) {
  if (value === undefined || value === null || value === "") return "--";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString("zh-CN", { maximumFractionDigits: digits }) : "--";
}

function money(value: unknown) {
  const rendered = numberText(value, 2);
  return rendered === "--" ? rendered : "$" + rendered;
}

function sideText(value: unknown) {
  const side = String(value ?? "").toUpperCase();
  if (side === "LONG") return { code: "LONG", className: "long" };
  if (side === "SHORT") return { code: "SHORT", className: "short" };
  return { code: side || "--", className: "neutral" };
}

const LABELS = {
  readOnly: "\u4ed3\u4f4d\u817f\uff08\u53ea\u8bfb\uff09",
  readOnlyNoAuthority: "\u4ed3\u4f4d\u817f\uff08\u53ea\u8bfb\uff0c\u65e0\u4ea4\u6613\u6743\u9650\uff09",
  unavailable: "\u4ed3\u4f4d\u817f\u63a5\u53e3\u6682\u672a\u5f00\u653e",
  degraded: "\u4ed3\u4f4d\u817f\u6570\u636e\u6682\u4e0d\u53ef\u7528",
  empty: "\u6682\u65e0\u6570\u636e",
  noLegs: "\u5f53\u524d\u65e0\u4ed3\u4f4d\u817f",
  legUnit: "\u6761\u817f",
  grossNote: "\u6bcf\u6761\u817f\u72ec\u7acb\u4e8b\u5b9e\u8bb0\u8d26\uff1b\u51c0\u6301\u4ed3\u4ec5\u6c47\u603b\u89c6\u56fe\uff0c\u4e0d\u63a9\u76d6\u603b\u655e\u53e3\u3002",
  gross: "\u603b\u655e\u53e3",
  net: "\u51c0\u655e\u53e3",
  grossPnl: "\u6bdb PnL",
  symbolLeg: "\u4ea4\u6613\u5bf9 / leg_id",
  side: "\u65b9\u5411",
  state: "\u72b6\u6001",
  qtyRemain: "\u6570\u91cf / \u5269\u4f59",
  entryMark: "\u5165\u573a / \u6807\u8bb0",
  pnlRealizedUnrealized: "\u5df2\u5b9e\u73b0 / \u672a\u5b9e\u73b0",
  feeFunding: "\u624b\u7eed\u8d39 / Funding",
  planDecision: "TradePlan / decision",
  baseExit: "Base Exit",
  reconciliation: "\u5bf9\u8d26",
  orderFill: "\u8ba2\u5355 / \u6210\u4ea4",
  reverse: "\u53cd\u5411",
  unsafe: "\uff08\u4e0d\u5b89\u5168\uff09",
};

export function PositionLegsPanel({ snapshot }: { snapshot: TradingSnapshot }) {
  const legState: ApiState<unknown> = snapshot.optional["/position-legs"] ?? { status: "loading" };
  const summaryState: ApiState<unknown> = snapshot.optional["/position-legs/summary"] ?? { status: "loading" };
  const legs = list(record(legState.data).position_legs);
  const summaries = list(record(summaryState.data).symbols);

  if (legState.status !== "ready") {
    const message = legState.status === "unavailable" ? LABELS.unavailable : LABELS.degraded;
    return <section className="panel position-legs-panel"><header className="panel-header"><h2>{LABELS.readOnly}</h2><span className={"state-badge " + legState.status}>{message}</span></header><div className={"empty-block " + legState.status}>{message}</div></section>;
  }
  if (legs.length === 0) {
    return <section className="panel position-legs-panel"><header className="panel-header"><h2>{LABELS.readOnly}</h2><span className="state-badge empty">{LABELS.empty}</span></header><div className="empty-block">{LABELS.noLegs}</div></section>;
  }

  const doubleSided = summaries.filter((item) => Boolean(pick(item, "both_sides")) || Number(pick(item, "gross_short_quantity") ?? 0) > 0);
  return <section className="panel position-legs-panel">
    <header className="panel-header"><h2>{LABELS.readOnlyNoAuthority}</h2><span className="state-badge ready">{legs.length} {LABELS.legUnit}</span></header>
    <p className="muted-line">{LABELS.grossNote}</p>
    {doubleSided.length > 0 && <div className="leg-summary">{doubleSided.map((item, index) => {
      const symbol = text(pick(item, "symbol"), "UNKNOWN");
      return <article key={symbol + "-" + index}>
        <strong>{symbol}</strong>
        <span>LONG {numberText(pick(item, "gross_long_quantity"))}</span>
        <span>SHORT {numberText(pick(item, "gross_short_quantity"))}</span>
        <span>{LABELS.gross} {numberText(pick(item, "gross_quantity"))}</span>
        <span>{LABELS.net} {numberText(pick(item, "net_quantity"))}</span>
        <span>{LABELS.grossPnl} {money(pick(item, "gross_pnl"))}</span>
      </article>;
    })}</div>}
    <div className="table-wrap"><table>
      <thead><tr><th>{LABELS.symbolLeg}</th><th>{LABELS.side}</th><th>{LABELS.state}</th><th>{LABELS.qtyRemain}</th><th>{LABELS.entryMark}</th><th>{LABELS.pnlRealizedUnrealized}</th><th>{LABELS.feeFunding}</th><th>{LABELS.planDecision}</th><th>{LABELS.baseExit}</th><th>{LABELS.reconciliation}</th><th>{LABELS.orderFill}</th><th>{LABELS.reverse}</th></tr></thead>
      <tbody>{legs.map((leg, index) => {
        const side = sideText(pick(leg, "side"));
        const lineage = record(leg.lineage);
        const reconciliation = record(leg.reconciliation);
        const baseExit = record(leg.base_exit);
        const legId = text(pick(leg, "leg_id"), "leg-" + index);
        const reconciliationStatus = text(pick(reconciliation, "status"), "UNKNOWN");
        const unsafe = reconciliation.leg_execution_safe === false ? LABELS.unsafe : "";
        return <tr key={legId}>
          <td><strong>{text(pick(leg, "symbol"))}</strong><small>{legId}</small></td>
          <td><span className={side.className}>{side.code}</span></td>
          <td>{text(pick(leg, "state", "status"))}</td>
          <td>{numberText(pick(leg, "quantity"))} / {numberText(pick(leg, "remaining_quantity", "remaining_qty"))}</td>
          <td>{money(pick(leg, "average_entry_price", "avg_entry_price"))} / {money(pick(leg, "mark_price"))}</td>
          <td>{money(pick(leg, "realized_pnl"))} / {money(pick(leg, "unrealized_pnl"))}</td>
          <td>{money(pick(leg, "fees"))} / {money(pick(leg, "funding"))}</td>
          <td>{text(pick(lineage, "trade_plan_id", "trade_plan_id"))}<small>{text(pick(lineage, "decision_id", "decision_id"))}</small></td>
          <td>{Object.keys(baseExit).length > 0 ? text(pick(baseExit, "type", "trigger"), "--") : "--"}</td>
          <td>{reconciliationStatus}{unsafe}</td>
          <td>{list(leg.orders).length} / {list(leg.fills).length}</td>
          <td>{text(pick(lineage, "reverse_of"))}</td>
        </tr>;
      })}</tbody>
    </table></div>
  </section>;
}
