import { env as nodeEnv } from "node:process";

/** Docker/runtime API base URL — read from node:process so standalone builds do not inline empty at build time. */
export function readApiServerUrl(): string {
  const fromServer = nodeEnv["API_SERVER_URL"]?.trim();
  if (fromServer) return fromServer.replace(/\/$/, "");
  const fromPublic = nodeEnv["NEXT_PUBLIC_API_URL"]?.trim();
  if (fromPublic) return fromPublic.replace(/\/$/, "");
  return "http://127.0.0.1:8000";
}
