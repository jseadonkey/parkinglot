/** Same-origin proxy (server reaches API via API_SERVER_URL in Docker). */
export function apiUrl(path: string): string {
  const clean = path.replace(/^\//, "");
  return `/api/proxy/${clean}`;
}

/** @deprecated Prefer apiUrl — direct browser calls break when CORS or PUBLIC_API_URL is wrong. */
export const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
