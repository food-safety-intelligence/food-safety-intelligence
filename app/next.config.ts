import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export — generates a fully pre-rendered site in `out/`.
  // Suitable for S3 + CloudFront hosting without a Node.js server.
  output: "export",

  // next/image optimisation requires a server; unoptimized keeps static export working.
  images: { unoptimized: true },

  // Trailing slashes ensure S3 resolves /chat/ → /chat/index.html correctly.
  trailingSlash: true,
};

export default nextConfig;
