"use client";
import { Map as MlMap, NavigationControl, setWorkerUrl, type MapGeoJSONFeature } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState, type RefObject } from "react";
import { loadGeo } from "@/lib/api";
import { cssVar } from "@/lib/palettes";

if (typeof window !== "undefined") setWorkerUrl("/maplibre-gl-worker.mjs");

const BR_BOUNDS: [number, number, number, number] = [-74.2, -34.0, -28.6, 5.5];
export type MapSync = { maps: Set<MlMap>; busy: boolean };

type Props = {
  level: string;
  values: Map<string, number | null>;
  /** Cor de um valor não ausente (classes ou escala contínua). Memoize no componente pai. */
  colorOf: (v: number) => string;
  format: (v: number | null) => string;
  uf?: string;
  /** Códigos dos territórios selecionados (contorno forte). Memoize no componente pai. */
  selected?: string[];
  /** Território destacado por outro componente (ex.: linha do ranking). */
  hovered?: string | null;
  onHover?: (code: string | null) => void;
  onSelect?: (code: string, name: string) => void;
  sync?: RefObject<MapSync>;
  height?: string;
  ariaLabel: string;
};

type Tip = { x: number; y: number; w: number; name: string; uf?: string; code: string };

function bboxOf(features: GeoJSON.Feature[]): [number, number, number, number] | null {
  let x0 = 180, y0 = 90, x1 = -180, y1 = -90;
  const visit = (c: unknown) => {
    if (typeof (c as number[])[0] === "number") {
      const [x, y] = c as number[];
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    } else (c as unknown[]).forEach(visit);
  };
  features.forEach((f) => f.geometry && "coordinates" in f.geometry && visit(f.geometry.coordinates));
  return x1 >= x0 ? [x0, y0, x1, y1] : null;
}

export function ChoroMap({ level, values, colorOf, format, uf, selected, hovered, onHover, onSelect, sync, height = "100%", ariaLabel }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const geoRef = useRef<GeoJSON.FeatureCollection | null>(null);
  const [geoLevel, setGeoLevel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const cb = useRef({ onSelect, onHover });
  useEffect(() => { cb.current = { onSelect, onHover }; });
  const lastHover = useRef<string | null>(null);
  // Enquadramento: enquanto o usuário não mover o mapa, ele é reenquadrado quando o contêiner muda de tamanho.
  const boundsRef = useRef<[number, number, number, number]>(BR_BOUNDS);
  const movedRef = useRef(false);

  // Inicialização do mapa (sem mapa-base externo: apenas a malha do IBGE).
  useEffect(() => {
    if (!el.current) return;
    const map = new MlMap({
      container: el.current,
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": cssVar("--surface-2") } }] },
      bounds: BR_BOUNDS, fitBoundsOptions: { padding: 12 }, attributionControl: false, dragRotate: false,
      pitchWithRotate: false, touchPitch: false, maxZoom: 11, minZoom: 2, renderWorldCopies: false,
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.touchZoomRotate.disableRotation();
    mapRef.current = map;
    const s = sync?.current;
    s?.maps.add(map);
    map.on("move", () => {
      if (!s || s.busy) return;
      s.busy = true;
      s.maps.forEach((m) => m !== map && m.jumpTo({ center: map.getCenter(), zoom: map.getZoom() }));
      s.busy = false;
    });
    map.on("mousemove", "terr-fill", (e) => {
      const f = e.features?.[0] as MapGeoJSONFeature | undefined;
      if (!f) return;
      map.getCanvas().style.cursor = "pointer";
      const p = f.properties as { code: string; name: string; uf?: string };
      map.setFilter("terr-hover", ["==", ["get", "code"], p.code]);
      if (lastHover.current !== String(p.code)) {
        lastHover.current = String(p.code);
        cb.current.onHover?.(String(p.code));
      }
      setTip({ x: e.point.x, y: e.point.y, w: map.getContainer().clientWidth, name: p.name, uf: p.uf, code: String(p.code) });
    });
    map.on("mouseleave", "terr-fill", () => {
      map.getCanvas().style.cursor = "";
      if (map.getLayer("terr-hover")) map.setFilter("terr-hover", ["==", ["get", "code"], ""]);
      setTip(null);
      lastHover.current = null;
      cb.current.onHover?.(null);
    });
    map.on("click", "terr-fill", (e) => {
      const p = e.features?.[0]?.properties as { code: string; name: string } | undefined;
      if (p) cb.current.onSelect?.(String(p.code), p.name);
    });
    map.on("movestart", (e) => { if ((e as { originalEvent?: unknown }).originalEvent) movedRef.current = true; });
    const ro = new ResizeObserver(() => {
      map.resize();
      if (!movedRef.current) map.fitBounds(boundsRef.current, { padding: 12, duration: 0 });
    });
    ro.observe(el.current);
    const onTheme = () => {
      map.setPaintProperty("bg", "background-color", cssVar("--surface-2"));
      if (map.getLayer("terr-fill")) map.setPaintProperty("terr-fill", "fill-color", ["coalesce", ["feature-state", "color"], cssVar("--missing")]);
      if (map.getLayer("terr-line")) map.setPaintProperty("terr-line", "line-color", cssVar("--surface"));
      if (map.getLayer("uf-line")) map.setPaintProperty("uf-line", "line-color", cssVar("--ink"));
    };
    window.addEventListener("atlas:theme", onTheme);
    return () => {
      window.removeEventListener("atlas:theme", onTheme);
      ro.disconnect();
      s?.maps.delete(map);
      map.remove();
      mapRef.current = null;
    };
  }, [sync]);

  // Carrega a malha do nível territorial.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    let alive = true;
    const fine = ["MUN", "RGI", "RGINT"].includes(level);
    Promise.all([loadGeo(level), fine ? loadGeo("UF") : Promise.resolve(null)])
      .then(([geo, ufGeo]) => {
        if (!alive) return;
        const apply = () => {
          for (const id of ["terr-hover", "terr-selected", "uf-line", "terr-line", "terr-fill"]) if (map.getLayer(id)) map.removeLayer(id);
          for (const id of ["terr", "ufs"]) if (map.getSource(id)) map.removeSource(id);
          map.addSource("terr", { type: "geojson", data: geo, promoteId: "code", tolerance: 0.2 });
          map.addLayer({ id: "terr-fill", type: "fill", source: "terr",
            paint: { "fill-color": ["coalesce", ["feature-state", "color"], cssVar("--missing")] } });
          map.addLayer({ id: "terr-line", type: "line", source: "terr",
            paint: { "line-color": cssVar("--surface"), "line-width": ["interpolate", ["linear"], ["zoom"], 3, fine ? 0.05 : 0.6, 6, fine ? 0.4 : 1, 9, 1] } });
          if (ufGeo) {
            map.addSource("ufs", { type: "geojson", data: ufGeo });
            map.addLayer({ id: "uf-line", type: "line", source: "ufs", paint: { "line-color": cssVar("--ink"), "line-width": 0.7, "line-opacity": 0.55 } });
          }
          map.addLayer({ id: "terr-selected", type: "line", source: "terr", filter: ["==", ["get", "code"], ""],
            paint: { "line-color": cssVar("--ink"), "line-width": 2.5 } });
          map.addLayer({ id: "terr-hover", type: "line", source: "terr", filter: ["==", ["get", "code"], ""],
            paint: { "line-color": cssVar("--ink"), "line-width": 1.5 } });
          geoRef.current = geo;
          setGeoLevel(level);
          setError(null);
        };
        if (map.isStyleLoaded()) apply();
        else map.once("load", apply);
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [level]);

  // Pinta as classes (feature-state) sempre que dados, limites ou paleta mudam.
  useEffect(() => {
    const map = mapRef.current;
    const geo = geoRef.current;
    if (!map || !geo || geoLevel !== level || !map.getSource("terr")) return;
    map.removeFeatureState({ source: "terr" });
    for (const f of geo.features) {
      const code = String((f.properties as { code: string }).code);
      const v = values.get(code);
      if (v !== null && v !== undefined) map.setFeatureState({ source: "terr", id: code }, { color: colorOf(v) });
    }
  }, [values, colorOf, geoLevel, level]);

  // Recorte por UF: filtra a malha e enquadra o estado.
  useEffect(() => {
    const map = mapRef.current;
    const geo = geoRef.current;
    if (!map || !geo || geoLevel !== level || !map.getLayer("terr-fill")) return;
    const canFilter = level !== "UF" && level !== "REGIAO";
    const f = uf && canFilter ? (["==", ["get", "uf"], uf] as ["==", ["get", string], string]) : null;
    map.setFilter("terr-fill", f);
    map.setFilter("terr-line", f);
    const bb = uf && canFilter ? bboxOf(geo.features.filter((x) => (x.properties as { uf?: string }).uf === uf)) : BR_BOUNDS;
    if (bb) {
      boundsRef.current = bb;
      movedRef.current = false;
      map.fitBounds(bb, { padding: 16, duration: 400 });
    }
  }, [uf, geoLevel, level]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("terr-selected")) map.setFilter("terr-selected", ["in", ["get", "code"], ["literal", selected ?? []]]);
  }, [selected, geoLevel]);

  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer("terr-hover")) map.setFilter("terr-hover", ["==", ["get", "code"], hovered ?? ""]);
  }, [hovered, geoLevel]);

  const tv = tip ? values.get(tip.code) : undefined;
  return (
    <div className="relative overflow-hidden rounded-md border border-line" style={{ height }}>
      <div ref={el} className="h-full w-full" role="application" aria-label={ariaLabel} />
      {geoLevel !== level && !error && <p className="absolute inset-0 grid place-items-center text-sm text-muted">Carregando malha territorial…</p>}
      {error && <p role="alert" className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-danger">{error}</p>}
      {tip && (
        <div
          className="pointer-events-none absolute z-10 max-w-64 rounded border border-line bg-surface px-2.5 py-1.5 text-sm shadow-lg"
          style={{ left: Math.max(4, Math.min(tip.x + 14, tip.w - 220)), top: tip.y + 14 }}
        >
          <div className="font-medium">{tip.name}</div>
          <div className="num text-muted">{tv === null || tv === undefined ? "Sem dado (ausente)" : format(tv)}</div>
        </div>
      )}
    </div>
  );
}
