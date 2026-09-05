import { useEffect, useMemo, useState, type ReactNode } from "react";
import { MarketChart } from "./components/MarketChart";
import { API_BASE_URL, getJson, sendJson, WS_URL } from "./api/client";
import { useKlines } from "./hooks/useKlines";
import { useTradingSnapshot } from "./hooks/useTradingSnapshot";
import type { ApiState, KlineInterval, Order, Position, TradingSnapshot } from "./types/api";

type Page = "trade" | "positions" | "orders" | "review" | "system";
type JsonRecord = Record<string, unknown>;

const pages: Array<[Page, string]> = [
  ["trade", "交易"], ["positions", "持仓"], ["orders", "订单"], ["review", "复盘"], ["system", "系统"],
];

const statusLabels: Record<ApiState<unknown>["status"], string> = {
  ready: "已连接", empty: "暂无数据", unavailable: "暂不可用", offline: "后端离线", error: "数据异常", loading: "加载中",
};

const sourceLabels: Record<string, string> = {
  HEALTHY: "实时", SYNTHETIC: "模拟", STALE: "延迟", UNAVAILABLE: "不可用", GEO_RESTRICTED: "地区限制", DEGRADED: "数据受限", INVALID: "数据异常",
};

const regimeLabels: Record<string, string> = {
  BULL: "上涨趋势", BEAR: "下跌趋势", RANGE: "震荡", HIGH_VOL: "高波动", EXTREME_RISK: "极端风险",
};

const okxValidationLabels: Record<string, string> = {
  AUTH_FAILED: "API 凭据验证失败",
  PERMISSION_DENIED: "API 权限不足，请确认已开启“读取 + 交易”",
  IP_RESTRICTED: "API IP 白名单限制",
  DEMO_ENV_MISMATCH: "API Key 与 OKX 模拟盘环境不匹配",
  TIME_OFFSET: "本机时间与 OKX 服务器时间偏差过大",
  RATE_LIMITED: "OKX 请求频率受限",
  OKX_UNAVAILABLE: "OKX 服务暂时不可用",
  NETWORK_ERROR: "无法连接 OKX",
  MALFORMED_RESPONSE: "OKX 返回异常数据",
  OKX_REJECTED: "OKX 拒绝请求",
};

function resolvePage(hash: string): Page {
  const value = hash.replace(/^#\/?/, "") as Page;
  return pages.some(([page]) => page === value) ? value : "trade";
}

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
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
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function numberText(value: unknown, digits = 2) {
  if (value === undefined || value === null || value === "") return "--";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString("zh-CN", { maximumFractionDigits: digits }) : "--";
}

function money(value: unknown) {
  const rendered = numberText(value, 2);
  return rendered === "--" ? rendered : `$${rendered}`;
}

function percent(value: unknown) {
  if (value === undefined || value === null || value === "") return "--";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "--";
  const normalized = Math.abs(parsed) <= 1 ? parsed * 100 : parsed;
  return `${normalized.toFixed(2)}%`;
}

function direction(value: unknown) {
  const side = String(value ?? "").toUpperCase();
  if (["BUY", "LONG"].includes(side)) return { label: "做多", code: "LONG", tone: "long" };
  if (["SELL", "SHORT"].includes(side)) return { label: "做空", code: "SHORT", tone: "short" };
  return { label: "观望", code: "--", tone: "neutral" };
}

function positionDirection(position: Position) {
  const quantity = Number(position.quantity);
  if (quantity > 0) return { label: "做多", code: "LONG", tone: "long" };
  if (quantity < 0) return { label: "做空", code: "SHORT", tone: "short" };
  return { label: "空仓", code: "--", tone: "neutral" };
}

function StateBadge({ source }: { source: ApiState<unknown> }) {
  return <span className={`state-badge ${source.status}`}>{statusLabels[source.status]}</span>;
}

function EmptyBlock({ source, unavailable = "数据接口暂未开放" }: { source: ApiState<unknown>; unavailable?: string }) {
  const label = source.status === "unavailable" ? unavailable : source.status === "offline" ? "后端离线" : source.status === "error" ? "数据加载异常" : source.status === "loading" ? "加载中" : "暂无数据";
  return <div className={`empty-block ${source.status}`}>{label}</div>;
}

function Panel({ title, source, action, children, className = "" }: { title: string; source?: ApiState<unknown>; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}><header className="panel-header"><h2>{title}</h2><div>{action}{source && <StateBadge source={source} />}</div></header>{children}</section>;
}

function Metric({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return <article className="metric"><span>{label}</span><strong className={tone}>{value}</strong></article>;
}

function OkxConnectionCard() {
  const [status, setStatus] = useState<JsonRecord>({});
  const [message, setMessage] = useState("正在读取连接状态…");
  const [busy, setBusy] = useState(false);

  const refreshStatus = async () => {
    const response = await getJson<JsonRecord>("/exchange/okx/status");
    if (response.status === "ready" && response.data) {
      setStatus(response.data);
      setMessage("");
    } else {
      setMessage(response.status === "unavailable" ? "当前后端未提供 OKX 凭据接口。" : "无法读取 OKX 连接状态。");
    }
  };

  useEffect(() => { void refreshStatus(); }, []);

  const validateCredentials = async () => {
    setBusy(true);
    const response = await sendJson<JsonRecord>("/exchange/okx/validate", "POST");
    setBusy(false);
    if (response.status === "ready" && response.data) {
      setStatus((current) => ({ ...current, ...response.data }));
      window.dispatchEvent(new Event("okx-status-changed"));
      const reason = String(response.data.reason_code ?? "OKX_REJECTED");
      const stage = response.data.stage ? `验证失败：${response.data.stage}\n` : "";
      setMessage(response.data.authenticated === true ? "OKX DEMO 验证成功。" : `${stage}${okxValidationLabels[reason] ?? "OKX 拒绝请求"}`);
    } else {
      setMessage("验证失败；请确认后端连接和 Access 权限。");
    }
  };

  const configured = status.configured === true;
  const health = text(status.health, configured ? "未验证" : "未配置");
  return <Panel title="OKX 交易所连接" className="okx-panel">
    <dl className="system-list okx-status"><div><dt>执行交易所</dt><dd>OKX</dd></div><div><dt>环境</dt><dd>模拟盘 DEMO</dd></div><div><dt>连接状态</dt><dd className="muted-status">{health}</dd></div><div><dt>凭据包</dt><dd>{configured ? "已配置（内容不可查看）" : "未配置"}</dd></div>{Boolean(status.reason_code) && <div><dt>验证状态</dt><dd className="muted-status">{okxValidationLabels[String(status.reason_code)] ?? "OKX 拒绝请求"}</dd></div>}</dl>
    <p className="form-hint">请在本机终端运行 <code>./scripts/okx-vault.sh save</code> 安全录入凭据。网页仅通过 Broker 验证连接。</p>
    <div className="form-actions"><button className="secondary-button" type="button" disabled={busy || !configured} onClick={() => void validateCredentials()}>{busy ? "验证中…" : "验证连接"}</button></div>
    {message && <p className="form-hint" role="status">{message}</p>}
  </Panel>;
}

function marketSource(snapshot: TradingSnapshot) {
  const market = record(snapshot.optional["/market"]?.data);
  const sources = record(snapshot.optional["/market/sources"]?.data);
  const candidates = [pick(market, "status", "health", "freshness"), pick(sources, "status")];
  for (const source of Object.values(sources)) candidates.push(pick(record(source), "status"));
  const values = candidates.filter(Boolean).map((value) => String(value).toUpperCase());
  for (const priority of ["GEO_RESTRICTED", "UNAVAILABLE", "STALE", "DEGRADED", "SYNTHETIC", "HEALTHY"]) if (values.includes(priority)) return priority;
  return snapshot.optional["/market"]?.status === "offline" ? "UNAVAILABLE" : "UNKNOWN";
}

function marketProvider(snapshot: TradingSnapshot, source: string) {
  const market = record(snapshot.optional["/market"]?.data);
  const dataSource = String(pick(market, "data_source", "source") ?? "").toUpperCase();
  return source === "SYNTHETIC" || dataSource.includes("SYNTHETIC") ? "后端模拟行情" : "Binance USDⓈ-M";
}

function StrategyRows({ snapshot }: { snapshot: TradingSnapshot }) {
  const payload = record(snapshot.optional["/strategies"]?.data);
  const strategies = list(payload.strategies);
  const names = strategies.length ? strategies : [
    { name: "trend" }, { name: "momentum" }, { name: "breakout" }, { name: "mean_reversion" }, { name: "funding_basis" },
  ];
  const labels: Record<string, string> = { trend: "趋势", momentum: "动量", breakout: "突破", mean_reversion: "均值回归", funding_basis: "资金 / 基差" };
  return <div className="strategy-list">{names.slice(0, 5).map((item, index) => {
    const name = String(item.name ?? `strategy-${index}`);
    const vote = direction(pick(item, "side", "direction", "vote"));
    return <div key={name}><span>{labels[name.toLowerCase()] ?? name}</span><b className={vote.tone}>{vote.code === "--" ? "--" : vote.label}</b><em>{percent(pick(item, "confidence"))}</em></div>;
  })}</div>;
}

function WeightRows({ snapshot }: { snapshot: TradingSnapshot }) {
  const payload = record(snapshot.optional["/strategies"]?.data);
  const weighted = list(payload.strategies).filter((item) => pick(item, "effective_weight", "weight") !== undefined);
  if (!weighted.length) return <p className="muted-line">有效权重暂无数据</p>;
  return <div className="weights">{weighted.slice(0, 5).map((item, index) => {
    const value = Number(pick(item, "effective_weight", "weight"));
    const normalized = Number.isFinite(value) ? Math.min(100, Math.max(0, Math.abs(value) <= 1 ? value * 100 : value)) : 0;
    return <div key={String(item.name ?? index)}><span>{text(item.name)}</span><i><b style={{ width: `${normalized}%` }} /></i><em>{Number.isFinite(value) ? `${normalized.toFixed(0)}%` : "--"}</em></div>;
  })}</div>;
}

function CurrentPosition({ snapshot, compact = false }: { snapshot: TradingSnapshot; compact?: boolean }) {
  const positions = Object.values(snapshot.positions.data ?? {}).filter((item) => Number(item.quantity) !== 0);
  if (snapshot.positions.status !== "ready" || !positions.length) return <div className="position-empty">当前无持仓</div>;
  const position = positions[0];
  const side = positionDirection(position);
  const market = record(snapshot.optional["/market"]?.data);
  return <div className={`current-position ${compact ? "compact" : ""}`}><div className="position-title"><strong>{position.symbol}</strong><span className={side.tone}>{side.code}</span><b>{numberText(Math.abs(Number(position.quantity)), 8)} BTC</b></div><dl><div><dt>入场价</dt><dd>{money(position.avg_entry_price)}</dd></div><div><dt>标记价格</dt><dd>{money(pick(market, "mark_price", "price"))}</dd></div><div><dt>未实现盈亏</dt><dd>--</dd></div><div><dt>已实现盈亏</dt><dd>{money(position.realized_pnl)}</dd></div><div><dt>杠杆</dt><dd>--</dd></div><div><dt>爆仓距离</dt><dd>--</dd></div></dl></div>;
}

function TradePage({ snapshot }: { snapshot: TradingSnapshot }) {
  const marketState = snapshot.optional["/market"] ?? { status: "loading" as const };
  const market = record(marketState.data);
  const source = marketSource(snapshot);
  const sourceLabel = sourceLabels[source] ?? "状态未知";
  const provider = marketProvider(snapshot, source);
  const signals = list(record(snapshot.optional["/signals"]?.data).signals);
  const signal = signals[0] ?? {};
  const regime = record(snapshot.optional["/regime"]?.data);
  const risk = record(snapshot.optional["/risk"]?.data);
  const riskConfig = record(risk.risk_config);
  const decision = direction(pick(signal, "side", "direction", "decision"));
  const positions = Object.values(snapshot.positions.data ?? {}).filter((item) => Number(item.quantity) !== 0);
  const current = positions[0];
  const kline = useKlines(snapshot.lastEvent, snapshot.websocket);
  const klineHealthy = kline.state.status === "ready" && kline.state.data?.status === "HEALTHY";
  const klineProvider = klineHealthy && kline.state.data?.source === "OKX" ? "OKX" : provider;
  const klineSourceLabel = klineHealthy && kline.state.data?.source === "OKX" ? "实时" : sourceLabel;
  const priceAllowed = !["UNAVAILABLE", "GEO_RESTRICTED", "UNKNOWN"].includes(source);

  return <>
    <section className="metrics" aria-label="核心指标">
      <Metric label="账户净值" value={money(snapshot.account.data?.equity)} />
      <Metric label="今日盈亏" value="--" />
      <Metric label="当前仓位" value={current ? `${positionDirection(current).code} ${numberText(Math.abs(Number(current.quantity)), 8)} BTC` : "空仓"} tone={current ? positionDirection(current).tone : ""} />
      <Metric label="当前回撤" value={percent(pick(risk, "current_drawdown", "drawdown"))} />
      <Metric label="有效杠杆" value={pick(risk, "effective_leverage") === undefined ? "--" : `${numberText(risk.effective_leverage)}x`} />
    </section>
    <section className="trading-workspace">
      <Panel title="BTCUSDT 行情" className="market-panel" action={<span className={`source-badge ${source.toLowerCase()}`}>{sourceLabel}</span>}>
        <div className="market-source-header"><strong>BTCUSDT</strong><span>行情源：{klineProvider} · {klineSourceLabel}</span><span>执行交易所：OKX 模拟盘 DEMO</span></div>
        <div className="market-strip"><div><strong>{priceAllowed ? money(pick(market, "price", "last_price")) : "--"}</strong><span>当前价格</span></div><div><b>{priceAllowed ? money(market.mark_price) : "--"}</b><span>标记价格</span></div><div><b>{priceAllowed ? money(market.index_price) : "--"}</b><span>指数价格</span></div><div><b>{percent(pick(market, "price_change_percent_24h", "change_24h"))}</b><span>24H 涨跌</span></div><div><b>{percent(market.funding_rate)}</b><span>资金费率</span></div><div><b>{numberText(market.open_interest, 2)}</b><span>未平仓量 OI</span></div></div>
        <div className="market-details"><span>买一 <b>{priceAllowed ? money(market.best_bid) : "--"}</b></span><span>卖一 <b>{priceAllowed ? money(market.best_ask) : "--"}</b></span><span>Spread <b>{priceAllowed ? numberText(market.spread, 4) : "--"}</b></span><span>Basis <b>{percent(market.basis)}</b></span></div>
        <div className="chart-toolbar"><div>{kline.intervals.map((value) => <button key={value} type="button" aria-pressed={kline.interval === value} disabled={!kline.supportedIntervals.includes(value)} onClick={() => kline.setInterval(value as KlineInterval)}>{value}</button>)}</div><span>{snapshot.websocket === "connected" ? "WebSocket 已连接" : "实时同步中断"}</span></div>
        <MarketChart source={kline.state} websocket={snapshot.websocket} />
      </Panel>
      <aside className="decision-column">
        <Panel title="当前判断" source={snapshot.optional["/signals"]} className="decision-panel">
          <div className={`decision ${decision.tone}`}><strong>{decision.label}</strong><span>{decision.code}</span></div>
          <dl className="decision-facts"><div><dt>置信度</dt><dd>{percent(signal.confidence)}</dd></div><div><dt>市场状态</dt><dd>{regimeLabels[String(regime.regime ?? "").toUpperCase()] ?? "--"}</dd></div><div><dt>建议仓位</dt><dd>{text(pick(signal, "suggested_position", "position_size"))}</dd></div><div><dt>建议杠杆</dt><dd>{pick(signal, "leverage", "risk_capped_leverage") === undefined ? "--" : `${numberText(pick(signal, "leverage", "risk_capped_leverage"))}x`}</dd></div><div><dt>风险等级</dt><dd>{text(pick(signal, "risk_level"))}</dd></div></dl>
          <h3>策略共识</h3><StrategyRows snapshot={snapshot} />
          <h3>有效权重</h3><WeightRows snapshot={snapshot} />
          <details className="why"><summary>为什么？</summary><dl><div><dt>市场阶段 Regime</dt><dd>{text(regime.regime)}</dd></div><div><dt>原因代码</dt><dd>{Array.isArray(signal.reasons) ? signal.reasons.join("、") || "--" : "--"}</dd></div><div><dt>原始置信度</dt><dd>{percent(pick(signal, "raw_confidence", "confidence"))}</dd></div><div><dt>校准置信度</dt><dd>{percent(signal.calibrated_confidence)}</dd></div><div><dt>风控后杠杆</dt><dd>{text(signal.risk_capped_leverage)}</dd></div><div><dt>复核结果</dt><dd>{text(signal.review_result)}</dd></div><div><dt>压力测试</dt><dd>{text(signal.stress_result)}</dd></div></dl></details>
        </Panel>
      </aside>
    </section>
    <section className="lower-workspace">
      <Panel title="当前持仓" source={snapshot.positions}><CurrentPosition snapshot={snapshot} compact /></Panel>
      <Panel title="风险状态" source={snapshot.optional["/risk"]}><dl className="risk-grid"><div><dt>当前回撤</dt><dd>{percent(pick(risk, "current_drawdown", "drawdown"))}</dd></div><div><dt>风险乘数</dt><dd>{numberText(pick(risk, "risk_multiplier"))}</dd></div><div><dt>有效杠杆</dt><dd>{numberText(pick(risk, "effective_leverage"))}</dd></div><div><dt>保证金率</dt><dd>{percent(pick(risk, "margin_ratio"))}</dd></div><div><dt>爆仓距离</dt><dd>--</dd></div><div><dt>Kill Switch</dt><dd className={Boolean(record(risk.kill_switch).enabled ?? snapshot.killswitch.data?.enabled) ? "danger" : "safe"}>{Boolean(record(risk.kill_switch).enabled ?? snapshot.killswitch.data?.enabled) ? "交易已停止" : "安全"}</dd></div></dl><p className="risk-note">最大杠杆配置：{text(pick(riskConfig, "max_leverage"))}</p></Panel>
    </section>
  </>;
}

function PositionsPage({ snapshot }: { snapshot: TradingSnapshot }) {
  const rows = Object.values(snapshot.positions.data ?? {});
  const market = record(snapshot.optional["/market"]?.data);
  return <Panel title="持仓明细" source={snapshot.positions}>{snapshot.positions.status !== "ready" || !rows.length ? <EmptyBlock source={snapshot.positions} /> : <div className="table-wrap"><table><thead><tr><th>交易对</th><th>方向</th><th>数量</th><th>入场价</th><th>标记价格</th><th>未实现盈亏</th><th>已实现盈亏</th><th>杠杆</th><th>爆仓价</th></tr></thead><tbody>{rows.map((position) => { const side = positionDirection(position); return <tr key={position.symbol}><td><strong>{position.symbol}</strong></td><td><span className={side.tone}>{side.code}</span></td><td>{numberText(Math.abs(Number(position.quantity)), 8)}</td><td>{money(position.avg_entry_price)}</td><td>{money(pick(market, "mark_price", "price"))}</td><td>--</td><td>{money(position.realized_pnl)}</td><td>--</td><td>--</td></tr>; })}</tbody></table></div>}</Panel>;
}

const orderStatus: Record<string, string> = { NEW: "待成交", OPEN: "挂单中", PARTIALLY_FILLED: "部分成交", FILLED: "已成交", CANCELLED: "已取消", REJECTED: "已拒绝", EXPIRED: "已过期", UNKNOWN: "状态未知" };

function OrdersPage({ snapshot }: { snapshot: TradingSnapshot }) {
  const rows = snapshot.orders.data ?? [];
  return <Panel title="订单记录" source={snapshot.orders}>{snapshot.orders.status !== "ready" || !rows.length ? <EmptyBlock source={snapshot.orders} /> : <div className="order-list"><div className="order-head"><span>时间</span><span>交易对</span><span>方向</span><span>类型</span><span>价格</span><span>数量 / 成交</span><span>状态</span></div>{rows.map((order: Order) => <details className={`order-row ${order.status === "UNKNOWN" ? "unknown" : ""}`} key={order.internal_order_id}><summary><time>{new Date(order.updated_at).toLocaleString("zh-CN")}</time><strong>{order.symbol}</strong><span className={direction(order.side).tone}>{direction(order.side).code}</span><span>{order.order_type}</span><span>{money(order.price)}</span><span>{numberText(order.quantity, 8)} / {numberText(order.filled_quantity, 8)}</span><b>{orderStatus[order.status] ?? order.status}</b></summary><div><span>内部订单 ID：{order.internal_order_id}</span><span>客户端订单 ID：{order.client_order_id}</span></div></details>)}</div>}</Panel>;
}

function ReviewPage({ snapshot }: { snapshot: TradingSnapshot }) {
  const dailyState = snapshot.optional["/daily-reviews"] ?? { status: "loading" as const };
  const daily = list(record(dailyState.data).daily_reviews)[0] ?? {};
  const learningState = snapshot.optional["/learning"] ?? { status: "loading" as const };
  const learning = record(learningState.data);
  const fast = record(learning.fast_learning);
  const candidates = Array.isArray(learning.slow_learning_candidates) ? learning.slow_learning_candidates : [];
  const factual = record(learning.factual);
  return <div className="review-layout"><Panel title="今日表现" source={dailyState}><div className="review-metrics"><Metric label="PnL" value={money(pick(daily, "daily_pnl", "pnl", "net_pnl"))} /><Metric label="胜率" value={percent(pick(daily, "win_rate"))} /><Metric label="Profit Factor" value={numberText(pick(daily, "profit_factor"))} /><Metric label="最大回撤" value={percent(pick(daily, "max_drawdown"))} /><Metric label="交易次数" value={numberText(pick(daily, "trade_count", "trades"), 0)} /><Metric label="手续费 / Funding" value={money(pick(daily, "fees", "funding"))} /></div></Panel><Panel title="策略表现" source={dailyState}>{dailyState.status === "ready" && Object.keys(daily).length ? <p className="muted-line">后端尚未提供结构化的分策略表现字段</p> : <EmptyBlock source={dailyState} unavailable="复盘接口暂未开放" />}</Panel><Panel title="系统学习" source={learningState}><dl className="learning-grid"><div><dt>快速学习</dt><dd>{Object.keys(fast).length ? "已更新" : "--"}</dd></div><div><dt>慢速学习候选模型</dt><dd>{candidates.length ? candidates.map(String).join("、") : "--"}</dd></div><div><dt>事实复盘</dt><dd>{text(pick(factual, "status"))}</dd></div><div><dt>已复盘 Episode</dt><dd>{numberText(pick(factual, "review_count"), 0)}</dd></div></dl></Panel><Panel title="失败记忆" source={dailyState}><p className="muted-line">本日主要问题暂无结构化统计</p><button className="text-button" type="button" disabled>查看全部</button></Panel></div>;
}

function SystemPage({ snapshot }: { snapshot: TradingSnapshot }) {
  const runtime = record(snapshot.runtime.data);
  const exchange = record(snapshot.optional["/exchange-health"]?.data);
  const version = record(snapshot.optional["/version"]?.data);
  const source = marketSource(snapshot);
  const execution = record(exchange.execution);
  const marketStatus = String(pick(record(exchange.market_data), "status") ?? source).toUpperCase();
  const okxOverview = execution.authenticated === true && execution.status === "HEALTHY" ? "已连接" : execution.configured === true ? "已配置" : execution.status === "DEGRADED" ? "异常" : "未配置";
  return <div className="system-grid"><Panel title="连接状态"><dl className="system-list"><div><dt>后端 API</dt><dd>{statusLabels[snapshot.health.status]}</dd></div><div><dt>WebSocket</dt><dd>{snapshot.websocket === "connected" ? "已连接" : snapshot.websocket === "connecting" ? "连接中" : "已断开"}</dd></div><div><dt>K线行情</dt><dd>{source === "HEALTHY" ? "OKX 实时" : sourceLabels[source] ?? "状态未知"}</dd></div><div><dt>OKX 公开行情</dt><dd>{sourceLabels[marketStatus] ?? "状态未知"}</dd></div><div><dt>OKX Demo</dt><dd className="muted-status">{okxOverview}</dd></div><div><dt>数据库</dt><dd>{text(pick(runtime, "database"))}</dd></div><div><dt>Scheduler</dt><dd>{text(pick(runtime, "scheduler"))}</dd></div><div><dt>Learning</dt><dd>{statusLabels[(snapshot.optional["/learning"] ?? { status: "loading" }).status]}</dd></div></dl></Panel><OkxConnectionCard /><Panel title="运行信息"><dl className="system-list"><div><dt>Adapter</dt><dd>{text(exchange.adapter)}</dd></div><div><dt>Daily Review</dt><dd>{statusLabels[(snapshot.optional["/daily-reviews"] ?? { status: "loading" }).status]}</dd></div><div><dt>Git SHA</dt><dd>{text(version.git_sha)}</dd></div><div><dt>环境</dt><dd>{text(version.environment, "本地")}</dd></div></dl></Panel><Panel title="接口地址" className="system-addresses"><p>API：{API_BASE_URL}</p><p>WebSocket：{WS_URL}</p></Panel></div>;
}

function PageContent({ page, snapshot }: { page: Page; snapshot: TradingSnapshot }) {
  if (page === "trade") return <TradePage snapshot={snapshot} />;
  if (page === "positions") return <PositionsPage snapshot={snapshot} />;
  if (page === "orders") return <OrdersPage snapshot={snapshot} />;
  if (page === "review") return <ReviewPage snapshot={snapshot} />;
  return <SystemPage snapshot={snapshot} />;
}

export default function App() {
  const [page, setPage] = useState<Page>(() => resolvePage(window.location.hash));
  const { snapshot, refresh } = useTradingSnapshot();
  useEffect(() => { const update = () => setPage(resolvePage(window.location.hash)); window.addEventListener("hashchange", update); return () => window.removeEventListener("hashchange", update); }, []);
  const offline = snapshot.health.status === "offline";
  const runtime = record(snapshot.runtime.data);
  const source = marketSource(snapshot);
  const provider = marketProvider(snapshot, source);
  const okx = record(snapshot.optional["/exchange/okx/status"]?.data);
  const okxConnected = okx.authenticated === true && okx.status === "HEALTHY";
  const okxLabel = okxConnected ? "OKX Demo：已连接" : okx.configured === true ? "OKX Demo：已配置" : "OKX Demo：未配置";
  const topStates = useMemo(() => [
    { label: String(pick(runtime, "state", "runtime_state", "engine") ?? "").toUpperCase() === "RUNNING" ? "系统运行中" : "系统待机", ok: String(pick(runtime, "state", "runtime_state") ?? "").toUpperCase() === "RUNNING" },
    { label: sourceLabels[source] ? `${provider.replace(" USDⓈ-M", "")}：${sourceLabels[source]}` : `${provider.replace(" USDⓈ-M", "")}：状态未知`, ok: source === "HEALTHY" },
    { label: okxLabel, ok: okxConnected },
    { label: snapshot.websocket === "connected" ? "WebSocket 已连接" : "WebSocket 未连接", ok: snapshot.websocket === "connected" },
  ], [runtime, snapshot.websocket, source, provider, okxLabel, okxConnected]);

  return <div className="terminal-shell"><header className="terminal-topbar"><div className="identity"><span className="logo">CQ</span><div><strong>量化交易</strong><small>自动交易系统</small></div></div><strong className="symbol">BTCUSDT</strong><div className="top-status"><span className="mode">PAPER</span><span>本地</span>{topStates.map((item) => <span className={item.ok ? "ok" : ""} key={item.label}><i />{item.label}</span>)}</div></header><nav className="primary-nav" aria-label="主导航">{pages.map(([id, label]) => <a key={id} href={`#/${id}`} aria-current={page === id ? "page" : undefined}>{label}</a>)}</nav><main>{offline && <section className="offline-notice" role="alert"><div><strong>后端离线</strong><span>本地 API 暂时不可用，页面会自动重试。</span></div><button type="button" onClick={() => void refresh()}>立即重试</button></section>}<PageContent page={page} snapshot={snapshot} /></main><footer>仅用于 PAPER 模拟交易研究，不连接真实资金，不构成投资建议。</footer></div>;
}
