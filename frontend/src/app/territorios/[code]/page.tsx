import type { Metadata } from "next";
import { Suspense } from "react";
import View from "@/views/AtlasView";

export const metadata: Metadata = { title: "Explorar — território" };

export default function Page() {
  return (
    <Suspense fallback={<p className="p-8 text-center text-sm text-muted">Carregando…</p>}>
      <View />
    </Suspense>
  );
}
