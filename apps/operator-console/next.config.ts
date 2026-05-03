import type { NextConfig } from "next";

const basePath = "/operator";

const nextConfig: NextConfig = {
  output: "standalone",
  basePath,
  eslint: { ignoreDuringBuilds: true },
  env: {
    NEXT_PUBLIC_BASE_PATH: basePath,
  },
};

export default nextConfig;
