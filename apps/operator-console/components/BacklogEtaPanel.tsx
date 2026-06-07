"use client";

import { useEffect, useState } from "react";
import { bridgeUrl } from "../lib/paths";

type BacklogEtaItem = {
  key: string;
  label: string;
  status: string;
  active_now: boolean;
  backlog_count: number;
  total_count: number;
  backlog_pct: number;
  unit: string;
  value: string;
  work_type: string;
  assumed_units_per_day: number | null;
  eta_days: number | null;
  eta_label: string;
  eta_confidence: string;
  recommendation: string;
  why: string;
};

type BacklogEta = {
  generated_at: string;
  summary: {
    active_parking_queue_depth: number;
    active_slack_queue_depth: number;
    workers_online: boolean;
    worker_detail: string | null;
    ops_auto_fix_enabled: boolean;
    data_checked_at: string | null;
    data_source: string;
    high_value_remaining: number;
    decision: string;
  };
  items: BacklogEtaItem[];
  degraded?: boolean;
};

function isBacklogEta(s: unknown): s is BacklogEta {
  return typeof s === "object" && s !== null && "summary" in s && Array.isArray((s as BacklogEta).items);
}

function valueLabel(value: string): string {
  if (value === "high") return "High value";
  if (value === "medium") return "Medium value";
  if (value === "selective") return "Selective value";
  return value;
}

function formatSnapshotTime(value: string | null): string {
  if (!value) return "No ops snapshot available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

async function fetchJson(path: string): Promise<unknown> {
  const res = await fetch(bridgeUrl(path), { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

export function BacklogEtaPanel() {
  const [backlogEta, setBacklogEta] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    fetchJson("internal/stats/backlog-eta")
      .then((data) => {
        if (!cancelled) setBacklogEta(data);
      })
      .catch((e) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const backlogView = isBacklogEta(backlogEta) ? backlogEta : null;

  if (err) return <div className="error">{err}</div>;
  if (!backlogView && loading) return <p className="muted">Loading backlog ETA...</p>;
  if (!backlogView) return null;

  return (
    <div className="panel">
      <div className="cols pipeline-stats">
        <div className="stat">
          <div className="muted">Parking queue now</div>
          <div className="n">{backlogView.summary.active_parking_queue_depth.toLocaleString()}</div>
        </div>
        <div className="stat">
          <div className="muted">High-value remaining</div>
          <div className="n">{backlogView.summary.high_value_remaining.toLocaleString()}</div>
        </div>
        <div className="stat">
          <div className="muted">Workers</div>
          <div className="n">{backlogView.summary.workers_online ? "Online" : "Offline"}</div>
        </div>
        <div className="stat">
          <div className="muted">Auto-fix</div>
          <div className="n">{backlogView.summary.ops_auto_fix_enabled ? "On" : "Off"}</div>
        </div>
      </div>
      <p className="muted" style={{ marginTop: "0.75rem" }}>
        {backlogView.summary.decision}
      </p>
      <p className="muted" style={{ marginTop: "0.35rem" }}>
        Data snapshot: {formatSnapshotTime(backlogView.summary.data_checked_at)} · Source:{" "}
        {backlogView.summary.data_source.replaceAll("_", " ")} · Page generated:{" "}
        {formatSnapshotTime(backlogView.generated_at)}
      </p>
      {backlogView.degraded ? (
        <div className="error" style={{ marginTop: "0.75rem" }}>
          Live backlog details are temporarily unavailable. This page will recover when the API bridge can reach the
          stats endpoint again.
        </div>
      ) : null}
      <table className="data" style={{ marginTop: "1rem" }}>
        <thead>
          <tr>
            <th>Work</th>
            <th>Value</th>
            <th>Remaining</th>
            <th>ETA</th>
            <th>Recommendation</th>
          </tr>
        </thead>
        <tbody>
          {backlogView.items.length === 0 ? (
            <tr>
              <td colSpan={5} className="muted">
                No backlog rows available right now.
              </td>
            </tr>
          ) : null}
          {backlogView.items.map((item) => (
            <tr key={item.key}>
              <td>
                <strong>{item.label}</strong>
                <div className="muted">{item.why}</div>
              </td>
              <td>
                <span className={item.value === "high" ? "badge badge-priority" : "badge"}>
                  {valueLabel(item.value)}
                </span>
              </td>
              <td>
                {item.backlog_count.toLocaleString()} / {item.total_count.toLocaleString()} {item.unit}
                <div className="muted">{item.backlog_pct}% remaining</div>
              </td>
              <td>
                {item.eta_label}
                <div className="muted">Confidence: {item.eta_confidence}</div>
                {item.assumed_units_per_day ? (
                  <div className="muted">Assumes ~{Math.round(item.assumed_units_per_day).toLocaleString()} / day</div>
                ) : null}
              </td>
              <td>{item.recommendation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
