"use client";

import { useEffect, useState } from "react";

type AuditRow = {
  id: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  meta: Record<string, unknown> | null;
  created_at: string;
};

const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function AuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const res = await fetch(`${apiBase}/audit?limit=300`, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as AuditRow[];
        if (!cancelled) setRows(data);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>Audit log</h1>
      <p className="muted">Recent decisions and pipeline events (newest first).</p>

      {err ? <div className="error">{err}</div> : null}

      <div className="panel" style={{ overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              <th>When</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Entity</th>
              <th>Meta</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="muted">{r.created_at?.slice(0, 19)}</td>
                <td>{r.actor}</td>
                <td>{r.action}</td>
                <td>
                  {r.entity_type}
                  {r.entity_id ? (
                    <span className="muted">
                      <br />
                      {r.entity_id}
                    </span>
                  ) : null}
                </td>
                <td style={{ maxWidth: "280px" }}>
                  <span className="muted">{r.meta ? JSON.stringify(r.meta).slice(0, 160) : "—"}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
