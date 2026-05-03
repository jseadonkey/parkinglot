import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AuthToolbar } from "../components/AuthToolbar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Parking — approvals",
  description: "Human approval gate for memos and contract drafts",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header
          style={{
            display: "flex",
            justifyContent: "flex-end",
            alignItems: "center",
            padding: "0.65rem 1.25rem",
            borderBottom: "1px solid #2a3544",
          }}
        >
          <AuthToolbar />
        </header>
        {children}
      </body>
    </html>
  );
}
