import test from "node:test";
import assert from "node:assert/strict";
import {
  SlidingWindowRateLimiter,
  allowedByRole,
  authorize,
  classifyRequest,
  routePath,
  securityHeaders,
} from "../src/index.js";

const env = {
  BACKEND_URL: "https://backend.example",
  CODEX_CLIENT_ID: "codex-id",
  CODEX_CLIENT_SECRET: "codex-secret",
  HARNESS_CLIENT_ID: "harness-id",
  HARNESS_CLIENT_SECRET: "harness-secret",
};

test("security headers include request id", () => {
  const headers = securityHeaders("req-1");
  assert.equal(headers["x-request-id"], "req-1");
  assert.ok(headers["content-security-policy"]);
});

test("routePath classifies api, ws, health, not_found", () => {
  assert.equal(routePath("/api/v1/health"), "api");
  assert.equal(routePath("/ws/market"), "ws");
  assert.equal(routePath("/health"), "health");
  assert.equal(routePath("/admin"), "not_found");
});

test("classifyRequest separates read/control/write", () => {
  assert.equal(classifyRequest("GET", "/api/v1/positions"), "READ");
  assert.equal(classifyRequest("POST", "/api/v1/kill-switch/off"), "CONTROL");
  assert.equal(classifyRequest("POST", "/api/v1/reviews/x/approve"), "CONTROL");
  assert.equal(classifyRequest("POST", "/api/v1/manual-orders"), "WRITE");
});

test("authorize codex token", async () => {
  const request = new Request("https://edge/api/v1/positions", {
    headers: { "CF-Access-Client-Id": "codex-id", "CF-Access-Client-Secret": "codex-secret" },
  });
  assert.equal(await authorize(request, env), "codex");
});

test("authorize harness token", async () => {
  const request = new Request("https://edge/api/v1/runtime/start", {
    headers: { "CF-Access-Client-Id": "harness-id", "CF-Access-Client-Secret": "harness-secret" },
  });
  assert.equal(await authorize(request, env), "harness");
});

test("authorize anonymous returns anonymous", async () => {
  const request = new Request("https://edge/api/v1/positions");
  assert.equal(await authorize(request, env), "anonymous");
});

test("codex read-only cannot access control endpoints", () => {
  assert.equal(allowedByRole("codex", "READ", "/api/v1/positions"), true);
  assert.equal(allowedByRole("codex", "CONTROL", "/api/v1/kill-switch/off"), false);
  assert.equal(allowedByRole("codex", "CONTROL", "/api/v1/runtime/start"), false);
  assert.equal(allowedByRole("codex", "WRITE", "/api/v1/reviews/x/approve"), false);
});

test("harness can access control endpoints", () => {
  assert.equal(allowedByRole("harness", "CONTROL", "/api/v1/kill-switch/off"), true);
  assert.equal(allowedByRole("harness", "CONTROL", "/api/v1/runtime/start"), true);
});

test("rate limiter blocks beyond max", () => {
  const limiter = new SlidingWindowRateLimiter(2, 60_000);
  assert.equal(limiter.allow("a", 1_000), true);
  assert.equal(limiter.allow("a", 1_001), true);
  assert.equal(limiter.allow("a", 1_002), false);
  assert.equal(limiter.allow("b", 1_002), true);
});
