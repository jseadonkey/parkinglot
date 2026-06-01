/** Operator-console routes live under /operator (see apps/operator-console/next.config.ts). */

const OPERATOR_PREFIX = "/operator";

/** Paths that only exist on operator-console, not approval-ui root. */
export const OPERATOR_ONLY_PREFIXES = [
  "/outreach",
  "/deals",
  "/parcels",
  "/audit",
  "/owners",
  "/approvals",
] as const;

export function toOperatorPath(pathname: string): string {
  const path = pathname.startsWith("/") ? pathname : `/${pathname}`;
  if (path === OPERATOR_PREFIX || path.startsWith(`${OPERATOR_PREFIX}/`)) {
    return path;
  }
  for (const prefix of OPERATOR_ONLY_PREFIXES) {
    if (path === prefix || path.startsWith(`${prefix}/`)) {
      return `${OPERATOR_PREFIX}${path}`;
    }
  }
  return path;
}

export function operatorRedirectRules(): { source: string; destination: string; permanent: boolean }[] {
  return OPERATOR_ONLY_PREFIXES.flatMap((prefix) => [
    { source: prefix, destination: `${OPERATOR_PREFIX}${prefix}`, permanent: true },
    { source: `${prefix}/:path*`, destination: `${OPERATOR_PREFIX}${prefix}/:path*`, permanent: true },
  ]);
}
