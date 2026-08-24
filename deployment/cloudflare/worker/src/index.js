/** Cloudflare edge gateway. Trading, risk, ledger, and order logic stay in Python. */
import { Container, getContainer } from "@cloudflare/containers";
import { env as workerEnv } from "cloudflare:workers";

import {
  allowedByRole,
  authorize,
  classifyRequest,
  containerPath,
  requiredRuntimeSecrets,
  routePath,
  runtimeIsHealthy,
  securityHeaders,
} from "./gateway.js";

const CONTAINER_NAME = "crypto-trading-primary";

function jsonResponse(body, status, requestId) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...securityHeaders(requestId) },
  });
}

function toContainerRequest(request, role, requestId) {
  const source = new URL(request.url);
  source.pathname = containerPath(source.pathname);
  const headers = new Headers(request.headers);
  headers.delete("CF-Access-Client-Secret");
  headers.delete("Cf-Access-Jwt-Assertion");
  headers.set("x-cf-role", role);
  headers.set("x-request-id", requestId);
  return new Request(source, { method: request.method, headers, body: request.body, redirect: "manual" });
}

async function handleRequest(request, env) {
  const requestId = crypto.randomUUID();
  const pathname = new URL(request.url).pathname;
  const route = routePath(pathname);
  if (route === "not_found") {
    return jsonResponse({ error: { code: "NOT_FOUND", message: "not found" } }, 404, requestId);
  }

  if (requiredRuntimeSecrets(env).length) {
    return jsonResponse({
      ok: false,
      error: { code: "RUNTIME_NOT_CONFIGURED", message: "required runtime secrets are missing" },
    }, 503, requestId);
  }

  let role = "anonymous";
  if (pathname !== "/health") {
    role = await authorize(request, env);
    const requestClass = classifyRequest(request.method, pathname);
    if (!allowedByRole(role, requestClass, pathname)) {
      return jsonResponse({ error: { code: "FORBIDDEN", message: "access denied" } }, 403, requestId);
    }
  }

  const container = getContainer(env.TRADING_CONTAINER, CONTAINER_NAME);
  const response = await container.fetch(toContainerRequest(request, role, requestId));
  if (route === "ws") return response;

  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(securityHeaders(requestId))) headers.set(name, value);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

const runtimeEnv = /** @type {Cloudflare.Env & {
 * DATABASE_URL: string,
 * INTERNAL_API_SECRET: string,
 * }} */ (workerEnv);

export class TradingContainerV2 extends Container {
  defaultPort = 8080;
  requiredPorts = [8080];
  sleepAfter = "10m";
  pingEndpoint = "/health";
  enableInternet = true;
  envVars = {
    APP_ENV: "production",
    TRADING_MODE: "PAPER",
    PAPER_MODE: "PAPER_REAL_MARKET",
    AUTO_START_RUNTIME: "true",
    LIVE_TRADING_ENABLED: "false",
    BINANCE_TESTNET: "false",
    DATABASE_URL: runtimeEnv.DATABASE_URL,
    INTERNAL_API_SECRET: runtimeEnv.INTERNAL_API_SECRET,
  };
}

async function runWatchdog(_event, env) {
  if (requiredRuntimeSecrets(env).length) {
    throw new Error("watchdog blocked: required runtime secrets are missing");
  }

  const container = getContainer(env.TRADING_CONTAINER, CONTAINER_NAME);
  await container.startAndWaitForPorts({
    ports: [8080],
    cancellationOptions: { portReadyTimeoutMS: 30_000 },
  });
  const response = await container.fetch(new Request("https://container/internal/runtime-health"));
  const payload = await response.json().catch(() => null);
  if (!runtimeIsHealthy(response.ok, payload)) {
    await container.stop("SIGTERM");
    await container.startAndWaitForPorts({
      ports: [8080],
      cancellationOptions: { portReadyTimeoutMS: 30_000 },
    });
    const recovered = await container.fetch(new Request("https://container/internal/runtime-health"));
    const recoveredPayload = await recovered.json().catch(() => null);
    if (!runtimeIsHealthy(recovered.ok, recoveredPayload)) {
      throw new Error(`watchdog recovery failed: HTTP ${recovered.status}`);
    }
  }
}

export default {
  fetch(request, env) {
    return handleRequest(request, env);
  },
  scheduled(event, env) {
    return runWatchdog(event, env);
  },
};
