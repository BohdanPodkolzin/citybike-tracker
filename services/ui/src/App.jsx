import { useEffect, useState } from "react";
import { api } from "./api.js";
import { useNow, usePolling, usePreferences, useSystemTheme } from "./hooks.js";
import AnimatedBackground from "./components/AnimatedBackground.jsx";
import Footer from "./components/Footer.jsx";
import Header from "./components/Header.jsx";
import HistoryChart from "./components/HistoryChart.jsx";
import KpiCards from "./components/KpiCards.jsx";
import StationMap from "./components/StationMap.jsx";
import StationsPanel from "./components/StationsPanel.jsx";

const REFRESH_MS = 30_000;

function Banner({ tone, children }) {
  return (
    <div className={`banner banner-${tone}`} role="status">
      {children}
    </div>
  );
}

function Message({ title, children }) {
  return (
    <section className="card message">
      <h2>{title}</h2>
      <p className="muted">{children}</p>
    </section>
  );
}

export default function App() {
  const [prefs, setPref] = usePreferences();
  const systemTheme = useSystemTheme();
  const theme = prefs.theme ?? systemTheme;
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Four independent data sources. Each keeps its last good data on failure.
  const current = usePolling(api.current, REFRESH_MS);
  const stations = usePolling(api.stations, REFRESH_MS);
  const history = usePolling((signal) => api.history(prefs.range, signal), REFRESH_MS, [prefs.range]);
  const status = usePolling(api.status, REFRESH_MS);

  const now = useNow(1000);

  // 404 from History only means "no snapshots stored yet". Not a failure.
  const noData = !current.data && current.error?.status === 404;
  const failure = [current, stations, history, status].find(
    (p) => p.error && p.error.status !== 404,
  )?.error;

  const pollInterval = status.data?.poll_interval ?? 60;
  const snapshotTime = current.data ? Date.parse(current.data.current.fetched_at) : null;
  const ageMs = snapshotTime ? now - snapshotTime : null;
  const isStale = ageMs != null && ageMs > Math.max(pollInterval * 3000, 180_000);

  let connection = "live";
  if (!current.data && !noData && !failure) connection = "loading";
  else if (noData) connection = "waiting";
  else if (failure) connection = "offline";
  else if (isStale) connection = "stale";

  const fatal = !current.data && failure && !noData;
  const stationList = stations.data?.stations ?? null;

  let banner = null;
  if (failure && !fatal) {
    banner = (
      <Banner tone="bad">
        {failure.status === 0
          ? "Can't reach the History service. Retrying automatically, showing the last data."
          : failure.status === 503
            ? "History is running, but its database is unavailable. Retrying automatically."
            : `Server error: ${failure.message}. Retrying automatically.`}
      </Banner>
    );
  } else if (isStale) {
    banner = (
      <Banner tone="warn">
        No new data for {Math.round(ageMs / 60000)} min. The poller or the Fetcher may be down.
        {status.data?.last_error ? ` Last error: ${status.data.last_error}` : ""}
      </Banner>
    );
  }

  return (
    <>
      <AnimatedBackground />
      <div className="app">
        <Header
          title={current.data?.current.network_name ?? "CityBikes"}
          subtitle={current.data?.current.network_id}
          connection={connection}
          ageMs={ageMs}
          theme={theme}
          onToggleTheme={() => setPref("theme", theme === "dark" ? "light" : "dark")}
        />

        {banner}

        {fatal ? (
          <Message title="Can't load data">
            {failure.status === 0
              ? "The History service is not reachable. This page keeps retrying every 30 seconds."
              : `${failure.message}. This page keeps retrying every 30 seconds.`}
          </Message>
        ) : noData ? (
          <Message title="Collecting the first data">
            The service is running but has not stored a snapshot yet. This page will fill in by itself.
          </Message>
        ) : (
          <main className="content">
            <KpiCards data={current.data} stations={stationList} />
            <div className="main-grid">
              <HistoryChart
                snapshots={history.data?.snapshots}
                range={prefs.range}
                onRangeChange={(r) => setPref("range", r)}
                loading={history.loading}
              />
              <StationsPanel
                stations={stationList}
                tab={prefs.stationsTab}
                onTabChange={(t) => setPref("stationsTab", t)}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            </div>
            <StationMap stations={stationList} selectedId={selectedId} onSelect={setSelectedId} />
          </main>
        )}

        <Footer status={status.data} />
      </div>
    </>
  );
}
