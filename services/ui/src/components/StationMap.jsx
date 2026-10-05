import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { fmtInt, stationLevel } from "../format.js";

// OpenStreetMap tiles. Their usage policy asks for visible attribution (the
// control in the corner) and light use, which a small dashboard satisfies.
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';
const FIT = { padding: [28, 28], maxZoom: 16 };

const toPoint = (s) => [s.latitude, s.longitude];

export default function StationMap({ stations, selectedId, onSelect }) {
  const canvasRef = useRef(null);
  const mapRef = useRef(null);
  const groupRef = useRef(null);
  const markersRef = useRef(new Map());
  const ringRef = useRef(null);
  const fittedFor = useRef("");
  const [mapVersion, setMapVersion] = useState(0); // bumps every time a map is (re)created
  const [failed, setFailed] = useState(false);

  // Handlers live in refs so the Leaflet listeners never go stale.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;

  const valid = useMemo(
    () =>
      (stations ?? []).filter(
        (s) => Number.isFinite(s.latitude) && Number.isFinite(s.longitude),
      ),
    [stations],
  );
  const hasPositions = valid.length > 0;
  const validRef = useRef(valid);
  validRef.current = valid;

  // 1. Create the map once, as soon as there is something to show.
  useEffect(() => {
    if (!hasPositions || mapRef.current || !canvasRef.current) return;
    try {
      const map = L.map(canvasRef.current, {
        // On a phone one finger should scroll the page, two fingers move the map.
        dragging: !L.Browser.mobile,
        touchZoom: true,
        scrollWheelZoom: false,
      });
      L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);
      groupRef.current = L.layerGroup().addTo(map);

      const points = validRef.current.map(toPoint);
      map.fitBounds(L.latLngBounds(points), FIT);
      fittedFor.current = validRef.current.map((s) => s.id).sort().join("|");

      // Mouse wheel zooms the map only after you click it, so scrolling the page never gets stuck.
      map.on("click", () => map.scrollWheelZoom.enable());
      map.on("mouseout", () => map.scrollWheelZoom.disable());

      mapRef.current = map;
      setMapVersion((v) => v + 1);
    } catch (err) {
      console.error("Map failed to start:", err);
      setFailed(true);
    }
  }, [hasPositions]);

  // 2. Draw the stations. Rebuilt on every refresh (60 dots is nothing).
  useEffect(() => {
    const map = mapRef.current;
    const group = groupRef.current;
    if (!map || !group) return;
    try {
      group.clearLayers();
      markersRef.current.clear();
      ringRef.current = null;

      for (const s of valid) {
        const level = stationLevel(s.free_bikes);
        const marker = L.circleMarker(toPoint(s), {
          radius: 7,
          weight: 1.5,
          opacity: 1,
          fillOpacity: 1,
          className: `dot lvl-${level}`, // colours come from CSS (theme aware)
        });
        marker.bindTooltip(`${s.name ?? s.id}: ${fmtInt(s.free_bikes)} bikes`, {
          direction: "top",
          offset: [0, -6],
        });
        marker.on("click", () =>
          onSelectRef.current(selectedRef.current === s.id ? null : s.id),
        );
        group.addLayer(marker);
        markersRef.current.set(s.id, marker);
      }

      // Re-fit only when the set of stations changed, never on a plain refresh,
      // otherwise the map would jump back while the user is looking around.
      const signature = valid.map((s) => s.id).sort().join("|");
      if (signature !== fittedFor.current) {
        map.fitBounds(L.latLngBounds(valid.map(toPoint)), FIT);
        fittedFor.current = signature;
      }
    } catch (err) {
      console.error("Map update failed:", err);
      setFailed(true);
    }
  }, [valid, mapVersion]);

  // 3. Highlight the selected station.
  useEffect(() => {
    const map = mapRef.current;
    const group = groupRef.current;
    if (!map || !group) return;
    try {
      if (ringRef.current) group.removeLayer(ringRef.current);
      ringRef.current = null;
      const marker = selectedId != null ? markersRef.current.get(selectedId) : null;
      if (!marker) return;
      const ring = L.circleMarker(marker.getLatLng(), {
        radius: 13,
        weight: 2,
        fill: false,
        interactive: false,
        className: "ring",
      });
      group.addLayer(ring);
      ringRef.current = ring;
      marker.bringToFront();
      // selected from the list while off-screen: bring it into view
      if (!map.getBounds().contains(marker.getLatLng())) map.panTo(marker.getLatLng());
    } catch (err) {
      console.error("Map selection failed:", err);
    }
  }, [selectedId, valid, mapVersion]);

  // 4. Keep the map sized correctly when its box changes (rotation, layout).
  useEffect(() => {
    const el = canvasRef.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(() => mapRef.current?.invalidateSize());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 5. Clean up on unmount.
  useEffect(
    () => () => {
      mapRef.current?.remove();
      mapRef.current = null;
      groupRef.current = null;
      markersRef.current.clear();
      ringRef.current = null;
      fittedFor.current = "";
    },
    [],
  );

  const selected = (stations ?? []).find((s) => s.id === selectedId) ?? null;

  return (
    <section className="card map-card" aria-labelledby="map-title">
      <div className="card-head">
        <div>
          <h2 id="map-title">Station map</h2>
          <p className="muted small">Tap a station for details</p>
        </div>
        <ul className="legend" aria-label="Legend">
          <li><span className="swatch lvl-empty" />0</li>
          <li><span className="swatch lvl-low" />1–3</li>
          <li><span className="swatch lvl-ok" />4+</li>
        </ul>
      </div>

      <div className="map-wrap">
        <div className="map-canvas" ref={canvasRef} hidden={failed} />
        {failed ? <div className="empty-note">The map could not be loaded.</div> : null}
        {!failed && stations === null ? <div className="skeleton map-skeleton" /> : null}
        {!failed && stations !== null && !hasPositions ? (
          <div className="empty-note">No station positions yet.</div>
        ) : null}
      </div>

      {selected ? (
        <div className="map-info" role="status">
          <strong>{selected.name ?? selected.id}</strong>
          <span>
            {fmtInt(selected.free_bikes)} bikes
            {selected.ebikes > 0 ? ` (${selected.ebikes} electric)` : ""} · {fmtInt(selected.empty_slots)} free docks
          </span>
        </div>
      ) : null}
    </section>
  );
}
