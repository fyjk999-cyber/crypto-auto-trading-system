export type ApiState<T> = {
  status: "loading" | "ready" | "empty" | "unavailable" | "offline" | "error";
  data?: T;
  message?: string;
};

export type Account = {
  account_id: string;
  mode: string;
  balances: Record<string, { currency: string; total: string; available: string; frozen: string }>;
  equity: string;
  margin_used: string;
  updated_at?: string | null;
};

export type Position = {
  symbol: string;
  base_asset?: string;
  quantity: string;
  avg_entry_price?: string | null;
  cost_basis: string;
  realized_pnl: string;
  updated_at?: string | null;
  market_type?: string;
  side?: string;
  unrealized_pnl?: string;
  leverage?: string;
  initial_margin?: string;
  liquidation_price?: string;
  mark_price?: string;
};

export type Order = {
  internal_order_id: string;
  client_order_id: string;
  exchange_order_id?: string | null;
  symbol: string;
  side: string;
  order_type: string;
  price?: string | null;
  avg_fill_price?: string | null;
  quantity: string;
  filled_quantity: string;
  status: string;
  created_at: string;
  updated_at: string;
  market_type?: string;
  position_side?: string;
  strategy_id?: string;
  run_id?: string | null;
  reduce_only?: boolean;
  rejection_reason?: string | null;
  fee_total?: string | null;
  fee_currency?: string | null;
  fill_count?: number;
  realized_pnl?: string | null;
  unrealized_pnl?: string | null;
  pnl_percent?: string | null;
  pnl_scope?: string | null;
  trade_status?: string | null;
  decision_id?: string | null;
  signal_id?: string | null;
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
