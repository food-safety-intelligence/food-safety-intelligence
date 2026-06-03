"use client";

import {
  Map,
  Marker,
  Popup,
  NavigationControl,
  useMap,
} from "react-map-gl/maplibre";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";

import type { PinSummary, RiskTier } from "@/lib/scores";
import { TIER_HEX } from "@/lib/scores";

/**
 * Real Chicago map via maplibre-gl + CartoDB Voyager raster tiles. No API
 * key needed. Voyager pairs warmly with the Clinical Quiet cream palette.
 *
 * Pin density is zoom-aware: at low zoom we render only the top ~80 most
 * prominent restaurants (sorted by risk_score, which doubles as a proxy
 * for "worth surfacing" in a food-safety context); as the viewer zooms in
 * we add more and clip to the viewport so the map never overcrowds.
 */

const CHICAGO_CENTER = { lat: 41.881, lon: -87.629, zoom: 11.6 };

const VOYAGER_STYLE = {
  version: 8 as const,
  sources: {
    "carto-voyager": {
      type: "raster" as const,
      tiles: [
        "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "https://d.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
    },
  },
  layers: [
    {
      id: "carto-voyager",
      type: "raster" as const,
      source: "carto-voyager",
      minzoom: 0,
      maxzoom: 19,
    },
  ],
};

/**
 * Zoom → density rule. The cap grows roughly geometrically with zoom; the
 * viewport-clip kicks in at zoom ≥ 13 so we stop drawing pins the user
 * can't see anyway. Numbers tuned by feel — adjust if the map ever feels
 * crowded or sparse.
 */
function pinCapForZoom(zoom: number): number {
  if (zoom < 11) return 80;
  if (zoom < 12.5) return 250;
  if (zoom < 13.5) return 600;
  return 1500;
}

export function MapView({
  pins,
  className = "",
}: {
  pins: PinSummary[];
  className?: string;
}) {
  const [selected, setSelected] = useState<PinSummary | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);

  return (
    <div className={className}>
      <Map
        initialViewState={{
          latitude: CHICAGO_CENTER.lat,
          longitude: CHICAGO_CENTER.lon,
          zoom: CHICAGO_CENTER.zoom,
        }}
        mapStyle={VOYAGER_STYLE as never}
        style={{ width: "100%", height: "100%" }}
      >
        <NavigationControl position="bottom-right" showCompass={false} />

        <PinLayer
          pins={pins}
          hovered={hovered}
          selected={selected}
          onHover={setHovered}
          onSelect={setSelected}
        />

        {selected && (
          <Popup
            latitude={selected.lat}
            longitude={selected.lon}
            anchor="bottom"
            closeButton={false}
            closeOnClick={false}
            onClose={() => setSelected(null)}
            maxWidth="280px"
            offset={32}
            className="fsi-popup"
          >
            <div className="relative pr-1">
              <button
                type="button"
                onClick={() => setSelected(null)}
                aria-label="Close"
                className="absolute -top-1 -right-1 w-6 h-6 rounded-full bg-tint hover:bg-line text-muted text-[14px] leading-none flex items-center justify-center"
              >
                ×
              </button>
              <div className="flex items-center gap-2 mb-1.5 pr-6">
                <span
                  className="inline-block w-2 h-2 rounded-full"
                  style={{ background: TIER_HEX[selected.risk_tier] }}
                />
                <span className="text-[10.5px] uppercase tracking-[0.14em] text-muted font-medium">
                  {selected.risk_tier}
                </span>
                <span className="num text-[14px] font-medium ml-auto">
                  {selected.risk_score.toFixed(2)}
                </span>
              </div>
              <div className="font-semibold text-[14px] leading-tight">
                {selected.dba_name}
              </div>
              <div className="text-[11.5px] text-muted mt-0.5">
                {selected.address}
              </div>
              <Link
                href={`/restaurant/${selected.license_id}`}
                className="text-[12px] text-teal underline mt-2 inline-block"
              >
                Open profile →
              </Link>
            </div>
          </Popup>
        )}
      </Map>
    </div>
  );
}

/**
 * Inner component that reads the map handle and recomputes the visible
 * pin set on every zoom/pan. Split out from MapView because `useMap()`
 * only works inside the <Map> tree.
 */
function PinLayer({
  pins,
  hovered,
  selected,
  onHover,
  onSelect,
}: {
  pins: PinSummary[];
  hovered: string | null;
  selected: PinSummary | null;
  onHover: (id: string | null) => void;
  onSelect: (p: PinSummary | null) => void;
}) {
  const { current: map } = useMap();
  const [zoom, setZoom] = useState(CHICAGO_CENTER.zoom);
  const [bounds, setBounds] = useState<{
    n: number;
    s: number;
    e: number;
    w: number;
  } | null>(null);

  const syncFromMap = useCallback(() => {
    if (!map) return;
    setZoom(map.getZoom());
    const b = map.getBounds();
    setBounds({
      n: b.getNorth(),
      s: b.getSouth(),
      e: b.getEast(),
      w: b.getWest(),
    });
  }, [map]);

  useEffect(() => {
    if (!map) return;
    syncFromMap();
    map.on("moveend", syncFromMap);
    map.on("zoomend", syncFromMap);
    return () => {
      map.off("moveend", syncFromMap);
      map.off("zoomend", syncFromMap);
    };
  }, [map, syncFromMap]);

  // pins prop comes in pre-sorted by risk_score desc (server-side). Take
  // the top N for the current zoom; clip to viewport when zoomed in.
  const visible = useMemo(() => {
    const cap = pinCapForZoom(zoom);
    const clip = zoom >= 13 && bounds;
    const out: PinSummary[] = [];
    for (const p of pins) {
      if (out.length >= cap) break;
      if (clip) {
        if (
          p.lat > bounds.n ||
          p.lat < bounds.s ||
          p.lon > bounds.e ||
          p.lon < bounds.w
        ) {
          continue;
        }
      }
      out.push(p);
    }
    return out;
  }, [pins, zoom, bounds]);

  return (
    <>
      {visible.map((p) => (
        <Marker
          key={p.license_id}
          latitude={p.lat}
          longitude={p.lon}
          anchor="bottom"
          onClick={(e) => {
            e.originalEvent.stopPropagation();
            onSelect(p);
          }}
        >
          <TeardropPin
            tier={p.risk_tier}
            isHovered={hovered === p.license_id}
            isSelected={selected?.license_id === p.license_id}
            onMouseEnter={() => onHover(p.license_id)}
            onMouseLeave={() => onHover(null)}
            label={`${p.dba_name} — ${p.risk_tier} risk`}
          />
        </Marker>
      ))}
    </>
  );
}

/**
 * Teardrop pin: an SVG path that anchors at the bottom point. The fill is
 * the tier colour; the inner white dot reads at small zooms. A soft drop
 * shadow + outer halo on hover/select gives it a tactile, modern feel.
 */
function TeardropPin({
  tier,
  isHovered,
  isSelected,
  onMouseEnter,
  onMouseLeave,
  label,
}: {
  tier: RiskTier;
  isHovered: boolean;
  isSelected: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  label: string;
}) {
  const color = TIER_HEX[tier];
  const active = isHovered || isSelected;

  return (
    <button
      type="button"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      aria-label={label}
      className={[
        "block bg-transparent border-0 p-0 cursor-pointer",
        "transition-transform duration-150 ease-out",
        "origin-bottom",
        active ? "scale-125 z-10" : "",
      ].join(" ")}
      style={{ filter: "drop-shadow(0 2px 3px rgba(0,0,0,0.28))" }}
    >
      <svg
        width={24}
        height={30}
        viewBox="0 0 24 30"
        xmlns="http://www.w3.org/2000/svg"
      >
        {active && (
          <circle cx={12} cy={12} r={11} fill={color} opacity={0.18} />
        )}
        <path
          d="M12 0 C 17.5 0 22 4.5 22 10 C 22 17 13.5 26.5 12.7 29.2 C 12.4 30.2 11.6 30.2 11.3 29.2 C 10.5 26.5 2 17 2 10 C 2 4.5 6.5 0 12 0 Z"
          fill={color}
          stroke="#FFFFFF"
          strokeWidth={1.5}
        />
        <circle cx={12} cy={10} r={3.5} fill="#FFFFFF" />
      </svg>
    </button>
  );
}
