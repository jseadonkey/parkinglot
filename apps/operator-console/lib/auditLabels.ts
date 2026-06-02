/** Plain-language labels for audit log rows. */

export function auditActionLabel(action: string): string {
  const map: Record<string, string> = {
    approval_approved: "Approved a request",
    approval_rejected: "Rejected a request",
    approval_created: "Created approval request",
    outreach_template_updated: "Updated message template",
    outreach_attempt_logged: "Logged outreach attempt",
    outbound_message_approval_requested: "Requested outreach approval",
    slack_digest_posted: "Posted Slack digest",
    pipeline_run_completed: "Pipeline run finished",
    pipeline_run_failed: "Pipeline run failed",
    site_watchdog_alert: "Site watchdog alert",
  };
  return map[action] ?? action.replaceAll("_", " ");
}

export function auditEntityLabel(entityType: string, entityId: string | null): string {
  const type = entityType.replaceAll("_", " ");
  if (!entityId) return type;
  if (entityId.length > 36) return `${type} · ${entityId.slice(0, 8)}…`;
  return `${type} · ${entityId.slice(0, 8)}…`;
}
