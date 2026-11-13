import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  // Seções fundidas no Explorar: os endereços antigos continuam funcionando (parâmetros são preservados).
  async redirects() {
    return [
      { source: "/territorios", destination: "/atlas", permanent: false },
      { source: "/comparador", destination: "/atlas", permanent: false },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
