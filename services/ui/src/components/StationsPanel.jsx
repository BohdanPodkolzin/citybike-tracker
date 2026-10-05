import { useMemo } from "react";
import { fmtInt, stationLevel } from "../format.js";

const byName = (a, b) => (a.name ?? "").localeCompare(b.name ?? "");

export default function StationsPanel({ stations, tab, onTabChange, selectedId, onSelect }) {
  const lists = useMemo(() => {
    const all = stations ?? [];
    const top = [...all]
      .sort((a, b) => (b.free_bikes ?? -1) - (a.free_bikes ?? -1) || byName(a, b))
      .slice(0, 10);
    const empty = all.filter((s) => s.free_bikes === 0).sort(byName);
    return { top, empty };
  }, [stations]);

  const rows = tab === "empty" ? lists.empty : lists.top;

  return (
    <section className="card stations-card" aria-labelledby="stations-title">
      <div className="card-head">
        <h2 id="stations-title">Stations</h2>
        <div className="segmented" role="tablist" aria-label="Station list">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "top"}
            className={tab === "top" ? "on" : ""}
            onClick={() => onTabChange("top")}
          >
            Top
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "empty"}
            className={tab === "empty" ? "on" : ""}
            onClick={() => onTabChange("empty")}
          >
            Empty{stations ? ` (${lists.empty.length})` : ""}
          </button>
        </div>
      </div>

      {stations === null ? (
        <ul className="station-list">
          {[0, 1, 2, 3, 4].map((i) => (
            <li key={i} className="station">
              <div className="skeleton sk-line" style={{ width: "100%" }} />
            </li>
          ))}
        </ul>
      ) : rows.length === 0 ? (
        <div className="empty-note">
          {tab === "empty" ? "Every station has at least one bike." : "No station data yet."}
        </div>
      ) : (
        <ul className="station-list">
          {rows.map((s) => {
            const total = (s.free_bikes ?? 0) + (s.empty_slots ?? 0);
            const pct = total > 0 && s.free_bikes != null ? (s.free_bikes / total) * 100 : 0;
            const level = stationLevel(s.free_bikes);
            return (
              <li key={s.id}>
                <button
                  type="button"
                  className={`station${s.id === selectedId ? " selected" : ""}`}
                  onClick={() => onSelect(s.id === selectedId ? null : s.id)}
                >
                  <span className="station-main">
                    <span className="station-name">{s.name ?? s.id}</span>
                    <span className="station-sub">
                      {s.ebikes > 0 ? `${s.ebikes} e-bike${s.ebikes === 1 ? "" : "s"} · ` : ""}
                      {fmtInt(s.empty_slots)} free docks
                    </span>
                    <span className="bar">
                      <span className={`bar-fill lvl-${level}`} style={{ width: `${pct}%` }} />
                    </span>
                  </span>
                  <span className={`station-count lvl-${level}`}>{fmtInt(s.free_bikes)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
