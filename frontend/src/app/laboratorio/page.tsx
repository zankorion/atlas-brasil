import type { Metadata } from "next";
import { Suspense } from "react";
import View from "@/views/LabView";

export const metadata: Metadata = { title: "Laboratório Econômico" };

export default function Page() {
  return (
    <Suspense fallback={<p className="p-8 text-center text-sm text-muted">Carregando…</p>}>
      <View />
    </Suspense>
  );
}
