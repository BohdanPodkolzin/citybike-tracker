import { fmtInt } from "../format.js";

export default function Footer({ status }) {
  return (
    <footer className="footer">
      <p>
        Data:{" "}
        <a href="https://citybik.es/" target="_blank" rel="noopener noreferrer">
          CityBikes
        </a>
      </p>
      {status ? (
        <p className="muted">
          {fmtInt(status.snapshots_total)} snapshots stored · polling every {status.poll_interval} s
        </p>
      ) : null}
    </footer>
  );
}
