"use client";

import { useEffect, useMemo, useState } from "react";

import { auditActionLabel, auditEntityLabel } from "../../lib/auditLabels";
import { bridgeUrl } from "../../lib/paths";

type AuditRow = {
  id: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  meta: Record<string, unknown> | null;
  created_at: string;
};

export default function AuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "approvals" | "pipeline" | "slack">("all");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const res = await fetch(bridgeUrl("audit?limit=300"), { cache: "no-store" });
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

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (filter === "all") return true;
      if (filter === "approvals") return r.action.includes("approval");
      if (filter === "pipeline") return r.action.includes("pipeline");
      if (filter === "slack") return r.action.includes("slack");
      return true;
    });
  }, [rows, filter]);

  return (
    <main>
      <h1>Audit log</h1>
      <p className="muted page-lead">
        History of approvals, pipeline events, template edits, and Slack notifications — newest first. Use this when
        you need to confirm who approved what and when.
      </p>

      <div className="panel toolbar">
        <div className="filter-chips" role="tablist" aria-label="Audit filter">
          {(
            [
              ["all", "All"],
              ["approvals", "Approvals"],
              ["pipeline", "Pipeline"],
              ["slack", "Slack"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={filter === key}
              className={filter === key ? "chip chip-active" : "chip"}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {err ? <div className="error">{err}</div> : null}

      <div className="panel panel-flush">
        <table className="data">
          <thead>
            <tr>
              <th>When</th>
              <th>What happened</th>
              <th>Who</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr key={r.id}>
                <td className="muted">{r.created_at?.slice(0, 19).replace("T", " ")}</td>
                <td>
                  <strong>{auditActionLabel(r.action)}</strong>
                  <div className="muted cell-sub">{auditEntityLabel(r.entity_type, r.entity_id)}</div>
                </td>
                <td>{r.actor}</td>
                <td style={{ maxWidth: "280px" }}>
                  {r.meta && Object.keys(r.meta).length > 0 ? (
                    <span className="muted">{JSON.stringify(r.meta).slice(0, 120)}</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && !err ? <p className="muted empty-state">No matching events.</p> : null}
      </div>
    </main>
  );
}
