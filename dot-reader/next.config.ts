import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  // The team's pitch deck (copied from ../docs/pitch.html by scripts/copy-deck.mjs).
  rewrites: async () => [{ source: '/deck', destination: '/deck.html' }],
  partialPrefetching: true,
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
