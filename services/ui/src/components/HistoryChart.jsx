import { useMemo, useRef, useState } from "react";
import { useElementWidth } from "../hooks.js";
import { fmtClock, fmtDateTime, fmtInt } from "../format.js";

const RANGES = [
  { id: 60, label: "1h" },
  { id: 360, label: "6h" },
  { id: 1440, label: "24h" },
];

const HEIGHT = 270;
const PAD = { top: 16, right: 14, bottom: 28, left: 44 };

// "Nice" axis: round step (1, 2, 5, 10, ...) and ticks that cover min..max.
// Bike counts are whole numbers, so the step is never below 1.
function niceScale(min, max, count = 4) {
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const rough = (max - min) / count;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const frac = rough / pow;
  const step = Math.max(1, (frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10) * pow);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return { lo, hi, ticks };
}

function LineChart({ points }) {
  const wrapRef = useRef(null);
  const width = useElementWidth(wrapRef);
  const [hover, setHover] = useState(null);

  const innerW = width - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;

  const geometry = useMemo(() => {
    const tMin = points[0].t;
    const tMax = points[points.length - 1].t;
    const span = Math.max(1, tMax - tMin);
    const values = points.map((p) => p.v);
    // a little headroom so the line never sits on the axis
    const vMin = Math.min(...values);
    const vMax = Math.max(...values);
    const headroom = Math.max(1, (vMax - vMin) * 0.08);
    const { lo, hi, ticks } = niceScale(vMin - headroom, vMax + headroom);
    const x = (t) => PAD.left + ((t - tMin) / span) * innerW;
    const y = (v) => PAD.top + (1 - (v - lo) / (hi - lo)) * innerH;
    const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
    const area = `${line}L${x(tMax).toFixed(1)},${PAD.top + innerH}L${x(tMin).toFixed(1)},${PAD.top + innerH}Z`;
    return { tMin, tMax, span, ticks, x, y, line, area };
  }, [points, innerW, innerH]);

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const t = geometry.tMin + ((e.clientX - rect.left - PAD.left) / innerW) * geometry.span;
    let lo = 0;
    let hi = points.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (points[mid].t < t) lo = mid;
      else hi = mid;
    }
    setHover(Math.abs(points[lo].t - t) <= Math.abs(points[hi].t - t) ? lo : hi);
  };

  const hp = hover != null ? points[hover] : null;
  const hx = hp ? geometry.x(hp.t) : 0;
  const hy = hp ? geometry.y(hp.v) : 0;
  const xTicks = [0, 1 / 3, 2 / 3, 1].map((f) => geometry.tMin + f * geometry.span);

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg
        width={width}
        height={HEIGHT}
        className="chart-svg"
        role="img"
        aria-label="Line chart of free bikes over time"
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: "var(--accent)", stopOpacity: 0.35 }} />
            <stop offset="100%" style={{ stopColor: "var(--accent)", stopOpacity: 0 }} />
          </linearGradient>
        </defs>

        {geometry.ticks.map((v) => (
          <g key={v}>
            <line className="grid-line" x1={PAD.left} x2={width - PAD.right} y1={geometry.y(v)} y2={geometry.y(v)} />
            <text className="axis-text" x={PAD.left - 8} y={geometry.y(v)} textAnchor="end" dominantBaseline="middle">
              {fmtInt(v)}
            </text>
          </g>
        ))}

        {xTicks.map((t, i) => (
          <text
            key={i}
            className="axis-text"
            x={geometry.x(t)}
            y={HEIGHT - 8}
            textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"}
          >
            {fmtClock(t)}
          </text>
        ))}

        <path d={geometry.area} fill="url(#areaFill)" />
        <path d={geometry.line} className="chart-line" />

        {hp ? (
          <g>
            <line className="hover-line" x1={hx} x2={hx} y1={PAD.top} y2={PAD.top + innerH} />
            <circle className="hover-dot" cx={hx} cy={hy} r="5" />
          </g>
        ) : null}
      </svg>

      {hp ? (
        <div
          className="chart-tip"
          style={{ left: Math.min(Math.max(hx, 70), width - 70), top: hy - 10 }}
        >
          <strong>{fmtInt(hp.v)} bikes</strong>
          <span>{fmtDateTime(hp.t)}</span>
        </div>
      ) : null}
    </div>
  );
}

export default function HistoryChart({ snapshots, range, onRangeChange, loading }) {
  const points = useMemo(
    () =>
      (snapshots ?? [])
        .map((s) => ({ t: Date.parse(s.fetched_at), v: s.free_bikes }))
        .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.v)),
    [snapshots],
  );

  const summary = useMemo(() => {
    if (points.length === 0) return "";
    const vals = points.map((p) => p.v);
    return `min ${fmtInt(Math.min(...vals))} · max ${fmtInt(Math.max(...vals))} · ${fmtInt(points.length)} snapshots`;
  }, [points]);

  return (
    <section className="card chart-card" aria-labelledby="chart-title">
      <div className="card-head">
        <div>
          <h2 id="chart-title">Free bikes over time</h2>
          <p className="muted small">{summary || "history from the database"}</p>
        </div>
        <div className="segmented" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button
              key={r.id}
              type="button"
              className={r.id === range ? "on" : ""}
              aria-pressed={r.id === range}
              onClick={() => onRangeChange(r.id)}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="skeleton chart-skeleton" />
      ) : points.length < 2 ? (
        <div className="empty-note">
          Collecting data… {points.length} snapshot{points.length === 1 ? "" : "s"} in this range so far.
        </div>
      ) : (
        <LineChart points={points} />
      )}
    </section>
  );
}
