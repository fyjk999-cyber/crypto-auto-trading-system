/**
 * Crypto Trading Gateway Worker.
 * Edge-only: auth, routing, rate limiting, security headers, request IDs,
 * WebSocket forwarding. No trading/risk/ledger/order logic.
 */

const CONTROL_ENDPOINTS = [
  "/api/v1/runtime/start",
  "/api/v1/runtime/stop",
  "/api/v1/kill-switch/on",
  "/api/v1/kill-switch/off",
  "/api/v1/reviews/",
];

export async function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  const enc = new TextEncoder();
  const ab = enc.encode(a);
  const bb = enc.encode(b);
  let diff = 0;
  for (let i = 0; i < ab.length; i += 1) diff |= ab[i] ^ bb[i];
  return diff === 0;
}

export function securityHeaders(requestId) {
  return {
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-request-id": requestId || "unknown",
  };
}

export class SlidingWindowRateLimiter {
  constructor(maxRequests = 120, windowMs = 60_000) {
    this.maxRequests = maxRequests;
    this.windowMs = windowMs;
    this.hits = new Map();
  }
  allow(key, now = Date.now()) {
    const windowStart = now - this.windowMs;
    let timestamps = this.hits.get(key) || [];
    timestamps = timestamps.filter((t) => t > windowStart);
    if (timestamps.length >= this.maxRequests) {
      this.hits.set(key, timestamps);
      return false;
    }
    timestamps.push(now);
    this.hits.set(key, timestamps);
    return true;
  }
}

export function classifyRequest(method, pathname) {
  if (method === "GET" || method === "HEAD") return "READ";
  if (CONTROL_ENDPOINTS.some((prefix) => pathname.startsWith(prefix))) return "CONTROL";
  return "WRITE";
}

export async function authorize(request, env) {
  const clientId = request.headers.get("CF-Access-Client-Id") || "";
  const clientSecret = request.headers.get("CF-Access-Client-Secret") || "";
  if (clientId && clientSecret) {
    if (env.CODEX_CLIENT_ID && (await timingSafeEqual(clientId, env.CODEX_CLIENT_ID))
        && (await timingSafeEqual(clientSecret, env.CODEX_CLIENT_SECRET))) return "codex";
    if (env.HARNESS_CLIENT_ID && (await timingSafeEqual(clientId, env.HARNESS_CLIENT_ID))
        && (await timingSafeEqual(clientSecret, env.HARNESS_CLIENT_SECRET))) return "harness";
  }
  const jwt = request.headers.get("Cf-Access-Jwt-Assertion");
  if (jwt) return "human";
  return "anonymous";
}

export function routePath(pathname) {
  if (pathname.startsWith("/api/v1/") || pathname.startsWith("/openapi.json")
      || pathname.startsWith("/docs")) return "api";
  if (pathname.startsWith("/ws")) return "ws";
  if (pathname === "/health") return "health";
  return "not_found";
}

export function allowedByRole(role, requestClass, pathname) {
  if (role === "harness") return true;
  if (role === "human") return requestClass !== "CONTROL";
  if (role === "codex") {
    if (requestClass === "CONTROL") return false;
    if (requestClass === "WRITE" && pathname.startsWith("/api/v1/reviews/")) return false;
    return true;
  }
  return false;
}

export async function handleRequest(request, env, ctx) {
  const requestId = crypto.randomUUID();
  const url = new URL(request.url);
  const pathname = url.pathname;
  const route = routePath(pathname);
  const baseHeaders = () => ({ "content-type": "application/json", ...securityHeaders(requestId) });
  if (route === "not_found") {
    return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "not found" } }),
      { status: 404, headers: baseHeaders() });
  }
  if (route === "health") {
    return new Response(JSON.stringify({ ok: true, request_id: requestId }), {
      status: 200, headers: baseHeaders(),
    });
  }
  const role = await authorize(request, env);
  const requestClass = classifyRequest(request.method, pathname);
  if (!allowedByRole(role, requestClass, pathname)) {
    return new Response(JSON.stringify({ error: { code: "FORBIDDEN", message: "access denied" } }),
      { status: 403, headers: baseHeaders() });
  }
  const limiter = ctx.rateLimiter;
  if (limiter && !limiter.allow(role || "anonymous")) {
    return new Response(JSON.stringify({ error: { code: "RATE_LIMITED", message: "slow down" } }),
      { status: 429, headers: baseHeaders() });
  }
  const backend = new URL(env.BACKEND_URL);
  if (pathname.startsWith("/api/v1/")) {
    backend.pathname = pathname.replace("/api/v1", "");
  } else {
    backend.pathname = pathname;
  }
  backend.search = url.search;

  if (route === "ws") {
    const upgrade = request.headers.get("Upgrade") || "";
    if (upgrade.toLowerCase() !== "websocket") {
      return new Response("websocket required", { status: 426, headers: securityHeaders(requestId) });
    }
    const backendWs = backend.toString().replace(/^http/, "ws");
    // @ts-ignore - Cloudflare WebSocketPair global
    const pair = new WebSocketPair();
    const [clientSocket, serverSocket] = Object.values(pair);
    serverSocket.accept();
    clientSocket.accept();
    ctx.waitUntil(proxyWebSocket(serverSocket, backendWs, request));
    // @ts-ignore - Cloudflare ResponseInit.webSocket extension
    return new Response(null, { status: 101, webSocket: clientSocket });
  }

  const headers = new Headers(request.headers);
  headers.set("x-request-id", requestId);
  headers.set("x-cf-role", role);
  headers.delete("CF-Access-Client-Secret");
  return fetch(backend.toString(), { method: request.method, headers, body: request.body, redirect: "manual" });
}

async function proxyWebSocket(localSocket, backendUrl, _request) {
  try {
    const backendSocket = await fetchWebSocket(backendUrl);
    await Promise.all([forward(localSocket, backendSocket), forward(backendSocket, localSocket)]);
  } catch {
    localSocket.close(1011, "backend unavailable");
  }
}

async function fetchWebSocket(url) {
  const response = await fetch(url, { headers: { Upgrade: "websocket" } });
  // @ts-ignore - Cloudflare Response.webSocket extension
  return response.webSocket;
}

async function forward(from, to) {
  const reader = from.readable.getReader();
  const writer = to.writable.getWriter();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      await writer.write(value);
    }
  } finally {
    try { await writer.close(); } catch { /* noop */ }
  }
}

export default {
  async fetch(request, env, ctx) {
    if (!ctx.rateLimiter) ctx.rateLimiter = new SlidingWindowRateLimiter();
    return handleRequest(request, env, ctx);
  },
};
