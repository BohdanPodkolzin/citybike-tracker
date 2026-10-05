import { timeAgo } from "../format.js";
import { MoonIcon, SunIcon } from "./Icons.jsx";

const LABELS = {
  loading: "Loading",
  waiting: "Waiting for data",
  live: "Live",
  stale: "Outdated",
  offline: "Offline",
};

export default function Header({ title, subtitle, connection, ageMs, theme, onToggleTheme }) {
  const showAge = ageMs != null && connection !== "waiting";
  const next = theme === "dark" ? "light" : "dark";
  return (
    <header className="header">
      <div>
        <p className="eyebrow">Live bike share</p>
        <h1>
          {title}
          {subtitle ? <span className="subtitle">{subtitle}</span> : null}
        </h1>
        <p className="status-line" role="status">
          <span className={`pill pill-${connection}`}>
            <span className="dot" />
            {LABELS[connection]}
          </span>
          {showAge ? <span className="muted">updated {timeAgo(ageMs)}</span> : null}
        </p>
      </div>
      <button
        type="button"
        className="icon-btn"
        onClick={onToggleTheme}
        aria-label={`Switch to ${next} theme`}
        title={`Switch to ${next} theme`}
      >
        {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      </button>
    </header>
  );
}
