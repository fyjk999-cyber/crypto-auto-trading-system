import type { ApiState } from "../types/api";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
export const WS_URL = import.meta.env.VITE_WS_URL || "ws://127.0.0.1:8000/ws";

function requestUrl(path: string) {
  // Vite proxies local development traffic so the browser does not need backend CORS changes.
  if (import.meta.env.DEV && API_BASE_URL === "http://127.0.0.1:8000") return `/local-api${path}`;
  return `${API_BASE_URL}${path}`;
}

export function websocketUrl() {
  if (import.meta.env.DEV && WS_URL === "ws://127.0.0.1:8000/ws") {
    return `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/local-ws`;
  }
  return WS_URL;
}

export async function getJson<T>(path: string): Promise<ApiState<T>> {
  try {
    const response = await fetch(requestUrl(path), { headers: { accept: "application/json" } });
    if (response.status === 404) return { status: "unavailable", message: "Backend endpoint unavailable" };
    if (!response.ok) return { status: "error", message: `Backend returned HTTP ${response.status}` };
    const data = await response.json() as T;
    const empty = Array.isArray(data) ? data.length === 0 : Object.keys(data as object).length === 0;
    return { status: empty ? "empty" : "ready", data };
  } catch {
    return { status: "offline", message: "Backend Offline" };
  }
}

export async function sendJson<T>(path: string, method: "POST" | "DELETE", body?: unknown): Promise<ApiState<T>> {
  try {
    const response = await fetch(requestUrl(path), {
      method,
      headers: { accept: "application/json", ...(body === undefined ? {} : { "content-type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (response.status === 404) return { status: "unavailable", message: "Backend endpoint unavailable" };
    if (!response.ok) return { status: "error", message: `Backend returned HTTP ${response.status}` };
    return { status: "ready", data: await response.json() as T };
  } catch {
    return { status: "offline", message: "Backend Offline" };
  }
}
