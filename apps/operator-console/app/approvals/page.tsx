"use client";

import { useCallback, useEffect, useState } from "react";
import { bridgeUrl } from "../../lib/paths";
import { canMutate, useAuth } from "../../lib/useAuth";

type Approval = {
  id: string;
  type: string;
  status: string;
  payload: Record<string, unknown>;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
};

export default function ApprovalsPage() {
  const auth = useAuth();
  const allowActions = canMutate(auth);
  const [filter, setFilter] = useState<"pending" | "all">("pending");
  const [items, setItems] = useState<Approval[]>([]);
  const [actor, setActor] = useState("operator@example.com");
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const q = filter === "pending" ? "?status=pending&limit=200" : "?limit=200";
      const res = await fetch(bridgeUrl(`approvals${q}`), { cache: "no-store" });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const j = (await res.json()) as { detail?: string };
          if (j.detail) detail = j.detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const data = (await res.json()) as Approval[];
      setItems(data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(id: string, action: "approve" | "reject") {
    setErr(null);
    const res = await fetch(bridgeUrl(`approvals/${id}/${action}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved_by: actor, note: null }),
    });
    if (!res.ok) {
      setErr(`${action} failed (${res.status})`);
      return;
    }
    await load();
  }

  return (
    <main>
      <h1>Approvals</h1>
      <p className="muted">Same approval queue as the standalone approval UI — human gate for memos and contracts.</p>

      <div className="panel" style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        <label className="muted">
          Show{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value as "pending" | "all")}>
            <option value="pending">Pending only</option>
            <option value="all">All recent</option>
          </select>
        </label>
        {allowActions ? (
          <label className="muted">
            Actor{" "}
            <input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="email" />
          </label>
        ) : auth.loading ? (
          <span className="muted">Checking permissions…</span>
        ) : (
          <span className="muted">View-only — approval actions hidden.</span>
        )}
        <button type="button" className="primary" onClick={() => void load()}>
          Refresh
        </button>
      </div>

      {err ? (
        <div className="error">
          {err}
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            You can also use the{" "}
            <a href="/" className="btn-link">
              standalone approvals page
            </a>{" "}
            at the site home, or click Refresh after a moment.
          </p>
        </div>
      ) : null}

      <div className="panel">
        {items.length === 0 ? (
          <p className="muted">No rows.</p>
        ) : (
          items.map((a) => (
            <div key={a.id} className="row">
              <div style={{ flex: 1, minWidth: "200px" }}>
                <strong>{a.type}</strong>{" "}
                <span className="muted">
                  {a.status} · {a.id.slice(0, 8)}…
                </span>
                <pre className="json" style={{ marginTop: "0.5rem", maxHeight: "120px" }}>
                  {JSON.stringify(a.payload, null, 2)}
                </pre>
              </div>
              {a.status === "pending" ? (
                allowActions ? (
                  <div style={{ display: "flex", gap: "0.35rem" }}>
                    <button type="button" className="primary" onClick={() => void decide(a.id, "approve")}>
                      Approve
                    </button>
                    <button type="button" onClick={() => void decide(a.id, "reject")}>
                      Reject
                    </button>
                  </div>
                ) : (
                  <span className="muted">—</span>
                )
              ) : (
                <span className="muted">{a.approved_by ?? "—"}</span>
              )}
            </div>
          ))
        )}
      </div>
    </main>
  );
}
