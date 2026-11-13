"use client";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import { useEffect, useRef, useState } from "react";
import { svgToPng } from "@/lib/exportMap";
import { download } from "@/lib/format";
import { cssVar } from "@/lib/palettes";

export type Theme = { ink: string; muted: string; line: string; surface: string; accent: string; series: string[] };

export function readTheme(): Theme {
  return {
    ink: cssVar("--ink"), muted: cssVar("--muted"), line: cssVar("--line"), surface: cssVar("--surface"), accent: cssVar("--accent"),
    series: Array.from({ length: 8 }, (_, i) => cssVar(`--series-${i + 1}`)),
  };
}

export function useThemeTick(): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const h = () => setTick((t) => t + 1);
    window.addEventListener("atlas:theme", h);
    return () => window.removeEventListener("atlas:theme", h);
  }, []);
  return tick;
}

/** Padrões compartilhados: tipografia, eixos discretos e tooltip na cor do tema. */
export function baseOption(t: Theme): EChartsOption {
  return {
    animationDuration: 250,
    color: t.series,
    textStyle: { fontFamily: "var(--font-plex-sans), sans-serif", color: t.ink },
    grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: t.surface, borderColor: t.line, textStyle: { color: t.ink, fontSize: 12 },
      extraCssText: "box-shadow:0 2px 10px rgba(0,0,0,.15);max-width:340px;white-space:normal;",
    },
    legend: { textStyle: { color: t.muted }, top: 0, type: "scroll" },
  };
}

export function axis(t: Theme, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    axisLine: { lineStyle: { color: t.line } }, axisTick: { lineStyle: { color: t.line } },
    axisLabel: { color: t.muted, fontSize: 11 }, splitLine: { lineStyle: { color: t.line, opacity: 0.55 } },
    nameTextStyle: { color: t.muted, fontSize: 11 }, ...extra,
  };
}

type Props = {
  build: (t: Theme) => EChartsOption | Record<string, unknown>;  // memoize no componente pai
  height?: number;
  renderer?: "canvas" | "svg";
  exportName?: string;
  ariaLabel: string;
  onPick?: (dataIndex: number, seriesIndex: number) => void;
};

export function Chart({ build, height = 360, renderer = "canvas", exportName, ariaLabel, onPick }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  const tick = useThemeTick();
  const pick = useRef(onPick);
  useEffect(() => { pick.current = onPick; });

  useEffect(() => {
    if (!el.current) return;
    const c = echarts.init(el.current, undefined, { renderer });
    inst.current = c;
    c.on("click", (p) => pick.current?.(p.dataIndex ?? -1, p.seriesIndex ?? 0));
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      c.dispose();
      inst.current = null;
    };
  }, [renderer]);

  useEffect(() => {
    inst.current?.setOption(build(readTheme()) as EChartsOption, true);
  }, [build, tick]);

  const exportAs = async (kind: "png" | "svg") => {
    const div = document.createElement("div");
    const w = Math.max(900, el.current?.clientWidth ?? 900);
    const c = echarts.init(div, undefined, { renderer: "svg", width: w, height: Math.max(height, 420) });
    const light: Theme = { ink: "#16202a", muted: "#56616c", line: "#d9d4c8", surface: "#ffffff", accent: "#0e4f5c",
      series: ["#0e4f5c", "#b4541a", "#5b4a9e", "#2e7d4f", "#a3271f", "#8a7a1c", "#3d6fb4", "#7a4a66"] };
    c.setOption({ ...(build(light) as EChartsOption), animation: false, backgroundColor: "#ffffff" }, true);
    const svg = c.renderToSVGString();
    c.dispose();
    if (kind === "svg") download(`${exportName}.svg`, svg, "image/svg+xml");
    else await svgToPng(svg, exportName ?? "grafico", 2);
  };

  return (
    <div>
      <div ref={el} role="img" aria-label={ariaLabel} style={{ height }} className="w-full" />
      {exportName && (
        <div className="mt-1 flex justify-end gap-3 text-xs text-muted">
          <span>Exportar gráfico:</span>
          <button type="button" className="underline hover:text-ink" onClick={() => exportAs("png")}>PNG</button>
          <button type="button" className="underline hover:text-ink" onClick={() => exportAs("svg")}>SVG</button>
        </div>
      )}
    </div>
  );
}
