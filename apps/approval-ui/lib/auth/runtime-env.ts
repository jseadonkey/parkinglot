import { env as nodeEnv } from "node:process";

/**
 * Read auth env from the Node runtime (Docker-injected at container start).
 * Using `import { env } from "node:process"` avoids Next.js inlining `process.env.*`
 * as empty at build time for standalone output.
 */
export function readAuthEnvForLogin() {
  return {
    authSecret: nodeEnv["AUTH_SECRET"]?.trim(),
    adminEmail: (nodeEnv["AUTH_ADMIN_EMAIL"] ?? "").trim().toLowerCase(),
    adminPass: nodeEnv["AUTH_ADMIN_PASSWORD"] ?? "",
    viewerUser: (nodeEnv["AUTH_VIEWER_USERNAME"] ?? "").trim().toLowerCase(),
    viewerPass: nodeEnv["AUTH_VIEWER_PASSWORD"] ?? "",
    adminEmailDisplay: (nodeEnv["AUTH_ADMIN_EMAIL"] ?? "").trim(),
    viewerUserDisplay: (nodeEnv["AUTH_VIEWER_USERNAME"] ?? "").trim(),
    nodeEnv: nodeEnv["NODE_ENV"],
  };
}

export function readAuthSecret(): string | undefined {
  return nodeEnv["AUTH_SECRET"]?.trim();
}
