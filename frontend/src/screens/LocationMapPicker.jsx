import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";
import { X } from "lucide-react";

import { useLanguage } from "../i18n/LanguageContext";

// Vite serves Leaflet's default marker images at hashed URLs; without this
// remap the marker renders as a broken image icon.
const markerIconDefault = L.icon({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

// Geographic centre of India — only used when the selected village has no
// known coordinates, so the picker still opens to something reasonable.
const INDIA_CENTER = [22.5, 80];

// A standalone OpenStreetMap + Leaflet pin picker. Purely a UI affordance for
// capturing an optional "proposed business location" (address/pincode plus
// a lat/lng pin) — it never looks up nearby villages, never touches
// village_lgd, and never feeds into viability/scoring. The caller decides
// what (if anything) to do with the coordinates it returns.
export default function LocationMapPicker({ villageCenter, initialPosition, onConfirm, onCancel }) {
  const { t } = useLanguage();
  const containerRef = useRef(null);
  const markerRef = useRef(null);
  const [position, setPosition] = useState(initialPosition || null);

  useEffect(() => {
    const startCenter = initialPosition
      ? [initialPosition.lat, initialPosition.lng]
      : villageCenter || INDIA_CENTER;
    const startZoom = initialPosition ? 16 : villageCenter ? 14 : 5;

    const map = L.map(containerRef.current, {
      center: startCenter,
      zoom: startZoom,
    });

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map);

    const marker = L.marker(startCenter, {
      icon: markerIconDefault,
      draggable: true,
    }).addTo(map);
    markerRef.current = marker;

    if (initialPosition) setPosition(initialPosition);

    marker.on("dragend", () => {
      const latlng = marker.getLatLng();
      setPosition({ lat: latlng.lat, lng: latlng.lng });
    });

    map.on("click", (event) => {
      marker.setLatLng(event.latlng);
      setPosition({ lat: event.latlng.lat, lng: event.latlng.lng });
    });

    // The map is created inside a just-mounted overlay; Leaflet needs a
    // recalculation once its container actually has a real size.
    const resizeTimer = setTimeout(() => map.invalidateSize(), 0);

    return () => {
      clearTimeout(resizeTimer);
      map.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4">
      <div className="flex w-full max-w-lg flex-col overflow-hidden rounded-t-3xl bg-white sm:rounded-3xl">
        <div className="flex items-center justify-between border-b border-stone-100 p-4">
          <h3 className="text-sm font-bold">{t("locationPicker.title")}</h3>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-full p-1 text-stone-400 hover:text-stone-600"
            aria-label={t("common.cancel")}
          >
            <X size={18} />
          </button>
        </div>

        <p className="px-4 pt-3 text-xs text-stone-500">{t("locationPicker.hint")}</p>

        <div ref={containerRef} className="mt-3 h-72 w-full sm:h-96" />

        <div className="flex items-center justify-between gap-3 border-t border-stone-100 p-4">
          <p className="min-w-0 flex-1 truncate text-xs font-medium text-stone-600">
            {position ? `${position.lat.toFixed(5)}, ${position.lng.toFixed(5)}` : t("locationPicker.noPin")}
          </p>
          <div className="flex shrink-0 gap-2">
            <button type="button" className="btn-secondary" onClick={onCancel}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={!position}
              onClick={() => position && onConfirm(position)}
            >
              {t("locationPicker.use")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
