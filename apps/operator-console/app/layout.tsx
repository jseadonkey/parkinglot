import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { AuthToolbar } from "../components/AuthToolbar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Parking — operator console",
  description: "Washington parking acquisition — browse parcels, track deals, approve outreach",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav className="nav">
          <div className="nav-inner">
            <div className="nav-brand">
              <span className="nav-title">WA parking acquisition</span>
              <span className="nav-sub muted">Operator console</span>
            </div>
            <div className="nav-links">
              <Link href="/">Overview</Link>
              <Link href="/outreach" className="nav-primary">
                Outreach
              </Link>
              <Link href="/approvals">Approvals</Link>
              <Link href="/deals">Deal progress</Link>
              <Link href="/parcels">Parcels</Link>
              <Link href="/templates">Templates</Link>
              <Link href="/owners">Portfolios</Link>
              <Link href="/audit">Audit</Link>
            </div>
          </div>
          <AuthToolbar />
        </nav>
        {children}
      </body>
    </html>
  );
}
