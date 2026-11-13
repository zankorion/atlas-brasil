# Atlas do Brasil — frontend

Next.js 16 (App Router) + React 19 + TypeScript + Tailwind 4 + MapLibre GL + ECharts.

```bash
npm install
npm run dev   # http://localhost:3000 (a API deve estar em NEXT_PUBLIC_API_URL, padrão http://localhost:8000)
```

- `src/app` — rotas (cada página é um Server Component que envolve a view cliente em `<Suspense>`).
- `src/views` — telas (cliente): Explorar (mapa + ranking + perfil + comparação), laboratório, séries, fontes.
  `/territorios/{código}` abre o Explorar com o território selecionado; `/territorios` e `/comparador` redirecionam para `/atlas`.
- `src/components` — mapa coroplético, gráficos, seletores e primitivas de interface.
- `src/lib` — cliente da API, formatação pt-BR, paletas e exportação de mapas (SVG/PNG).

Esta versão do Next tem mudanças em relação a versões anteriores; consulte `node_modules/next/dist/docs/` antes de alterar convenções.
