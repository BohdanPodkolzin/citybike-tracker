// UI preferences (theme, chart range, selected tab).
// They live on the server: History keeps them in Redis under an id that the
// browser holds in a cookie ("sid"). No login. Close the tab, open it again,
// and the same cookie brings the same settings back.
// The browser sends the cookie by itself, because /api is on the same origin.
 
export const DEFAULTS = { theme: null, range: 60, stationsTab: "top" };
 
const ALLOWED = {
  theme: ["light", "dark"], // null = follow the system setting
  range: [60, 360, 1440], // minutes
  stationsTab: ["top", "empty"],
};
 
// Never trust data from outside: keep only known keys with allowed values.
export function sanitize(raw) {
  const out = { ...DEFAULTS };
  if (raw && typeof raw === "object") {
    for (const key of Object.keys(ALLOWED)) {
      if (ALLOWED[key].includes(raw[key])) out[key] = raw[key];
    }
  }
  return out;
}
 
// Never fails: if the server cannot answer, the defaults are used.
export async function loadPreferences() {
  try {
    const res = await fetch("/api/preferences", { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return sanitize(await res.json());
  } catch {
    return { ...DEFAULTS };
  }
}
 
export async function savePreferences(prefs) {
  await fetch("/api/preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sanitize(prefs)),
  });
}
