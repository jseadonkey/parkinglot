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
  server_load_tier?: string;
  server_load_note?: string;
};

type ServerLoadJob = {
  name: string;
  schedule_utc: string;
  load_tier: string;
  status: string;
  note: string;
};

type ServerLoad = {
  pressure_level: string;
  assessed_at: string | null;
  parking_queue_depth: number;
  score_gaps: number;
  ident_score_gaps: number;
  ent_score_gaps: number;
  gross_entitlement_gaps?: number;
  primary_drivers: string[];
  signals: string[];
  scheduled_jobs: ServerLoadJob[];
  throttles: string[];
};

type BacklogEta = {
  generated_at: string;
  server_load?: ServerLoad | null;
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
    load_governor_pressure_level?: string | null;
    load_governor_decision?: string | null;
    pipeline_enqueue_multiplier?: number | null;
    wa_rollout_allowed?: boolean | null;
    ops_autofix_allowed?: boolean | null;
    score_gaps_total?: number | null;
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

function pressureLabel(level: string | null | undefined): string {
  if (!level) return "Unknown";
  return level.charAt(0).toUpperCase() + level.slice(1);
}

function loadTierClass(tier: string | undefined): string {
  if (tier === "high") return "badge badge-load-high";
  if (tier === "medium") return "badge badge-load-medium";
  return "badge badge-load-low";
}

function loadTierLabel(tier: string | undefined): string {
  if (tier === "high") return "High CPU/DB";
  if (tier === "medium") return "Moderate";
  return "Light";
}

function jobStatusLabel(status: string): string {
  if (status === "throttled") return "Throttled";
  if (status === "paused") return "Paused";
  return "Active";
}

function countLabel(value: number, degraded?: boolean): string {
  return degraded ? "Unknown" : value.toLocaleString();
}

function workStateLabel(item: BacklogEtaItem, degraded?: boolean): string {
  if (degraded) return "Unavailable";
  if (item.backlog_count > 0) return "Needs work";
  if (item.active_now) return "Running";
  return "Complete";
}

function workStateClass(item: BacklogEtaItem, degraded?: boolean): string {
  if (degraded) return "badge";
  if (item.backlog_count > 0) return item.value === "high" ? "badge badge-priority" : "badge badge-load-medium";
  if (item.active_now) return "badge badge-load-medium";
  return "badge badge-load-low";
}

function itemByKey(items: BacklogEtaItem[], key: string): BacklogEtaItem | null {
  return items.find((item) => item.key === key) ?? null;
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

  const governorLevel = backlogView.summary.load_governor_pressure_level;
  const serverLoad = backlogView.server_load;
  const actionableItems = backlogView.degraded
    ? backlogView.items
    : backlogView.items.filter((item) => item.backlog_count > 0 || item.active_now);
  const completedItems = backlogView.degraded
    ? []
    : backlogView.items.filter((item) => item.backlog_count <= 0 && !item.active_now);
  const grossEntitlementGaps = serverLoad?.gross_entitlement_gaps ?? 0;
  const inventoryItem = itemByKey(backlogView.items, "pipeline_funnel") ?? itemByKey(backlogView.items, "score_gaps");
  const ownerTargetsItem = itemByKey(backlogView.items, "owner_outreach_briefs");
  const gatheredParcels = inventoryItem?.total_count ?? 0;
  const atlasCovered = Math.max(0, gatheredParcels - grossEntitlementGaps);
  const queuedWork = (backlogView.summary.active_parking_queue_depth || 0) + (backlogView.summary.active_slack_queue_depth || 0);

  return (
    <div className="panel">
      <div className="cols pipeline-stats">
        <div className="stat">
          <div className="muted">Parking queue now</div>
          <div className="n">{countLabel(backlogView.summary.active_parking_queue_depth, backlogView.degraded)}</div>
        </div>
        <div className="stat">
          <div className="muted">High-value remaining</div>
          <div className="n">{countLabel(backlogView.summary.high_value_remaining, backlogView.degraded)}</div>
        </div>
        <div className="stat">
          <div className="muted">Workers</div>
          <div className="n">
            {backlogView.degraded ? "Unknown" : backlogView.summary.workers_online ? "Online" : "Offline"}
          </div>
        </div>
        <div className="stat">
          <div className="muted">Auto-fix</div>
          <div className="n">{backlogView.summary.ops_auto_fix_enabled ? "On" : "Off"}</div>
        </div>
        {governorLevel ? (
          <div className="stat">
            <div className="muted">Load governor</div>
            <div className="n">{pressureLabel(governorLevel)}</div>
          </div>
        ) : null}
        {serverLoad ? (
          <div className="stat">
            <div className="muted">Score gaps (latent load)</div>
            <div className="n">{countLabel(serverLoad.score_gaps, backlogView.degraded)}</div>
          </div>
        ) : null}
        {backlogView.summary.active_slack_queue_depth > 0 ? (
          <div className="stat">
            <div className="muted">Slack queue</div>
            <div className="n">{backlogView.summary.active_slack_queue_depth.toLocaleString()}</div>
          </div>
        ) : null}
      </div>
      {serverLoad ? (
        <div className="server-load-panel" style={{ marginTop: "1rem" }}>
          <h3 style={{ margin: "0 0 0.5rem", fontSize: "1rem" }}>What&apos;s using the server</h3>
          <p className="muted" style={{ marginTop: 0 }}>
            {backlogView.degraded
              ? "Live queue depth is unknown while the API bridge is degraded. The schedule below shows what should run when the API recovers."
              : `Live queue depth is ${serverLoad.parking_queue_depth.toLocaleString()}. Orange/red governor means scheduled work is throttled even when the queue looks empty — latent gaps below still drive Postgres load when Beat tasks run.`}
          </p>
          {serverLoad.primary_drivers.length > 0 ? (
            <ul className="server-load-drivers">
              {serverLoad.primary_drivers.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : null}
          {serverLoad.throttles.length > 0 ? (
            <p className="muted">
              <strong>Active throttles:</strong> {serverLoad.throttles.join(" ")}
            </p>
          ) : null}
          {serverLoad.signals.length > 0 ? (
            <details style={{ marginTop: "0.5rem" }}>
              <summary className="muted">Governor signals ({serverLoad.signals.length})</summary>
              <ul className="server-load-drivers">
                {serverLoad.signals.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          ) : null}
          {serverLoad.scheduled_jobs.length > 0 ? (
            <table className="data" style={{ marginTop: "0.75rem" }}>
              <thead>
                <tr>
                  <th>Scheduled automation</th>
                  <th>UTC schedule</th>
                  <th>Server load</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {serverLoad.scheduled_jobs.map((job) => (
                  <tr key={job.name}>
                    <td>
                      <strong>{job.name}</strong>
                      {job.note ? <div className="muted">{job.note}</div> : null}
                    </td>
                    <td className="mono">{job.schedule_utc}</td>
                    <td>
                      <span className={loadTierClass(job.load_tier)}>{loadTierLabel(job.load_tier)}</span>
                    </td>
                    <td>{jobStatusLabel(job.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      ) : null}
      <p className="muted" style={{ marginTop: "0.75rem" }}>
        {backlogView.summary.decision}
      </p>
      {backlogView.summary.load_governor_decision ? (
        <p className="muted" style={{ marginTop: "0.35rem" }}>
          Governor: {backlogView.summary.load_governor_decision}
          {backlogView.summary.pipeline_enqueue_multiplier != null
            ? ` · Pipeline enqueue at ${Math.round(backlogView.summary.pipeline_enqueue_multiplier * 100)}%`
            : ""}
          {backlogView.summary.wa_rollout_allowed === false ? " · WA county rollout paused" : ""}
        </p>
      ) : null}
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
      <h3 style={{ margin: "1rem 0 0.5rem", fontSize: "1rem" }}>Gathered inventory & current work</h3>
      <div className="cols pipeline-stats">
        <div className="stat">
          <div className="muted">Parcels gathered</div>
          <div className="n">{countLabel(gatheredParcels, backlogView.degraded)}</div>
          <div className="cell-sub muted">Rows loaded into the parcel inventory snapshot.</div>
        </div>
        <div className="stat">
          <div className="muted">Outreach target pool</div>
          <div className="n">{countLabel(ownerTargetsItem?.total_count ?? 0, backlogView.degraded)}</div>
          <div className="cell-sub muted">Top-score parcels being monitored for owner work.</div>
        </div>
        <div className="stat">
          <div className="muted">Atlas coverage</div>
          <div className="n">{countLabel(atlasCovered, backlogView.degraded)}</div>
          <div className="cell-sub muted">
            {grossEntitlementGaps > 0
              ? `${grossEntitlementGaps.toLocaleString()} broad rows remain informational.`
              : "No broad entitlement coverage gap in this snapshot."}
          </div>
        </div>
        <div className="stat">
          <div className="muted">Queued work now</div>
          <div className="n">{countLabel(queuedWork, backlogView.degraded)}</div>
          <div className="cell-sub muted">Parking + Slack queues currently waiting/running.</div>
        </div>
      </div>
      <h3 style={{ margin: "1rem 0 0.5rem", fontSize: "1rem" }}>Actionable backlog</h3>
      {actionableItems.length === 0 ? (
        <div className="panel-inset muted">
          No candidate backlog needs operator action in this snapshot. The rows that used to show 0% remaining are now
          listed under completed/monitored scopes below.
        </div>
      ) : (
        <table className="data" style={{ marginTop: "0.5rem" }}>
          <thead>
            <tr>
              <th>Work</th>
              <th>Priority</th>
              <th>Remaining</th>
              <th>Server load</th>
              <th>ETA</th>
              <th>Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {actionableItems.map((item) => (
              <tr key={item.key} className={item.backlog_count > 0 ? "row-attention" : undefined}>
                <td>
                  <strong>{item.label}</strong>
                  <div className="muted">{item.why}</div>
                </td>
                <td>
                  <span className={workStateClass(item, backlogView.degraded)}>{workStateLabel(item, backlogView.degraded)}</span>
                  <div className="muted cell-sub">{valueLabel(item.value)}</div>
                </td>
                <td>
                  {backlogView.degraded ? (
                    <>
                      Unavailable
                      <div className="muted">Live count unavailable</div>
                    </>
                  ) : (
                    <>
                      {item.backlog_count.toLocaleString()} / {item.total_count.toLocaleString()} {item.unit}
                      <div className="muted">{item.backlog_pct}% remaining</div>
                    </>
                  )}
                </td>
                <td>
                  <span className={loadTierClass(item.server_load_tier)}>{loadTierLabel(item.server_load_tier)}</span>
                  {item.server_load_note ? <div className="muted">{item.server_load_note}</div> : null}
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
      )}

      <h3 style={{ margin: "1rem 0 0.5rem", fontSize: "1rem" }}>Current / next automated work</h3>
      <table className="data" style={{ marginTop: "0.5rem" }}>
        <thead>
          <tr>
            <th>Work</th>
            <th>Status</th>
            <th>Schedule</th>
            <th>Server load</th>
            <th>What it means</th>
          </tr>
        </thead>
        <tbody>
          {grossEntitlementGaps > 0 ? (
            <tr>
              <td>
                <strong>Broad entitlement coverage</strong>
                <div className="muted">
                  {grossEntitlementGaps.toLocaleString()} parcels do not have Atlas entitlement coverage.
                </div>
              </td>
              <td>
                <span className="badge badge-load-low">Informational</span>
              </td>
              <td className="muted">Not queued citywide</td>
              <td>
                <span className="badge badge-load-low">Light</span>
              </td>
              <td>
                Not a candidate backlog. These rows are scored only after identification prescreen or another candidate
                trigger says they can affect surface-parking lead quality.
              </td>
            </tr>
          ) : null}
          {serverLoad?.scheduled_jobs.length ? (
            serverLoad.scheduled_jobs.map((job) => (
              <tr key={job.name}>
                <td>
                  <strong>{job.name}</strong>
                  {job.note ? <div className="muted">{job.note}</div> : null}
                </td>
                <td>{jobStatusLabel(job.status)}</td>
                <td className="mono">{job.schedule_utc}</td>
                <td>
                  <span className={loadTierClass(job.load_tier)}>{loadTierLabel(job.load_tier)}</span>
                </td>
                <td>
                  {job.status === "paused"
                    ? "Paused by governor or config; it should resume when pressure/config allows."
                    : job.status === "throttled"
                      ? "Still available, but capped so it does not dominate API/DB capacity."
                      : "Active automation; no manual action needed unless it starts failing."}
                </td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={5} className="muted">
                No scheduled automation rows available in this snapshot.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {completedItems.length > 0 ? (
        <details style={{ marginTop: "1rem" }}>
          <summary className="muted">Completed / monitored candidate scopes ({completedItems.length})</summary>
          <table className="data" style={{ marginTop: "0.5rem" }}>
            <thead>
              <tr>
                <th>Scope</th>
                <th>State</th>
                <th>Candidate population</th>
                <th>Monitoring note</th>
              </tr>
            </thead>
            <tbody>
              {completedItems.map((item) => (
                <tr key={item.key}>
                  <td>
                    <strong>{item.label}</strong>
                    <div className="muted">{item.why}</div>
                  </td>
                  <td>
                    <span className={workStateClass(item)}>{workStateLabel(item)}</span>
                    <div className="muted cell-sub">{valueLabel(item.value)}</div>
                  </td>
                  <td>
                    {item.total_count.toLocaleString()} {item.unit} monitored
                    <div className="muted">0 open in this snapshot</div>
                  </td>
                  <td>{item.recommendation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
    </div>
  );
}
