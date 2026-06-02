"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AuthToolbar } from "./AuthToolbar";
import {
  AGENT_LEGEND,
  DAILY_ROUTINE,
  NAV_GROUPS,
  breadcrumbsForPath,
  isNavActive,
  navItemForPath,
  skipAppChrome,
} from "../lib/siteNav";

function PageMeta({ pathname }: { pathname: string }) {
  if (pathname.match(/^\/parcels\/[^/]+$/) || pathname === "/platform") {
    return null;
  }
  const item = navItemForPath(pathname);
  if (!item) return null;
  const crumbs = breadcrumbsForPath(pathname);
  return (
    <header className="app-page-meta">
      <nav className="breadcrumbs" aria-label="Breadcrumb">
        {crumbs.map((c, i) => (
          <span key={c.href} className="breadcrumb-item">
            {i > 0 ? <span className="breadcrumb-sep">›</span> : null}
            {i === crumbs.length - 1 ? (
              <span aria-current="page">{c.label}</span>
            ) : (
              <Link href={c.href}>{c.label}</Link>
            )}
          </span>
        ))}
      </nav>
      <h1 className="app-page-title">{item.label}</h1>
      <p className="app-page-purpose muted">{item.purpose}</p>
    </header>
  );
}

function SidebarNav({ pathname }: { pathname: string }) {
  return (
    <nav className="sidebar-nav" aria-label="Operator console">
      {NAV_GROUPS.map((group) => (
        <div key={group.label} className="sidebar-group">
          <div className="sidebar-group-label">{group.label}</div>
          <ul className="sidebar-links">
            {group.items.map((item) => {
              const active = isNavActive(pathname, item.href);
              return (
                <li key={item.href}>
                  <Link href={item.href} className={active ? "sidebar-link active" : "sidebar-link"}>
                    {item.short ?? item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function DailyRoutine() {
  return (
    <div className="sidebar-memory panel-inset">
      <div className="sidebar-memory-title">Your usual path</div>
      <ol className="sidebar-routine">
        {DAILY_ROUTINE.map((r) => (
          <li key={r.step}>
            <Link href={r.href}>
              <span className="routine-n">{r.step}</span>
              {r.label}
            </Link>
            <span className="muted routine-hint">{r.hint}</span>
          </li>
        ))}
      </ol>
      <div className="sidebar-legend muted">
        {AGENT_LEGEND.map((a) => (
          <div key={a.name}>
            <strong>{a.name}</strong> = {a.means}
          </div>
        ))}
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";

  if (skipAppChrome(pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <Link href="/outreach" className="app-brand">
          <span className="app-brand-title">WA parking</span>
          <span className="app-brand-sub muted">Operator console</span>
        </Link>
        <AuthToolbar />
      </header>
      <div className="app-body">
        <aside className="app-sidebar">
          <SidebarNav pathname={pathname} />
          <DailyRoutine />
        </aside>
        <main className="app-main">
          <PageMeta pathname={pathname} />
          <div className="app-page-content">{children}</div>
        </main>
      </div>
    </div>
  );
}
