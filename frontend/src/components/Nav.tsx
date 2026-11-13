"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const ITEMS = [
  { href: "/", label: "Início" },
  { href: "/atlas", label: "Explorar" },
  { href: "/indicadores", label: "Indicadores" },
  { href: "/laboratorio", label: "Laboratório Econômico" },
  { href: "/series", label: "Séries Históricas" },
  { href: "/fontes", label: "Fontes e Metodologia" },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<string | null>(null);
  useEffect(() => {
    const id = requestAnimationFrame(() => setTheme(document.documentElement.dataset.theme ?? "light"));
    return () => cancelAnimationFrame(id);
  }, []);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("atlas.theme", next);
    } catch {}
    setTheme(next);
    window.dispatchEvent(new Event("atlas:theme"));
  };
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={theme === "dark" ? "Ativar modo claro" : "Ativar modo escuro"}
      className="rounded border border-line px-2.5 py-1.5 text-sm text-muted hover:text-ink"
    >
      {theme === "dark" ? "Modo claro" : "Modo escuro"}
    </button>
  );
}

/** Em rotas dinâmicas o caminho só é conhecido na requisição: o layout envolve <Nav> em Suspense e usa <NavBar path=""> como fallback. */
export function Nav() {
  return <NavBar path={usePathname()} />;
}

export function NavBar({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  // perfis (/territorios/…) fazem parte do Explorar
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href) || (href === "/atlas" && path.startsWith("/territorios")));
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1600px] items-center gap-4 px-4 py-2.5">
        <Link href="/" className="shrink-0 font-serif text-lg font-semibold leading-tight tracking-tight">
          Atlas <span className="text-accent">do Brasil</span>
          <span className="block text-[11px] font-normal font-sans uppercase tracking-[0.14em] text-muted">Econômico e Social</span>
        </Link>
        <nav aria-label="Navegação principal" className="hidden flex-1 flex-wrap items-center gap-x-1 xl:flex">
          {ITEMS.map((i) => (
            <Link
              key={i.href}
              href={i.href}
              aria-current={active(i.href) ? "page" : undefined}
              className={`rounded px-2.5 py-1.5 text-sm ${active(i.href) ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-ink"}`}
            >
              {i.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          <button
            type="button"
            className="rounded border border-line px-2.5 py-1.5 text-sm xl:hidden"
            aria-expanded={open}
            aria-controls="menu-movel"
            onClick={() => setOpen(!open)}
          >
            Menu
          </button>
        </div>
      </div>
      {open && (
        <nav id="menu-movel" aria-label="Navegação principal" className="border-t border-line px-4 py-2 xl:hidden">
          {ITEMS.map((i) => (
            <Link
              key={i.href}
              href={i.href}
              onClick={() => setOpen(false)}
              aria-current={active(i.href) ? "page" : undefined}
              className={`block rounded px-2 py-2 text-sm ${active(i.href) ? "bg-accent-soft font-medium text-accent" : "text-ink"}`}
            >
              {i.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}
