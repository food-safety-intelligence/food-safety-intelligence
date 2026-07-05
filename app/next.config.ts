import type { NextConfig } from "next";

// Local-only: serve the dev server under a sub-path so it works behind the
// SageMaker Studio jupyter-server-proxy. Set DEV_BASE_PATH=/…/proxy/absolute/<port>
// when running `next dev` for browser preview. Empty in prod → no effect on the
// static export / real deploy.
const devBasePath = process.env.DEV_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  // Static export — generates a fully pre-rendered site in `out/`.
  // Suitable for S3 + CloudFront hosting without a Node.js server.
  output: "export",

  // next/image optimisation requires a server; unoptimized keeps static export working.
  images: { unoptimized: true },

  // Trailing slashes ensure S3 resolves /chat/ → /chat/index.html correctly.
  trailingSlash: true,

  ...(devBasePath ? { basePath: devBasePath, assetPrefix: devBasePath } : {}),
};

export default nextConfig;
