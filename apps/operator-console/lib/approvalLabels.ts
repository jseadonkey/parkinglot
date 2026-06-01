const CHANNEL_LABELS: Record<string, string> = {
  email: "Email",
  sms: "Text",
  phone: "Voice",
  certified_mail: "Mail",
};

export function approvalHeadline(type: string, payload: Record<string, unknown>): string {
  switch (type) {
    case "outbound_message": {
      const ch = String(payload.channel ?? "");
      const apn = String(payload.apn ?? "—");
      return `${CHANNEL_LABELS[ch] ?? ch} outreach — APN ${apn}`;
    }
    case "deal_memo_publish":
      return `Deal memo — ${String(payload.title ?? payload.parcel_id ?? "—")}`;
    case "contract_send":
      return `Contract send — parcel ${String(payload.parcel_id ?? "").slice(0, 8)}…`;
    default:
      return type.replaceAll("_", " ");
  }
}

export function approvalRecipient(payload: Record<string, unknown>): string | null {
  const email = payload.to_email;
  if (typeof email === "string" && email) return email;
  const phone = payload.to_phone;
  if (typeof phone === "string" && phone) return phone;
  const mail = payload.to_mailing_address;
  if (typeof mail === "string" && mail) return mail;
  const name = payload.to_name;
  if (typeof name === "string" && name) return name;
  return null;
}

export function approvalDetail(type: string, payload: Record<string, unknown>): string | null {
  if (type === "outbound_message") {
    const subject = payload.subject;
    if (typeof subject === "string" && subject) return `Subject: ${subject}`;
    return null;
  }
  if (type === "contract_send" && payload.s3_key) {
    return `Draft: ${String(payload.s3_key)}`;
  }
  return null;
}

export function approvalBodyPreview(type: string, payload: Record<string, unknown>): string | null {
  if (type === "outbound_message" && typeof payload.body === "string") {
    return payload.body;
  }
  return null;
}
