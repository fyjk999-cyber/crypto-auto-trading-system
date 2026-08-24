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
  quantity: string;
  avg_entry_price?: string | null;
  cost_basis: string;
  realized_pnl: string;
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
  lastEvent?: { event_type?: string; payload?: Record<string, unknown> };
};
