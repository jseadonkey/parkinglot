import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
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
        </nav>
        {children}
      </body>
    </html>
  );
}
