import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  loadPreferences,
  readCached,
  sanitize,
  savePreferences,
} from "./preferences.js";

/**
 * Calls fetcher(signal) now and then every intervalMs.
 *  - keeps the last good data when a refresh fails (shown as stale, not blank)
 *  - does not poll while the tab is hidden, refreshes as soon as it is visible
 *  - when `deps` change (e.g. the chart range) the old data is dropped at once
 */
export function usePolling(fetcher, intervalMs, deps = []) {
  const depsKey = JSON.stringify(deps);
  const [state, setState] = useState({
    data: null,
    error: null,
    updatedAt: null,
    depsKey,
  });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher; // always call the latest closure

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let controller = null;

    const run = async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        const data = await fetcherRef.current(controller.signal);
        if (!cancelled) {
          setState({ data, error: null, updatedAt: Date.now(), depsKey });
        }
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;
        setState((s) => ({ ...s, error: err }));
      }
    };

    const loop = async () => {
      if (!document.hidden) await run();
      if (!cancelled) timer = setTimeout(loop, intervalMs);
    };
    loop();

    const onVisible = () => {
      if (!document.hidden) run();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs, depsKey]);

  const fresh = state.depsKey === depsKey;
  const data = fresh ? state.data : null;
  return {
    data,
    error: state.error,
    updatedAt: fresh ? state.updatedAt : null,
    loading: data === null && state.error === null,
  };
}

// Re-renders every intervalMs so "12 s ago" keeps counting.
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

const LIGHT_QUERY = "(prefers-color-scheme: light)";

export function useSystemTheme() {
  const read = () => (window.matchMedia?.(LIGHT_QUERY).matches ? "light" : "dark");
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    const mq = window.matchMedia?.(LIGHT_QUERY);
    if (!mq) return undefined;
    const onChange = () => setTheme(mq.matches ? "light" : "dark");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return theme;
}

// [prefs, setPref]. Updates the screen immediately, saves in the background.
export function usePreferences() {
  const [prefs, setPrefs] = useState(readCached);
  const latest = useRef(prefs);
  latest.current = prefs;

  useEffect(() => {
    let alive = true;
    loadPreferences()
      .then((p) => alive && setPrefs(sanitize(p)))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const setPref = useCallback((key, value) => {
    const next = sanitize({ ...latest.current, [key]: value });
    latest.current = next;
    setPrefs(next);
    savePreferences(next).catch(() => {});
  }, []);

  return [prefs, setPref];
}

// Width in px of an element, kept up to date on resize (for the SVG charts).
export function useElementWidth(ref, fallback = 600) {
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const update = () =>
      setWidth(Math.max(240, Math.round(el.getBoundingClientRect().width)));
    update();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", update);
      return () => window.removeEventListener("resize", update);
    }
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}
