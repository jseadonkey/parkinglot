import type { NextConfig } from "next";

import { operatorRedirectRules } from "./lib/operatorPaths";

const nextConfig: NextConfig = {
  output: "standalone",
  eslint: { ignoreDuringBuilds: true },
  env: {
    NEXT_PUBLIC_BASE_PATH: "",
  },
  async redirects() {
    return operatorRedirectRules();
  },
};

export default nextConfig;
