// Exportação de mapas em SVG/PNG com título, legenda, fonte e nota — independente do WebGL.
import { download } from "./format";

type Legend = { color: string; label: string }[];
export type MapExport = {
  geo: GeoJSON.FeatureCollection; colorOf: (code: string) => string; title: string; subtitle: string;
  legend: Legend; source: string; outline?: GeoJSON.FeatureCollection | null;
};

const W = 1200, MAP_H = 1130, PAD = 30, TOP = 96;
// Caixa do Brasil; projeção equirretangular com paralelo padrão em 15°S (adequada para mapa temático nacional).
const LON0 = -74.2, LON1 = -28.6, LAT0 = -33.9, LAT1 = 5.4;
const KX = Math.cos((15 * Math.PI) / 180);

function projector(bbox: [number, number, number, number]) {
  const [x0, y0, x1, y1] = bbox;
  const s = Math.min((W - 2 * PAD) / ((x1 - x0) * KX), (MAP_H - 2 * PAD) / (y1 - y0));
  const ox = (W - (x1 - x0) * KX * s) / 2, oy = TOP + (MAP_H - (y1 - y0) * s) / 2;
  return (lon: number, lat: number) => [ox + (lon - x0) * KX * s, oy + (y1 - lat) * s] as const;
}

function pathOf(g: GeoJSON.Geometry, proj: ReturnType<typeof projector>): string {
  const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
  let d = "";
  for (const poly of polys)
    for (const ring of poly) {
      d += ring.map((c, i) => {
        const [x, y] = proj(c[0], c[1]);
        return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
      }).join("") + "Z";
    }
  return d;
}

function bboxOf(fc: GeoJSON.FeatureCollection): [number, number, number, number] {
  let x0 = 180, y0 = 90, x1 = -180, y1 = -90;
  const visit = (c: unknown) => {
    if (typeof (c as number[])[0] === "number") {
      const [x, y] = c as number[];
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    } else (c as unknown[]).forEach(visit);
  };
  fc.features.forEach((f) => f.geometry && "coordinates" in f.geometry && visit(f.geometry.coordinates));
  return [x0, y0, x1, y1];
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function buildSvg(o: MapExport, partial = false): string {
  const proj = projector(partial ? bboxOf(o.geo) : [LON0, LAT0, LON1, LAT1]);
  const H = TOP + MAP_H + 90;
  const parts: string[] = [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" font-family="'IBM Plex Sans', Arial, sans-serif">`,
    `<rect width="${W}" height="${H}" fill="#ffffff"/>`,
    `<text x="${PAD}" y="44" font-size="26" font-weight="600" fill="#16202a">${esc(o.title)}</text>`,
    `<text x="${PAD}" y="74" font-size="17" fill="#56616c">${esc(o.subtitle)}</text>`,
    `<g stroke="#ffffff" stroke-width="0.25" stroke-linejoin="round">`,
  ];
  for (const f of o.geo.features) {
    if (!f.geometry) continue;
    const code = String((f.properties as { code: string }).code);
    parts.push(`<path d="${pathOf(f.geometry, proj)}" fill="${o.colorOf(code)}"/>`);
  }
  parts.push("</g>");
  if (o.outline && !partial) {
    parts.push(`<g fill="none" stroke="#16202a" stroke-width="0.7" stroke-opacity="0.55">`);
    for (const f of o.outline.features) if (f.geometry) parts.push(`<path d="${pathOf(f.geometry, proj)}"/>`);
    parts.push("</g>");
  }
  const ly = TOP + MAP_H - o.legend.length * 26 - 10;
  o.legend.forEach((l, i) => {
    parts.push(`<rect x="${PAD}" y="${ly + i * 26}" width="26" height="18" fill="${l.color}" stroke="#56616c" stroke-width="0.4"/>`);
    parts.push(`<text x="${PAD + 36}" y="${ly + i * 26 + 14}" font-size="15" fill="#16202a">${esc(l.label)}</text>`);
  });
  parts.push(`<text x="${PAD}" y="${H - 52}" font-size="13" fill="#56616c">${esc(o.source)}</text>`);
  parts.push(`<text x="${PAD}" y="${H - 30}" font-size="13" fill="#56616c">Atlas Econômico e Social do Brasil · malha IBGE generalizada · territórios sem dado em cinza (ausente ≠ zero)</text>`);
  parts.push("</svg>");
  return parts.join("");
}

export function exportSvg(o: MapExport, filename: string, partial = false) {
  download(filename + ".svg", buildSvg(o, partial), "image/svg+xml");
}

export async function svgToPng(svg: string, filename: string, scale = 2) {
  const img = new Image();
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  await new Promise<void>((res, rej) => {
    img.onload = () => res();
    img.onerror = () => rej(new Error("Falha ao renderizar a imagem."));
    img.src = url;
  });
  const c = document.createElement("canvas");
  c.width = img.width * scale;
  c.height = img.height * scale;
  const ctx = c.getContext("2d")!;
  ctx.drawImage(img, 0, 0, c.width, c.height);
  URL.revokeObjectURL(url);
  c.toBlob((b) => b && download(filename + ".png", b), "image/png");
}

export async function exportPng(o: MapExport, filename: string, partial = false) {
  await svgToPng(buildSvg(o, partial), filename, 1.5);
}
