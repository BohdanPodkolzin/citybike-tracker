// The only place that talks to the History service. All paths are relative
// (/api/...): in dev Vite proxies them, in production nginx does.

export class ApiError extends Error {
  // status 0 means "no HTTP answer at all" (server down, network, timeout)
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const TIMEOUT_MS = 8000;

async function getJson(path, signal) {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), TIMEOUT_MS);
  const forward = () => timeout.abort();
  signal?.addEventListener("abort", forward);

  try {
    const res = await fetch(path, {
      signal: timeout.signal,
      headers: { Accept: "application/json" },
    });
    let body = null;
    try {
      body = await res.json();
    } catch {
      /* the body is not JSON, keep null */
    }
    if (!res.ok) {
      throw new ApiError(res.status, body?.error || `HTTP ${res.status}`);
    }
    return body;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err?.name === "AbortError") {
      if (signal?.aborted) throw err; // the caller cancelled: not an error
      throw new ApiError(0, "Request timed out");
    }
    throw new ApiError(0, "Cannot reach the server");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forward);
  }
}

export const api = {
  current: (signal) => getJson("/api/current", signal),
  history: (minutes, signal) => getJson(`/api/history?minutes=${minutes}`, signal),
  stations: (signal) => getJson("/api/stations/latest", signal),
  status: (signal) => getJson("/api/status", signal),
};
