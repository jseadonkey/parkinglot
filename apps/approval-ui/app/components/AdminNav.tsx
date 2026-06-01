import Link from "next/link";

const links = [
  { href: "/", label: "Approvals" },
  { href: "/templates", label: "Message templates" },
];

export function AdminNav({ active }: { active: "approvals" | "templates" }) {
  return (
    <header className="admin-header">
      <div className="admin-brand">
        <span className="admin-title">Parking admin</span>
        <span className="muted">Human gates for outreach and deal flow</span>
      </div>
      <nav className="admin-nav" aria-label="Admin sections">
        {links.map((link) => {
          const isActive =
            (active === "approvals" && link.href === "/") ||
            (active === "templates" && link.href === "/templates");
          return (
            <Link key={link.href} href={link.href} className={isActive ? "nav-link active" : "nav-link"}>
              {link.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
