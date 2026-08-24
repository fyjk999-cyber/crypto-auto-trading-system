import test from "node:test";
import assert from "node:assert/strict";
import {
  allowedByRole,
  authorize,
  classifyRequest,
  containerPath,
  requiredRuntimeSecrets,
  routePath,
  runtimeIsHealthy,
  securityHeaders,
  timingSafeEqual,
} from "../src/gateway.js";

const env = {
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

test("routePath classifies all required container routes", () => {
  assert.equal(routePath("/api/v1/health"), "api");
  assert.equal(routePath("/ws/market"), "ws");
  assert.equal(routePath("/health"), "health");
  assert.equal(routePath("/ready"), "health");
  assert.equal(routePath("/internal/runtime-health"), "health");
  assert.equal(routePath("/openapi.json"), "api");
  assert.equal(routePath("/docs"), "api");
  assert.equal(routePath("/admin"), "not_found");
});

test("classifyRequest separates read/control/write", () => {
  assert.equal(classifyRequest("GET", "/api/v1/positions"), "READ");
  assert.equal(classifyRequest("POST", "/api/v1/kill-switch/off"), "CONTROL");
  assert.equal(classifyRequest("POST", "/api/v1/killswitch"), "CONTROL");
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

test("an unverified Access JWT is never accepted as human", async () => {
  const request = new Request("https://edge/api/v1/positions", {
    headers: { "Cf-Access-Jwt-Assertion": "attacker-controlled" },
  });
  assert.equal(await authorize(request, env, async () => false), "anonymous");
  assert.equal(await authorize(request, env, async () => { throw new Error("bad signature"); }), "anonymous");
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

test("codex is read-only for every write class", () => {
  assert.equal(allowedByRole("codex", "WRITE", "/api/v1/manual-orders"), false);
  assert.equal(allowedByRole("codex", "CONTROL", "/api/v1/runtime/start"), false);
});

test("api prefix is removed before container forwarding", () => {
  assert.equal(containerPath("/api/v1/positions"), "/positions");
  assert.equal(containerPath("/api/v1"), "/");
  assert.equal(containerPath("/ready"), "/ready");
});

test("runtime configuration fails closed when secrets are missing", () => {
  assert.deepEqual(requiredRuntimeSecrets({}), [
    "DATABASE_URL",
    "BINANCE_TESTNET_API_KEY",
    "BINANCE_TESTNET_API_SECRET",
    "INTERNAL_API_SECRET",
  ]);
  assert.deepEqual(requiredRuntimeSecrets({
    DATABASE_URL: "set",
    BINANCE_TESTNET_API_KEY: "set",
    BINANCE_TESTNET_API_SECRET: "set",
    INTERNAL_API_SECRET: "set",
  }), []);
});

test("timingSafeEqual handles unequal input lengths without early return", async () => {
  assert.equal(await timingSafeEqual("same", "same"), true);
  assert.equal(await timingSafeEqual("short", "longer"), false);
});

test("watchdog requires a running database-backed lease, not HTTP 200 alone", () => {
  assert.equal(runtimeIsHealthy(true, { runtime_state: "STOPPED" }), false);
  assert.equal(runtimeIsHealthy(true, {
    runtime_state: "RUNNING", database: true, lease_valid: false,
  }), false);
  assert.equal(runtimeIsHealthy(true, {
    runtime_state: "RUNNING", database: true, lease_valid: true,
  }), true);
});
