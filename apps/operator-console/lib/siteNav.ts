/** Single source of truth for operator console navigation and page purpose copy. */

export type NavItem = {
  href: string;
  label: string;
  /** One line — shown under the title on every visit (memory aid). */
  purpose: string;
  /** Sidebar link text (can be shorter). */
  short?: string;
};

export type NavGroup = {
  label: string;
  items: NavItem[];
};

/** Daily workflow order — same every time you open the site. */
export const DAILY_ROUTINE: { step: number; label: string; href: string; hint: string }[] = [
  { step: 1, label: "Outreach pipeline", href: "/outreach", hint: "Filter Needs action first" },
  { step: 2, label: "Approvals", href: "/approvals", hint: "Memos, contracts, outbound messages" },
  { step: 3, label: "Open a parcel", href: "/outreach", hint: "Review brief → request approval" },
];

export const AGENT_LEGEND: { name: string; means: string }[] = [
  { name: "Cartographer", means: "Prescreen at ingest" },
  { name: "Atlas", means: "Entitlement / zoning fit" },
  { name: "Beacon", means: "Strategic / market fit" },
];

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Every visit",
    items: [
      {
        href: "/outreach",
        label: "Outreach pipeline",
        short: "Outreach",
        purpose: "Your daily queue of qualified deals. Start with the Needs action filter.",
      },
      {
        href: "/approvals",
        label: "Approvals",
        purpose: "Human gate — approve or reject memos, contracts, and outbound messages.",
      },
      {
        href: "/",
        label: "Overview",
        purpose: "Multi-state pilot scope (Baltimore + Washington), scoring totals, and data funnel.",
      },
    ],
  },
  {
    label: "Browse",
    items: [
      {
        href: "/deals",
        label: "Deal progress",
        short: "Deals",
        purpose: "Every parcel with a pipeline run — step-by-step progress bars.",
      },
      {
        href: "/parcels",
        label: "Parcels",
        purpose: "Scored inventory — filter by state or county (Maryland and Washington).",
      },
      {
        href: "/owners",
        label: "Portfolios",
        purpose: "Owners with multiple qualified parcels — expand to see all their lots.",
      },
    ],
  },
  {
    label: "Setup",
    items: [
      {
        href: "/templates",
        label: "Message templates",
        short: "Templates",
        purpose: "Default email, text, voice, and mail copy before outreach.",
      },
      { href: "/audit", label: "Audit log", short: "Audit", purpose: "Who approved what and when — history trail." },
    ],
  },
  {
    label: "Share",
    items: [
      {
        href: "/platform",
        label: "Platform showcase",
        short: "Platform",
        purpose: "Partner-facing story with live metrics and redacted sample outputs.",
      },
    ],
  },
];

const ALL_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

export function navItemForPath(pathname: string): NavItem | null {
  const path = pathname.replace(/\/$/, "") || "/";
  if (path === "/") return ALL_ITEMS.find((i) => i.href === "/") ?? null;
  const exact = ALL_ITEMS.find((i) => i.href !== "/" && (path === i.href || path.startsWith(`${i.href}/`)));
  return exact ?? null;
}

export function breadcrumbsForPath(pathname: string): { href: string; label: string }[] {
  const path = pathname.replace(/\/$/, "") || "/";
  const crumbs: { href: string; label: string }[] = [{ href: "/", label: "Home" }];

  if (path === "/") return crumbs;

  const parcelDetail = path.match(/^\/parcels\/([^/]+)$/);
  if (parcelDetail) {
    crumbs.push({ href: "/parcels", label: "Parcels" });
    crumbs.push({ href: path, label: "Parcel detail" });
    return crumbs;
  }

  const item = navItemForPath(path);
  if (item && item.href !== "/") {
    crumbs.push({ href: item.href, label: item.short ?? item.label });
  } else {
    crumbs.push({ href: path, label: "Page" });
  }
  return crumbs;
}

export function isNavActive(pathname: string, href: string): boolean {
  const path = pathname.replace(/\/$/, "") || "/";
  const target = href.replace(/\/$/, "") || "/";
  if (target === "/") return path === "/";
  return path === target || path.startsWith(`${target}/`);
}

export function skipAppChrome(pathname: string): boolean {
  return pathname.startsWith("/login");
}
