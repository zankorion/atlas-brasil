import type { Metadata } from "next";
import { Suspense } from "react";
import View from "@/views/IndicatorDetailView";

export const metadata: Metadata = { title: "Indicador" };

export default function Page() {
  return (
    <Suspense fallback={<p className="p-8 text-center text-sm text-muted">Carregando…</p>}>
      <View />
    </Suspense>
  );
}
