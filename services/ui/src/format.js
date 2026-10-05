const nf = new Intl.NumberFormat("en-US");

export const fmtInt = (n) => (n == null ? "–" : nf.format(n));
export const fmtPct = (n) => (n == null ? "–" : `${n.toFixed(1)}%`);

// +3, −5, 0 (a real minus sign, not a hyphen). Returns null for "unknown".
export function fmtDelta(n, suffix = "") {
  if (n == null) return null;
  if (n === 0) return `0${suffix}`;
  const abs = Number.isInteger(n) ? Math.abs(n) : Math.abs(n).toFixed(1);
  return `${n > 0 ? "+" : "−"}${abs}${suffix}`;
}

export function timeAgo(ms) {
  if (ms == null) return "–";
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s} s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  return `${Math.floor(m / 60)} h ago`;
}

export const fmtClock = (t) =>
  new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export const fmtDateTime = (t) =>
  new Date(t).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

// How full a station is, used for colours in the list and on the map.
export function stationLevel(bikes) {
  if (bikes == null) return "unknown";
  if (bikes === 0) return "empty";
  if (bikes <= 3) return "low";
  return "ok";
}
