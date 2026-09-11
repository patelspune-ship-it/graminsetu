import { useEffect, useMemo, useRef, useState } from "react";
import { geoCentroid, geoMercator } from "d3-geo";
import { ComposableMap, Geographies, Geography } from "react-simple-maps";
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Info,
  LoaderCircle,
  MapPin,
  TriangleAlert,
} from "lucide-react";

import { useLanguage } from "../i18n/LanguageContext";

// Villages are only ingested (with real population data) for these two
// districts. Everywhere else in Maharashtra is on the map but not yet
// backed by village-level evidence.
const PILOT_DISTRICTS = ["Nashik", "Jalgaon"];
const LIVE_STATE = "Maharashtra";

const INDIA_GEOJSON_URL = "/maps/india-states.geojson";
const MAHARASHTRA_GEOJSON_URL = "/maps/maharashtra-districts.geojson";

function useGeoJson(url) {
  const [state, setState] = useState({ data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    setState({ data: null, error: null });

    fetch(url)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Could not load ${url} (${response.status}).`);
        }
        return response.json();
      })
      .then((json) => {
        if (!cancelled) setState({ data: json, error: null });
      })
      .catch((err) => {
        if (!cancelled) setState({ data: null, error: err.message });
      });

    return () => {
      cancelled = true;
    };
  }, [url]);

  return state;
}

// Measures the rendered pixel width of the map's wrapping element so label
// font sizes can be converted from "CSS pixels" to SVG user-space units and
// stay legible regardless of the viewBox scale (mobile vs. desktop).
function useElementWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") return undefined;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return [ref, width];
}

// A non-interactive, halo-outlined label so text stays readable over any
// region fill color without blocking clicks/hover on the map shape beneath.
function MapLabel({ x, y, fontSize, bold, emphasis, children }) {
  return (
    <text
      x={x}
      y={y}
      textAnchor="middle"
      dominantBaseline="middle"
      fontSize={fontSize}
      fontWeight={bold ? 700 : 500}
      fill={emphasis ? "#ffffff" : "#2c3a27"}
      stroke={emphasis ? "#0f4a34" : "#f7f8f2"}
      strokeWidth={fontSize * 0.28}
      paintOrder="stroke"
      style={{ pointerEvents: "none", userSelect: "none" }}
    >
      {children}
    </text>
  );
}

function MapStatus({ children }) {
  return (
    <div className="flex h-72 items-center justify-center rounded-2xl border border-stone-200 bg-stone-50 text-sm text-stone-500 sm:h-96">
      {children}
    </div>
  );
}

function Breadcrumb({ items, ariaLabel }) {
  return (
    <nav
      aria-label={ariaLabel}
      className="flex flex-wrap items-center gap-x-1 gap-y-1 text-xs font-medium sm:text-sm"
    >
      {items.map((item, index) => (
        <span key={`${item.label}-${index}`} className="flex items-center gap-1">
          {index > 0 && (
            <ChevronRight size={14} className="shrink-0 text-stone-300" />
          )}
          {item.onClick ? (
            <button
              type="button"
              onClick={item.onClick}
              className="rounded px-1 py-0.5 text-forest hover:underline"
            >
              {item.label}
            </button>
          ) : (
            <span
              className="px-1 py-0.5 text-ink"
              aria-current={index === items.length - 1 ? "location" : undefined}
            >
              {item.label}
            </span>
          )}
        </span>
      ))}
    </nav>
  );
}

const INDIA_VIEWBOX_WIDTH = 800;

function IndiaMap({ hoveredState, onHoverState, onSelectState }) {
  const { t } = useLanguage();
  const { data: geojson, error } = useGeoJson(INDIA_GEOJSON_URL);
  const [containerRef, containerWidth] = useElementWidth();

  const projection = useMemo(() => {
    if (!geojson) return null;
    return geoMercator().fitSize([800, 780], geojson);
  }, [geojson]);

  // The source file is district-granularity, so a state can have dozens of
  // features. Average each state's district centroids into one label point
  // instead of repeating the state name once per district.
  const stateLabelPoints = useMemo(() => {
    if (!geojson) return [];

    const totals = new Map();

    for (const feature of geojson.features) {
      const name = feature.properties?.st_nm;
      if (!name) continue;

      const [lon, lat] = geoCentroid(feature);
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;

      const entry = totals.get(name) || { lon: 0, lat: 0, count: 0 };
      entry.lon += lon;
      entry.lat += lat;
      entry.count += 1;
      totals.set(name, entry);
    }

    return Array.from(totals, ([name, { lon, lat, count }]) => ({
      name,
      position: [lon / count, lat / count],
    }));
  }, [geojson]);

  const pxScale = containerWidth > 0 ? containerWidth / INDIA_VIEWBOX_WIDTH : 1;

  if (error) {
    return (
      <MapStatus>
        <span className="flex items-center gap-2 px-4 text-center">
          <TriangleAlert size={16} className="shrink-0 text-red-400" />
          {t("village.errorIndiaMap")}
        </span>
      </MapStatus>
    );
  }

  if (!geojson || !projection) {
    return (
      <MapStatus>
        <span className="flex items-center gap-2">
          <LoaderCircle size={16} className="animate-spin" />
          {t("village.loadingIndiaMap")}
        </span>
      </MapStatus>
    );
  }

  return (
    <div ref={containerRef} className="w-full">
      <ComposableMap
        width={800}
        height={780}
        projection={projection}
        className="h-auto max-h-[65vh] w-full"
        role="img"
        aria-label={t("village.heading")}
      >
        <Geographies geography={geojson}>
          {({ geographies }) =>
            geographies.map((geo) => {
              const stateName = geo.properties.st_nm;
              const isMaharashtra = stateName === LIVE_STATE;
              const isHovered = hoveredState === stateName;

              return (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  tabIndex={0}
                  role="button"
                  aria-label={`${stateName}${isMaharashtra ? " — village data live" : ""}`}
                  onMouseEnter={() => onHoverState(stateName)}
                  onMouseLeave={() => onHoverState(null)}
                  onFocus={() => onHoverState(stateName)}
                  onBlur={() => onHoverState(null)}
                  onClick={() => onSelectState(stateName)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelectState(stateName);
                    }
                  }}
                  fill={
                    isMaharashtra
                      ? isHovered
                        ? "#0f4a34"
                        : "#176448"
                      : isHovered
                        ? "#c3d4b8"
                        : "#e4e9dc"
                  }
                  stroke="#f7f8f2"
                  strokeWidth={0.6}
                  style={{ outline: "none", cursor: "pointer", transition: "fill 120ms ease" }}
                />
              );
            })
          }
        </Geographies>

        {stateLabelPoints.map(({ name, position }) => {
          const point = projection(position);
          if (!point) return null;

          const isMaharashtra = name === LIVE_STATE;
          const fontSize = (isMaharashtra ? 12 : 8) / pxScale;

          return (
            <MapLabel
              key={name}
              x={point[0]}
              y={point[1]}
              fontSize={fontSize}
              bold={isMaharashtra}
              emphasis={isMaharashtra}
            >
              {name}
            </MapLabel>
          );
        })}
      </ComposableMap>
    </div>
  );
}

const MAHARASHTRA_VIEWBOX_WIDTH = 800;

function MaharashtraDistrictMap({ hoveredDistrict, onHoverDistrict, onSelectDistrict }) {
  const { t } = useLanguage();
  const { data: geojson, error } = useGeoJson(MAHARASHTRA_GEOJSON_URL);
  const [containerRef, containerWidth] = useElementWidth();

  const projection = useMemo(() => {
    if (!geojson) return null;
    return geoMercator().fitSize([800, 680], geojson);
  }, [geojson]);

  const pxScale = containerWidth > 0 ? containerWidth / MAHARASHTRA_VIEWBOX_WIDTH : 1;

  if (error) {
    return (
      <MapStatus>
        <span className="flex items-center gap-2 px-4 text-center">
          <TriangleAlert size={16} className="shrink-0 text-red-400" />
          {t("village.errorMaharashtraMap")}
        </span>
      </MapStatus>
    );
  }

  if (!geojson || !projection) {
    return (
      <MapStatus>
        <span className="flex items-center gap-2">
          <LoaderCircle size={16} className="animate-spin" />
          {t("village.loadingMaharashtraMap")}
        </span>
      </MapStatus>
    );
  }

  return (
    <div ref={containerRef} className="w-full">
      <ComposableMap
        width={800}
        height={680}
        projection={projection}
        className="h-auto max-h-[65vh] w-full"
        role="img"
        aria-label={t("village.chooseVillage")}
      >
        <Geographies geography={geojson}>
          {({ geographies }) =>
            geographies.map((geo) => {
              const districtName = geo.properties.district;
              const isPilot = PILOT_DISTRICTS.includes(districtName);
              const isHovered = hoveredDistrict === districtName;

              return (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  tabIndex={0}
                  role="button"
                  aria-label={`${districtName}${
                    isPilot ? " — village data live" : " — village data not yet ingested"
                  }`}
                  onMouseEnter={() => onHoverDistrict(districtName)}
                  onMouseLeave={() => onHoverDistrict(null)}
                  onFocus={() => onHoverDistrict(districtName)}
                  onBlur={() => onHoverDistrict(null)}
                  onClick={() => onSelectDistrict(districtName)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelectDistrict(districtName);
                    }
                  }}
                  fill={
                    isPilot
                      ? isHovered
                        ? "#0f4a34"
                        : "#176448"
                      : isHovered
                        ? "#eef1e6"
                        : "#ffffff"
                  }
                  stroke={isPilot ? "#f7f8f2" : "#8a9a7f"}
                  strokeWidth={isPilot ? 0.6 : 1}
                  style={{ outline: "none", cursor: "pointer", transition: "fill 120ms ease" }}
                />
              );
            })
          }
        </Geographies>

        {geojson.features.map((feature) => {
          const districtName = feature.properties?.district;
          if (!districtName) return null;

          const point = projection(geoCentroid(feature));
          if (!point) return null;

          const isPilot = PILOT_DISTRICTS.includes(districtName);
          const fontSize = (isPilot ? 11 : 7.5) / pxScale;

          return (
            <MapLabel
              key={districtName}
              x={point[0]}
              y={point[1]}
              fontSize={fontSize}
              bold={isPilot}
              emphasis={isPilot}
            >
              {districtName}
            </MapLabel>
          );
        })}
      </ComposableMap>
    </div>
  );
}

function initialNavState(selectedVillage) {
  if (!selectedVillage) {
    return { view: "india", selectedState: null, selectedDistrict: null };
  }

  return {
    view: "villages",
    selectedState: selectedVillage.state || LIVE_STATE,
    selectedDistrict: selectedVillage.district,
  };
}

function VillageMapStep({
  villages,
  loading,
  villageId,
  setVillageId,
  selectedVillage,
  onContinue,
}) {
  const { t } = useLanguage();
  const [{ view, selectedState, selectedDistrict }, setNav] = useState(() =>
    initialNavState(selectedVillage)
  );
  const [hoveredState, setHoveredState] = useState(null);
  const [hoveredDistrict, setHoveredDistrict] = useState(null);
  const [villageQuery, setVillageQuery] = useState("");

  function goToIndia() {
    setVillageId("");
    setVillageQuery("");
    setNav({ view: "india", selectedState: null, selectedDistrict: null });
  }

  function goToStateDistricts(stateName) {
    setVillageId("");
    setVillageQuery("");
    setNav({ view: "state-districts", selectedState: stateName, selectedDistrict: null });
  }

  function goToVillageList(districtName) {
    setVillageId("");
    setVillageQuery("");
    setNav((current) => ({ ...current, view: "villages", selectedDistrict: districtName }));
  }

  const districtVillages = useMemo(
    () => villages.filter((village) => village.district === selectedDistrict),
    [villages, selectedDistrict]
  );

  const filteredVillages = useMemo(
    () =>
      districtVillages.filter((village) =>
        village.name.toLowerCase().includes(villageQuery.trim().toLowerCase())
      ),
    [districtVillages, villageQuery]
  );

  const visibleVillages = filteredVillages.slice(0, 24);

  const isPilotDistrict = PILOT_DISTRICTS.includes(selectedDistrict);
  const isLiveState = selectedState === LIVE_STATE;

  const breadcrumbItems = useMemo(() => {
    const items = [{ label: "India", onClick: view !== "india" ? goToIndia : undefined }];

    if (selectedState) {
      items.push({
        label: selectedState,
        onClick: view !== "state-districts" ? () => goToStateDistricts(selectedState) : undefined,
      });
    }

    if (view === "villages" && selectedDistrict) {
      const hasVillage = selectedVillage && selectedVillage.district === selectedDistrict;
      items.push({
        label: selectedDistrict,
        onClick: hasVillage ? () => goToVillageList(selectedDistrict) : undefined,
      });

      if (hasVillage) {
        items.push({ label: selectedVillage.name, onClick: undefined });
      }
    }

    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, selectedState, selectedDistrict, selectedVillage]);

  return (
    <section className="card fade-in">
      <p className="eyebrow">{t("village.eyebrow")}</p>
      <h2 className="mt-2 text-2xl font-bold tracking-tight">
        {t("village.heading")}
      </h2>
      <p className="mt-2 text-sm leading-6 text-stone-500">
        {t("village.subheading")}
      </p>

      <div className="mt-5 rounded-2xl border border-stone-200 bg-stone-50 px-4 py-3">
        <Breadcrumb items={breadcrumbItems} ariaLabel={t("village.breadcrumbLabel")} />
      </div>

      <div className="mt-5">
        {view === "india" && (
          <>
            <div className="mb-3 flex min-h-6 items-center gap-2 text-sm font-semibold text-ink">
              <MapPin size={15} className="shrink-0 text-forest" />
              {hoveredState || t("village.tapState")}
            </div>
            <IndiaMap
              hoveredState={hoveredState}
              onHoverState={setHoveredState}
              onSelectState={(stateName) => {
                setHoveredState(null);
                goToStateDistricts(stateName);
              }}
            />
            <p className="mt-3 flex items-center gap-2 text-xs text-stone-500">
              <span className="inline-block h-3 w-3 shrink-0 rounded-sm bg-forest" />
              {t("village.legend.maharashtra")}
            </p>
          </>
        )}

        {view === "state-districts" && isLiveState && (
          <>
            <div className="mb-3 flex min-h-6 items-center gap-2 text-sm font-semibold text-ink">
              <MapPin size={15} className="shrink-0 text-forest" />
              {hoveredDistrict || t("village.tapDistrict")}
            </div>
            <MaharashtraDistrictMap
              hoveredDistrict={hoveredDistrict}
              onHoverDistrict={setHoveredDistrict}
              onSelectDistrict={(districtName) => {
                setHoveredDistrict(null);
                goToVillageList(districtName);
              }}
            />
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-stone-500">
              <span className="flex items-center gap-2">
                <span className="inline-block h-3 w-3 shrink-0 rounded-sm bg-forest" />
                {t("village.legend.pilotDistricts")}
              </span>
              <span className="flex items-center gap-2">
                <span className="inline-block h-3 w-3 shrink-0 rounded-sm border border-stone-400 bg-white" />
                {t("village.legend.otherDistricts")}
              </span>
            </div>
          </>
        )}

        {view === "state-districts" && !isLiveState && (
          <div className="flex flex-col items-start gap-3 rounded-2xl border border-dashed border-stone-300 bg-stone-50 p-6 text-sm text-stone-600">
            <Info size={20} className="text-forest" />
            <p>{t("village.districtFallback")}</p>
            <button
              type="button"
              className="btn-secondary"
              onClick={goToIndia}
            >
              <ChevronLeft size={16} /> {t("village.backToIndia")}
            </button>
          </div>
        )}

        {view === "villages" && isPilotDistrict && (
          <fieldset>
            <legend className="label">{t("village.chooseVillage")}</legend>

            {loading ? (
              <div className="mt-4 flex items-center gap-2 text-sm text-stone-500">
                <LoaderCircle size={17} className="animate-spin" />
                {t("village.loadingLocations")}
              </div>
            ) : districtVillages.length === 0 ? (
              <p className="mt-4 text-sm text-stone-500">
                {t("village.noRecords")}
              </p>
            ) : (
              <>
                <input
                  type="search"
                  className="field mt-3"
                  placeholder={t("village.searchPlaceholder", { count: districtVillages.length })}
                  value={villageQuery}
                  onChange={(event) => setVillageQuery(event.target.value)}
                />

                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {visibleVillages.map((village) => {
                    const selected = villageId === village.id;

                    return (
                      <label
                        key={village.id}
                        className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 transition ${
                          selected
                            ? "border-forest bg-forest/5"
                            : "border-stone-200 hover:border-forest/40"
                        }`}
                      >
                        <input
                          type="radio"
                          name="village"
                          value={village.id}
                          checked={selected}
                          onChange={() => setVillageId(village.id)}
                          className="mt-1 h-4 w-4 accent-[#176448]"
                        />

                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-semibold">
                            {village.name}
                          </div>
                          <div className="mt-1 text-xs leading-5 text-stone-500">
                            {village.district}
                          </div>
                          <div className="mt-1 text-xs leading-5 text-stone-400">
                            {village.source}
                          </div>
                        </div>

                        <MapPin size={18} className="mt-0.5 shrink-0 text-forest" />
                      </label>
                    );
                  })}
                </div>

                {filteredVillages.length === 0 ? (
                  <p className="mt-3 text-sm text-stone-500">
                    {t("village.noMatch")}
                  </p>
                ) : filteredVillages.length > visibleVillages.length ? (
                  <p className="mt-3 text-sm text-stone-500">
                    {t("village.showingMatches", {
                      shown: visibleVillages.length,
                      total: filteredVillages.length,
                    })}
                  </p>
                ) : null}
              </>
            )}

            <button
              type="button"
              className="btn-secondary mt-5"
              onClick={() => goToStateDistricts(selectedState)}
            >
              <ChevronLeft size={16} /> {t("village.backToDistrictMap")}
            </button>
          </fieldset>
        )}

        {view === "villages" && !isPilotDistrict && (
          <div className="flex flex-col items-start gap-3 rounded-2xl border border-dashed border-stone-300 bg-stone-50 p-6 text-sm text-stone-600">
            <Info size={20} className="text-forest" />
            <p>{t("village.villageFallback")}</p>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => goToStateDistricts(selectedState)}
            >
              <ChevronLeft size={16} /> {t("village.backToDistrictMap")}
            </button>
          </div>
        )}
      </div>

      <div className="mt-8 flex justify-end border-t border-stone-100 pt-5">
        <button
          type="button"
          className="btn-primary w-full sm:w-auto"
          disabled={!selectedVillage || loading}
          onClick={onContinue}
        >
          {t("village.continue")} <ArrowRight size={17} />
        </button>
      </div>
    </section>
  );
}

export default VillageMapStep;
