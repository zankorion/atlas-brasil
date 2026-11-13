import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Source_Serif_4 } from "next/font/google";
import "./globals.css";
import { Suspense } from "react";
import { Nav, NavBar } from "@/components/Nav";

const sans = IBM_Plex_Sans({ variable: "--font-plex-sans", subsets: ["latin"], weight: ["400", "500", "600"] });
const mono = IBM_Plex_Mono({ variable: "--font-plex-mono", subsets: ["latin"], weight: ["400", "500"] });
const serif = Source_Serif_4({ variable: "--font-source-serif", subsets: ["latin"], weight: ["400", "600"] });

export const metadata: Metadata = {
  title: { default: "Atlas Econômico e Social do Brasil", template: "%s · Atlas do Brasil" },
  description:
    "Plataforma pública de inteligência econômica e territorial: dados oficiais brasileiros desde o Plano Real, com fonte, método e período rastreáveis.",
};

// Aplica o tema salvo (ou o do sistema) antes da primeira pintura, evitando o flash.
const themeScript = `try{var t=localStorage.getItem('atlas.theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt-BR" className={`${sans.variable} ${mono.variable} ${serif.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <a href="#conteudo" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-ink">
          Ir para o conteúdo
        </a>
        <Suspense fallback={<NavBar path="" />}>
          <Nav />
        </Suspense>
        <main id="conteudo" className="flex-1">{children}</main>
        <footer className="border-t border-line px-4 py-5 text-sm text-muted">
          <div className="mx-auto flex max-w-7xl flex-wrap justify-between gap-x-8 gap-y-2">
            <p>Atlas Econômico e Social do Brasil — código aberto, dados públicos oficiais.</p>
            <p>Valores ausentes nunca são tratados como zero. Correlação não é causalidade.</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
