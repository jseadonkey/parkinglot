import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  basePath: "/operator",
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
