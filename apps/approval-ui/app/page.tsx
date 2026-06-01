"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminNav } from "./components/AdminNav";
import { apiBase } from "./lib/api";

type Approval = {
  id: string;
  type: string;
  status: string;
  payload: Record<string, unknown>;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
};

export default function Home() {
  const [items, setItems] = useState<Approval[]>([]);
  const [actor, setActor] = useState("reviewer@example.com");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const res = await fetch(`${apiBase}/approvals?status=pending`, { cache: "no-store" });
    if (!res.ok) {
      setError(`Failed to load approvals (${res.status})`);
      return;
    }
    const data = (await res.json()) as Approval[];
    setItems(data);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(id: string, action: "approve" | "reject") {
    setError(null);
    const res = await fetch(`${apiBase}/approvals/${id}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved_by: actor, note: null }),
    });
    if (!res.ok) {
      setError(`${action} failed (${res.status})`);
      return;
    }
    await load();
  }

  return (
    <>
      <AdminNav active="approvals" />
      <main>
        <h1>Pending approvals</h1>
        <p className="muted">
          Approve deal memos and contract drafts here. Edit mail and call copy under{" "}
          <a href="/templates">Message templates</a>. Outbound sends remain disabled in the API until Lob and counsel
          sign-off.
        </p>

        <div className="panel" style={{ marginTop: "1.5rem" }}>
          <label className="muted" htmlFor="actor">
            Approver identity
          </label>
          <div style={{ marginTop: "0.35rem" }}>
            <input id="actor" value={actor} onChange={(e) => setActor(e.target.value)} placeholder="name@company.com" />
          </div>
        </div>

        {error ? <div className="error">{error}</div> : null}

        <div className="panel">
          {items.length === 0 ? (
            <p className="muted">No pending items. Ingest sample parcels and run a pipeline from the API.</p>
          ) : (
            items.map((a) => (
              <div key={a.id} className="row">
                <div>
                  <div>
                    <strong>{a.type}</strong>
                    <span className="muted" style={{ marginLeft: "0.5rem" }}>
                      {a.id.slice(0, 8)}…
                    </span>
                  </div>
                  <div className="muted" style={{ marginTop: "0.25rem" }}>
                    {JSON.stringify(a.payload)}
                  </div>
                </div>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button className="primary" type="button" onClick={() => void decide(a.id, "approve")}>
                    Approve
                  </button>
                  <button className="danger" type="button" onClick={() => void decide(a.id, "reject")}>
                    Reject
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </main>
    </>
  );
}
