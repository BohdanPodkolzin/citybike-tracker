// Every UI preference (theme, chart range, stations tab) goes through THIS
// file. Today they live in the browser's localStorage. In the Redis stage the
// bodies of loadPreferences() and savePreferences() will call the History API
// instead; the rest of the UI does not change, because it already treats both
// as asynchronous.

const KEY = "cbh:prefs"; // keep in sync with the inline script in index.html

export const DEFAULTS = { theme: null, range: 60, stationsTab: "top" };

const ALLOWED = {
  theme: ["light", "dark"], // null = follow the system setting
  range: [60, 360, 1440], // minutes
  stationsTab: ["top", "empty"],
};

// Never trust stored data: keep only known keys with allowed values.
export function sanitize(raw) {
  const out = { ...DEFAULTS };
  if (raw && typeof raw === "object") {
    for (const key of Object.keys(ALLOWED)) {
      if (ALLOWED[key].includes(raw[key])) out[key] = raw[key];
    }
  }
  return out;
}

// Synchronous: what we last knew. Used for the very first render, no flicker.
export function readCached() {
  try {
    return sanitize(JSON.parse(localStorage.getItem(KEY) || "{}"));
  } catch {
    return { ...DEFAULTS };
  }
}

export async function loadPreferences() {
  return readCached();
}

export async function savePreferences(prefs) {
  try {
    localStorage.setItem(KEY, JSON.stringify(sanitize(prefs)));
  } catch {
    /* storage blocked (private mode): the preference just won't persist */
  }
}
