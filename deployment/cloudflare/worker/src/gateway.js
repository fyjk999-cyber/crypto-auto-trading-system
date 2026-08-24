import { createRemoteJWKSet, jwtVerify } from "jose";

const CONTROL_ENDPOINTS = [
  "/api/v1/runtime/start",
  "/api/v1/runtime/stop",
  "/api/v1/kill-switch/on",
  "/api/v1/kill-switch/off",
  "/api/v1/killswitch",
  "/api/v1/reviews/",
];

export async function timingSafeEqual(a, b) {
  const encoder = new TextEncoder();
  const [aHash, bHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(a)),
    crypto.subtle.digest("SHA-256", encoder.encode(b)),
  ]);
  // Workers exposes timingSafeEqual; Node tests do not yet. Both inputs are
  // fixed-length SHA-256 digests, so the fallback has no length oracle.
  const subtle = /** @type {SubtleCrypto & { timingSafeEqual?: (a: ArrayBuffer, b: ArrayBuffer) => boolean }} */ (crypto.subtle);
  if (typeof subtle.timingSafeEqual === "function") {
    return subtle.timingSafeEqual(aHash, bHash);
  }
  const aBytes = new Uint8Array(aHash);
  const bBytes = new Uint8Array(bHash);
  let difference = 0;
  for (let index = 0; index < aBytes.length; index += 1) {
    difference |= aBytes[index] ^ bBytes[index];
  }
  return difference === 0;
}

export function securityHeaders(requestId) {
  return {
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-request-id": requestId || "unknown",
  };
}

export function classifyRequest(method, pathname) {
  if (method === "GET" || method === "HEAD") return "READ";
  if (CONTROL_ENDPOINTS.some((prefix) => pathname.startsWith(prefix))) return "CONTROL";
  return "WRITE";
}

function normalizeTeamDomain(value) {
  if (!value) return null;
  const url = new URL(value.startsWith("https://") ? value : `https://${value}`);
  return url.origin;
}

export async function verifyHumanAccessJwt(token, env) {
  const issuer = normalizeTeamDomain(env.ACCESS_TEAM_DOMAIN);
  const audience = env.ACCESS_POLICY_AUD;
  if (!issuer || !audience) return false;
  const jwks = createRemoteJWKSet(new URL(`${issuer}/cdn-cgi/access/certs`));
  await jwtVerify(token, jwks, { issuer, audience });
  return true;
}

export async function authorize(request, env, verifyJwt = verifyHumanAccessJwt) {
  const clientId = request.headers.get("CF-Access-Client-Id") || "";
  const clientSecret = request.headers.get("CF-Access-Client-Secret") || "";
  if (clientId && clientSecret) {
    if (env.CODEX_CLIENT_ID && env.CODEX_CLIENT_SECRET
        && (await timingSafeEqual(clientId, env.CODEX_CLIENT_ID))
        && (await timingSafeEqual(clientSecret, env.CODEX_CLIENT_SECRET))) return "codex";
    if (env.HARNESS_CLIENT_ID && env.HARNESS_CLIENT_SECRET
        && (await timingSafeEqual(clientId, env.HARNESS_CLIENT_ID))
        && (await timingSafeEqual(clientSecret, env.HARNESS_CLIENT_SECRET))) return "harness";
  }

  const jwt = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!jwt) return "anonymous";
  try {
    return (await verifyJwt(jwt, env)) ? "human" : "anonymous";
  } catch {
    return "anonymous";
  }
}

export function routePath(pathname) {
  if (pathname.startsWith("/api/v1/") || pathname === "/api/v1") return "api";
  if (pathname === "/openapi.json" || pathname.startsWith("/docs")) return "api";
  if (pathname === "/ws" || pathname.startsWith("/ws/")) return "ws";
  if (["/health", "/ready", "/internal/runtime-health"].includes(pathname)) return "health";
  return "not_found";
}

export function allowedByRole(role, requestClass, pathname) {
  if (role === "harness") return true;
  if (role === "human") return requestClass !== "CONTROL";
  if (role === "codex") return requestClass === "READ" && !pathname.startsWith("/api/v1/reviews/");
  return false;
}

export function containerPath(pathname) {
  if (pathname === "/api/v1") return "/";
  if (pathname.startsWith("/api/v1/")) return pathname.slice("/api/v1".length);
  return pathname;
}

export function requiredRuntimeSecrets(env) {
  return [
    "DATABASE_URL",
    "BINANCE_TESTNET_API_KEY",
    "BINANCE_TESTNET_API_SECRET",
    "INTERNAL_API_SECRET",
  ].filter((name) => !env[name]);
}

export function runtimeIsHealthy(responseOk, payload) {
  return responseOk
    && payload !== null
    && typeof payload === "object"
    && ["RUNNING", "RECOVERING"].includes(payload.runtime_state)
    && payload.database === true
    && payload.lease_valid === true;
}
