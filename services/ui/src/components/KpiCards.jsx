import { fmtDelta, fmtInt, fmtPct } from "../format.js";

// signed: green when up, red when down. Otherwise a neutral grey chip.
function Delta({ value, suffix = "", signed = false }) {
  const text = fmtDelta(value, suffix);
  if (text === null) return null;
  const dir = value > 0 ? "up" : value < 0 ? "down" : "flat";
  const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "•";
  return (
    <span className={`delta delta-${signed ? dir : "neutral"}`}>
      {arrow} {text}
    </span>
  );
}

function Kpi({ label, value, sub, delta, primary, tone }) {
  return (
    <div className={`card kpi${primary ? " kpi-primary" : ""}${tone ? ` kpi-${tone}` : ""}`}>
      <p className="kpi-label">{label}</p>
      <p className="kpi-value">
        {value}
        {delta}
      </p>
      <p className="kpi-sub">{sub}</p>
    </div>
  );
}

export default function KpiCards({ data, stations }) {
  if (!data) {
    return (
      <section className="kpis" aria-label="Key numbers">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className={`card kpi${i === 0 ? " kpi-primary" : ""}`}>
            <div className="skeleton sk-line sk-short" />
            <div className="skeleton sk-value" />
            <div className="skeleton sk-line" />
          </div>
        ))}
      </section>
    );
  }

  const { current: cur, delta } = data;
  const emptyCount = stations ? stations.filter((s) => s.free_bikes === 0).length : null;

  return (
    <section className="kpis" aria-label="Key numbers">
      <Kpi
        primary
        label="Free bikes"
        value={fmtInt(cur.free_bikes)}
        delta={<Delta value={delta?.free_bikes} signed />}
        sub={`across ${fmtInt(cur.stations_count)} stations`}
      />
      <Kpi
        label="Free docks"
        value={fmtInt(cur.empty_slots)}
        delta={<Delta value={delta?.empty_slots} />}
        sub="places to return a bike"
      />
      <Kpi
        label="Occupancy"
        value={fmtPct(cur.occupancy_pct)}
        delta={<Delta value={delta?.occupancy_pct} suffix=" pp" />}
        sub="docks holding a bike"
      />
      <Kpi label="Stations" value={fmtInt(cur.stations_count)} sub="in the network" />
      <Kpi
        label="Empty stations"
        value={fmtInt(emptyCount)}
        sub="no bikes available"
        tone={emptyCount > 0 ? "warn" : undefined}
      />
    </section>
  );
}
