import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the build self-contained: no image optimization service and no network fonts.
  images: { unoptimized: true },
};

export default nextConfig;
