import { useEffect, useMemo, useState } from "react";
import { getJson } from "../api/client";
import "../styles/market-intelligence-dock.css";

type JsonRecord = Record<string, unknown>;
type AnalysisPayload = {
  status?: string;
  symbol?: string;
  source?: string;
  market?: JsonRecord;
  technical_indicators?: JsonRecord;
  technical_indicator_authority?: string;
  opportunity_ranking?: JsonRecord[];
  opportunity_authority?: string;
  history?: JsonRecord;
};

type HistoryPayload = {
  status?: string;
  source?: string;
  dataset?: string;
  symbol?: string;
  interval?: string | null;
  rows?: JsonRecord[];
  next_after?: string | null;
  reason_code?: string;
  last_error?: string;
};

type Tab = "market" | "technical" | "history";
type Dataset = "candles" | "trades" | "funding" | "index_candles" | "mark_price_candles";

const DATASETS: Array<[Dataset, string]> = [
  ["candles", "交易价 K 线"],
  ["trades", "历史成交"],
  ["funding", "Funding 历史"],
  ["index_candles", "指数 K 线"],
  ["mark_price_candles", "标记价 K 线"],
];

const INTERVALS = ["1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "2d", "3d", "1w", "1M", "3M"];

const MARKET_GROUPS: Array<[string, Array<[string, string, "price" | "percent" | "number" | "time" | "raw"]>]> = [
  ["价格与 24H", [
    ["price", "当前价格", "price"], ["mark_price", "标记价格", "price"], ["index_price", "指数价格", "price"],
    ["open_24h", "24H 开盘", "price"], ["high_24h", "24H 最高", "price"], ["low_24h", "24H 最低", "price"],
    ["price_change_24h", "24H 涨跌额", "price"], ["price_change_percent_24h", "24H 涨跌幅", "percent"],
    ["open_utc0", "UTC0 开盘", "price"], ["open_utc8", "UTC8 开盘", "price"],
  ]],
  ["订单簿 / 流动性", [
    ["best_bid", "买一", "price"], ["best_ask", "卖一", "price"], ["best_bid_size", "买一量", "number"],
    ["best_ask_size", "卖一量", "number"], ["last_size", "最新成交量", "number"], ["spread", "Spread", "number"],
    ["depth", "Orderbook Depth", "number"], ["imbalance", "Orderbook Imbalance", "percent"],
  ]],
  ["成交量", [
    ["volume_24h", "24H 合约成交量", "number"], ["volume_ccy_24h", "24H 币本位成交量", "number"],
    ["volume", "当前成交量字段", "number"], ["trade_volume", "近期成交量", "number"],
  ]],
  ["衍生品", [
    ["funding_rate", "Funding Rate", "percent"], ["next_funding_time", "下次 Funding", "time"], ["basis", "Basis", "percent"],
    ["open_interest", "OI 合约数", "number"], ["open_interest_ccy", "OI 币本位", "number"], ["open_interest_usd", "OI USD", "price"],
    ["open_interest_change", "OI 变化", "number"], ["realized_volatility", "Realized Volatility", "percent"],
  ]],
  ["数据健康", [
    ["exchange", "Exchange", "raw"], ["source", "Source", "raw"], ["health", "Health", "raw"], ["freshness", "Freshness", "raw"],
    ["exchange_timestamp", "Exchange Timestamp", "time"], ["received_timestamp", "Received Timestamp", "time"],
    ["new_risk_allowed", "New Risk Allowed", "raw"], ["new_risk_block_reason", "Risk Block Reason", "raw"],
  ]],
];

const TECH_GROUPS: Array<[string, RegExp]> = [
  ["均线 / 趋势", /^(sma_|ema_|price_vs_ema|tenkan_|kijun_|senkou_)/],
  ["动量", /^(rsi_|macd_|stochastic_|williams_|cci_|roc_|momentum_)/],
  ["波动率 / 通道", /^(bollinger_|atr_|adx_|plus_di_|minus_di_|donchian_|keltner_|realized_volatility|zscore_)/],
  ["量能 / 资金流", /^(obv$|mfi_|vwap_|volume_ratio_)/],
  ["结构 / 支撑阻力", /^(recent_support_|recent_resistance_)/],
];

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
}

function isAvailable(value: unknown) {
  return value !== undefined && value !== null && value !== "";
}

function number(value: unknown, digits = 6) {
  if (!isAvailable(value)) return "NOT_AVAILABLE";
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString("zh-CN", { maximumFractionDigits: digits })
    : String(value);
}

function price(value: unknown) {
  if (!isAvailable(value)) return "NOT_AVAILABLE";
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? `$${parsed.toLocaleString("zh-CN", { maximumFractionDigits: 8 })}`
    : String(value);
}

function percent(value: unknown) {
  if (!isAvailable(value)) return "NOT_AVAILABLE";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return `${(Math.abs(parsed) <= 1 ? parsed * 100 : parsed).toFixed(4)}%`;
}

function time(value: unknown) {
  if (!isAvailable(value)) return "NOT_AVAILABLE";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN");
}

function raw(value: unknown) {
  if (!isAvailable(value)) return "NOT_AVAILABLE";
  if (typeof value === "boolean") return value ? "YES" : "NO";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function format(value: unknown, kind: "price" | "percent" | "number" | "time" | "raw" = "number") {
  if (kind === "price") return price(value);
  if (kind === "percent") return percent(value);
  if (kind === "time") return time(value);
  if (kind === "raw") return raw(value);
  return number(value);
}

function prettifyIndicator(key: string) {
  return key
    .replaceAll("_", " ")
    .replace(/\bema\b/gi, "EMA")
    .replace(/\bsma\b/gi, "SMA")
    .replace(/\brsi\b/gi, "RSI")
    .replace(/\bmacd\b/gi, "MACD")
    .replace(/\bat[r]?\b/gi, (match) => match.toUpperCase())
    .replace(/\badx\b/gi, "ADX")
    .replace(/\bvwap\b/gi, "VWAP")
    .replace(/\bobv\b/gi, "OBV")
    .replace(/\bmfi\b/gi, "MFI")
    .replace(/\bcci\b/gi, "CCI")
    .replace(/\broc\b/gi, "ROC")
    .replace(/\bdi\b/gi, "DI")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function MarketMetric({ label, value, kind = "number" }: { label: string; value: unknown; kind?: "price" | "percent" | "number" | "time" | "raw" }) {
  const rendered = format(value, kind);
  const tone = kind === "percent" && rendered !== "NOT_AVAILABLE"
    ? Number(value) > 0 ? "positive" : Number(value) < 0 ? "negative" : ""
    : "";
  return <div className="mi-metric"><span>{label}</span><strong className={tone}>{rendered}</strong></div>;
}

function IndicatorGrid({ indicators }: { indicators: JsonRecord }) {
  const assigned = new Set<string>();
  const groups = TECH_GROUPS.map(([title, pattern]) => {
    const entries = Object.entries(indicators).filter(([key]) => pattern.test(key));
    entries.forEach(([key]) => assigned.add(key));
    return [title, entries] as const;
  });
  const other = Object.entries(indicators).filter(([key]) => !assigned.has(key));
  if (other.length) groups.push(["其他指标", other]);
  if (!Object.keys(indicators).length) return <div className="mi-empty">NOT_AVAILABLE</div>;

  return <div className="mi-tech-groups">
    {groups.filter(([, entries]) => entries.length).map(([title, entries]) => (
      <section className="mi-section" key={title}>
        <h4>{title}</h4>
        <div className="mi-grid technical">
          {entries.map(([key, value]) => <MarketMetric key={key} label={prettifyIndicator(key)} value={value} />)}
        </div>
      </section>
    ))}
  </div>;
}

function HistoryTable({ dataset, rows }: { dataset: Dataset; rows: JsonRecord[] }) {
  if (!rows.length) return <div className="mi-empty">暂无历史数据 / NOT_AVAILABLE</div>;
  if (dataset === "trades") {
    return <div className="mi-table-wrap"><table><thead><tr><th>时间</th><th>方向</th><th>价格</th><th>数量</th><th>Trade ID</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${raw(row.trade_id)}-${index}`}><td>{time(row.timestamp)}</td><td>{raw(row.side)}</td><td>{price(row.price)}</td><td>{number(row.size)}</td><td>{raw(row.trade_id)}</td></tr>)}</tbody></table></div>;
  }
  if (dataset === "funding") {
    return <div className="mi-table-wrap"><table><thead><tr><th>时间</th><th>Funding Rate</th><th>Realized Rate</th><th>Formula</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${raw(row.timestamp_ms)}-${index}`}><td>{time(row.timestamp)}</td><td>{percent(row.funding_rate)}</td><td>{percent(row.realized_rate)}</td><td>{raw(row.formula_type)}</td></tr>)}</tbody></table></div>;
  }
  return <div className="mi-table-wrap"><table><thead><tr><th>时间</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th><th>币本位</th><th>Quote</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${raw(row.timestamp_ms)}-${index}`}><td>{time(row.timestamp)}</td><td>{price(row.open)}</td><td>{price(row.high)}</td><td>{price(row.low)}</td><td>{price(row.close)}</td><td>{number(row.volume)}</td><td>{number(row.volume_ccy)}</td><td>{number(row.volume_quote)}</td></tr>)}</tbody></table></div>;
}

export function MarketIntelligenceDock() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("market");
  const [analysis, setAnalysis] = useState<AnalysisPayload | null>(null);
  const [analysisStatus, setAnalysisStatus] = useState("IDLE");
  const [dataset, setDataset] = useState<Dataset>("candles");
  const [interval, setInterval] = useState("1m");
  const [history, setHistory] = useState<HistoryPayload | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let active = true;
    const load = async () => {
      const response = await getJson<AnalysisPayload>("/market/analysis?symbol=BTCUSDT");
      if (!active) return;
      if (response.status === "ready" && response.data) {
        setAnalysis(response.data);
        setAnalysisStatus(String(response.data.status ?? "OK"));
      } else {
        setAnalysisStatus(response.status.toUpperCase());
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [open]);

  const market = asRecord(analysis?.market);
  const technical = asRecord(analysis?.technical_indicators);
  const indicators = asRecord(technical.indicators);
  const ranking = Array.isArray(analysis?.opportunity_ranking) ? analysis.opportunity_ranking : [];
  const indicatorCount = useMemo(() => Object.keys(indicators).length, [indicators]);
  const isCandleDataset = dataset.endsWith("candles");

  const loadHistory = async (loadEarlier = false) => {
    setHistoryBusy(true);
    const params = new URLSearchParams({ dataset, symbol: "BTCUSDT", limit: "100" });
    if (isCandleDataset) params.set("interval", interval);
    if (loadEarlier && history?.next_after) params.set("after", history.next_after);
    const response = await getJson<HistoryPayload>(`/market/history?${params.toString()}`);
    setHistoryBusy(false);
    if (response.status !== "ready" || !response.data) {
      setHistory({ status: response.status.toUpperCase(), dataset, rows: [] });
      return;
    }
    const next = response.data;
    if (loadEarlier && history?.rows) {
      setHistory({ ...next, rows: [...history.rows, ...(next.rows ?? [])] });
    } else {
      setHistory(next);
    }
  };

  return <>
    <button className="mi-launcher" type="button" onClick={() => setOpen(true)} aria-label="打开 OKX 市场分析">
      <span>OKX</span><strong>市场分析</strong>
    </button>
    {open && <div className="mi-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <section className="mi-drawer" role="dialog" aria-modal="true" aria-label="OKX 市场分析">
        <header className="mi-header">
          <div><p>REAL MARKET INTELLIGENCE</p><h2>OKX 市场分析 · BTCUSDT</h2><span>数据、量化与技术指标只作为 AI 证据，不拥有交易决定权。</span></div>
          <div className="mi-header-actions"><span className="mi-live">{analysisStatus}</span><button type="button" onClick={() => setOpen(false)}>关闭</button></div>
        </header>
        <div className="mi-doctrine"><strong>ADVISORY · 仅供 AI 参考</strong><span>Quant measures · AI decides · Risk protects · Execution executes</span></div>
        <nav className="mi-tabs">
          <button className={tab === "market" ? "active" : ""} onClick={() => setTab("market")} type="button">OKX 全量实时数据</button>
          <button className={tab === "technical" ? "active" : ""} onClick={() => setTab("technical")} type="button">技术指标 {indicatorCount ? `(${indicatorCount})` : ""}</button>
          <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")} type="button">OKX 历史数据</button>
        </nav>

        <div className="mi-content">
          {tab === "market" && <>
            {!Object.keys(market).length ? <div className="mi-empty">市场状态暂不可用 / NOT_AVAILABLE</div> : MARKET_GROUPS.map(([title, fields]) => <section className="mi-section" key={title}><h4>{title}</h4><div className="mi-grid">{fields.map(([key, label, kind]) => <MarketMetric key={key} label={label} value={market[key]} kind={kind} />)}</div></section>)}
            <section className="mi-section"><h4>量化机会观察 <span className="mi-advisory">ADVISORY</span></h4>{ranking.length ? <div className="mi-ranking">{ranking.map((item, index) => <div key={`${raw(item.symbol)}-${index}`}><strong>#{index + 1} {raw(item.symbol)}</strong><span>score {number(item.score, 4)}</span><span>{raw(item.direction)}</span><small>{raw(item.reason)}</small></div>)}</div> : <div className="mi-empty">当前没有 Opportunity Ranking；不会因此阻止 AI 分析。</div>}</section>
            <details className="mi-raw"><summary>查看 MarketState 全部原始字段</summary><div className="mi-grid raw">{Object.entries(market).map(([key, value]) => <MarketMetric key={key} label={key} value={value} kind="raw" />)}</div></details>
          </>}

          {tab === "technical" && <>
            <section className="mi-summary"><div><span>Authority</span><strong>{raw(technical.authority ?? analysis?.technical_indicator_authority)}</strong></div><div><span>Status</span><strong>{raw(technical.status)}</strong></div><div><span>Sample Count</span><strong>{number(technical.sample_count, 0)}</strong></div><div><span>Available Indicators</span><strong>{number(technical.available_indicator_count ?? indicatorCount, 0)}</strong></div></section>
            <IndicatorGrid indicators={indicators} />
            <p className="mi-footnote">任何 RSI / MACD / EMA / ADX / ATR / Bollinger / VWAP / OI / Funding 等数值都不能单独阻止 Chief Trader。缺少真实历史时显示 NOT_AVAILABLE。</p>
          </>}

          {tab === "history" && <>
            <section className="mi-history-toolbar">
              <label>数据集<select value={dataset} onChange={(event) => { setDataset(event.target.value as Dataset); setHistory(null); }}>{DATASETS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              {isCandleDataset && <label>周期<select value={interval} onChange={(event) => { setInterval(event.target.value); setHistory(null); }}>{INTERVALS.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>}
              <button type="button" disabled={historyBusy} onClick={() => void loadHistory(false)}>{historyBusy ? "加载中…" : "读取 OKX 历史"}</button>
              <span>按需分页读取，不把多年历史一次塞入实时 AI 上下文。</span>
            </section>
            {history && <><div className="mi-history-status"><span>Source: {raw(history.source ?? "OKX")}</span><span>Status: {raw(history.status)}</span><span>Rows: {number(history.rows?.length ?? 0, 0)}</span>{history.reason_code && <span>{history.reason_code}</span>}</div><HistoryTable dataset={dataset} rows={history.rows ?? []} />{history.next_after && <button className="mi-load-more" type="button" disabled={historyBusy} onClick={() => void loadHistory(true)}>{historyBusy ? "加载中…" : "加载更早 100 条"}</button>}{history.last_error && <p className="mi-error">{history.last_error}</p>}</>}
            {!history && <div className="mi-empty">选择数据集后点击“读取 OKX 历史”。历史数据不会自动大批量下载。</div>}
          </>}
        </div>
      </section>
    </div>}
  </>;
}
