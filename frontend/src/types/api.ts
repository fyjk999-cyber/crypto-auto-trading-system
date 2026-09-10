export type ApiState<T> = {
  status: "loading" | "ready" | "empty" | "unavailable" | "offline" | "error";
  data?: T;
  message?: string;
};

export type ValuationBatch = {
  valuation_id: string | null;
  account_id: string;
  currency: string;
  quality: string;
  raw_mtm_equity: string | null;
  available_margin: string | null;
  adjusted_equity: string | null;
  peak_adjusted_equity: string | null;
  drawdown_amount: string | null;
  drawdown_ratio: string | null;
  market_as_of: string | null;
  valuation_as_of?: string | null;
  ledger_watermark: string | null;
  position_snapshot_ref: string | null;
  missing_marks: string[];
  stale_marks: string[];
  components?: Array<Record<string, unknown>>;
  solvency: string | null;
  reason_codes: string[];
};

export type Account = {
  account_id: string;
  mode: string;
  balances: Record<string, { currency: string; total: string; available: string; frozen: string }>;
  equity: string;
  margin_used: string;
  updated_at?: string | null;
  valuation?: ValuationBatch | null;
};

export type DailyReviewRun = {
  date: string;
  status: "PENDING" | "RUNNING" | "FAILED" | "SUCCEEDED" | string;
  daily_pnl: string;
  trade_count: number;
  episode_count: number;
  attempt_count: number;
  win_rate: string;
  profit_factor: string;
  owner?: string | null;
  claim_deadline_at?: string | null;
  last_error_type?: string | null;
};

export type Position = {
  symbol: string;
  base_asset?: string;
  quantity: string;
  avg_entry_price?: string | null;
  mark_price?: string | null;
  unrealized_pnl?: string | null;
  cost_basis: string;
  realized_pnl: string;
  leverage?: string;
  updated_at?: string | null;
};

export type Order = {
  internal_order_id: string;
  client_order_id: string;
  symbol: string;
  side: string;
  order_type: string;
  price?: string | null;
  quantity: string;
  filled_quantity: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type RuntimeHealth = Record<string, unknown>;
export type KillSwitch = Record<string, unknown>;

export type KlineInterval = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";

export type KlineCandle = {
  open_time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  close_time?: string;
  closed?: boolean;
};

export type KlineResponse = {
  symbol: string;
  interval: KlineInterval;
  source: string;
  status: string;
  supported_intervals?: KlineInterval[];
  candles: KlineCandle[];
};

export type TradingSnapshot = {
  health: ApiState<Record<string, unknown>>;
  ready: ApiState<Record<string, unknown>>;
  runtime: ApiState<RuntimeHealth>;
  account: ApiState<Account>;
  positions: ApiState<Record<string, Position>>;
  orders: ApiState<Order[]>;
  killswitch: ApiState<KillSwitch>;
  optional: Record<string, ApiState<unknown>>;
  websocket: "connecting" | "connected" | "disconnected";
  lastEvent?: { event_type?: string; payload?: Record<string, unknown>; timestamp?: string };
};
