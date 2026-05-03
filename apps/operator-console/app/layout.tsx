import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { AuthToolbar } from "../components/AuthToolbar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Parking — operator console",
  description: "Browse parcels, deal workflow, approvals, and readiness metrics",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav className="nav">
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem 0.75rem", alignItems: "center", flex: "1 1 auto" }}>
            <Link href="/">Overview</Link>
            <span className="sep">|</span>
            <Link href="/parcels">Parcels</Link>
            <span className="sep">|</span>
            <Link href="/deals">Deal progress</Link>
            <span className="sep">|</span>
            <Link href="/approvals">Approvals</Link>
            <span className="sep">|</span>
            <Link href="/audit">Audit</Link>
            <span className="sep">|</span>
            <Link href="/owners">Portfolios</Link>
            <span className="sep">|</span>
            <Link href="/outreach">Outreach pipeline</Link>
          </div>
          <AuthToolbar />
        </nav>
        {children}
      </body>
    </html>
  );
}
