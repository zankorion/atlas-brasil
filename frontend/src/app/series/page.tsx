import type { Metadata } from "next";
import { Suspense } from "react";
import View from "@/views/SeriesView";

export const metadata: Metadata = { title: "Séries Históricas" };

export default function Page() {
  return (
    <Suspense fallback={<p className="p-8 text-center text-sm text-muted">Carregando…</p>}>
      <View />
    </Suspense>
  );
}
