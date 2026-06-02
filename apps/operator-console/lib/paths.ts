/** Must match next.config.ts basePath */
export const BASE_PATH = "/operator";

export function bridgeUrl(internalPath: string): string {
  const clean = internalPath.replace(/^\//, "");
  return `${BASE_PATH}/api/bridge/${clean}`;
}

export function platformShowcaseUrl(): string {
  return `${BASE_PATH}/api/platform-showcase`;
}
