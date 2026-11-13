"use client";
import { useEffect, useState } from "react";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type SourceRef = { dataset_id: string; dataset: string; source: string; endpoint: string | null; license: string | null; publication: string | null; updated_at: string | null };
export type VarMeta = {
  spec: string; id: string | null; name: string; short_name: string; unit: string; custom: boolean; formula: string | null;
  nature: string; frequency: string; real: boolean; decimals: number; percent: boolean; limitations: string | null;
  breaks: { period: string; note: string }[]; methodology_id: string | null; div_zero: number; out_of_range?: number; notes: string[];
  components: { id: string; name: string; dataset_id: string }[]; sources: SourceRef[];
};
export type Indicator = {
  id: string; name: string; short_name: string; description: string | null; dimension: string; unit: string; percent: boolean;
  nature: string; value_kind: string; stock_flow: string; frequency: string; levels: string[]; status: string;
  formula: string | null; limitations: string | null; breaks: { period: string; note: string }[]; decimals: number;
  methodology_id: string | null; dataset: string | null; dataset_id: string | null; source: string | null; monetary: boolean;
  period_min?: string | null; period_max?: string | null; n_periods?: number;
};
export type Territory = { code: string; level: string; name: string; sigla: string | null; uf: string | null; uf_code: string | null };
export type Stats = { n: number; mean?: number; std?: number | null; min?: number; p10?: number; p25?: number; median?: number; p75?: number; p90?: number; max?: number };
export type MapData = {
  meta: VarMeta; level: string; level_name: string; period: string; periods: string[]; stats: Stats; breaks: number[];
  method: string; n_territories: number; n_missing: number; values: { code: string; value: number | null }[];
};
export type Dimension = { id: string; name: string; status: string };
export type AppMeta = {
  dimensions: Dimension[]; levels: { id: string; name: string }[]; indicators: Record<string, number>;
  counts: { observations: number; territories: number }; updated_at: string | null; start_year: number;
};

export class ApiError extends Error {}

const cache = new Map<string, unknown>();

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const key = init?.body ? `${path}::${init.body}` : path;
  if (cache.has(key)) return cache.get(key) as T;
  let r: Response;
  try {
    r = await fetch(API + path, init);
  } catch {
    throw new ApiError(`Não foi possível contatar a API do Atlas em ${API}. Verifique se o backend está em execução.`);
  }
  if (!r.ok) {
    let detail = `Erro ${r.status}`;
    try {
      const j = await r.json();
      if (typeof j.detail === "string") detail = j.detail;
      else if (Array.isArray(j.detail)) detail = j.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {}
    throw new ApiError(detail);
  }
  const j = (await r.json()) as T;
  if (cache.size > 300) cache.clear();
  cache.set(key, j);
  return j;
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export type Loadable<T> = { data: T | null; error: string | null; loading: boolean };

/** Busca dados da API; `path` nulo suspende a consulta. Para POST, passe `body`. */
export function useApi<T>(path: string | null, body?: unknown): Loadable<T> {
  const bodyKey = body === undefined ? "" : JSON.stringify(body);
  const [state, setState] = useState<Loadable<T> & { key: string }>({ data: null, error: null, loading: !!path, key: "" });
  const key = path ? path + bodyKey : "";
  useEffect(() => {
    if (!path) return;
    let alive = true;
    const p = bodyKey ? post<T>(path, JSON.parse(bodyKey)) : api<T>(path);
    p.then((data) => alive && setState({ data, error: null, loading: false, key }))
      .catch((e: Error) => alive && setState({ data: null, error: e.message, loading: false, key }));
    return () => {
      alive = false;
    };
  }, [path, bodyKey, key]);
  if (!path) return { data: null, error: null, loading: false };
  // Mantém o dado anterior visível enquanto a nova consulta carrega (evita "piscar").
  return { data: state.data, error: state.key === key ? state.error : null, loading: state.key !== key };
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "" && v !== false) u.set(k, String(v));
  const s = u.toString();
  return s ? "?" + s : "";
}

const geoCache = new Map<string, Promise<GeoJSON.FeatureCollection>>();
export function loadGeo(level: string): Promise<GeoJSON.FeatureCollection> {
  if (!geoCache.has(level)) {
    geoCache.set(
      level,
      fetch(`${API}/api/geo/${level}`).then((r) => {
        if (!r.ok) throw new ApiError("Malha territorial indisponível.");
        return r.json();
      }),
    );
  }
  return geoCache.get(level)!;
}

// Indicadores personalizados ficam no navegador do usuário (localStorage).
export type CustomIndicator = { name: string; expr: string };
const CK = "atlas.custom";
export function getCustom(): CustomIndicator[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(CK) ?? "[]");
  } catch {
    return [];
  }
}
export function saveCustom(list: CustomIndicator[]) {
  localStorage.setItem(CK, JSON.stringify(list));
  window.dispatchEvent(new Event("atlas:custom"));
}
