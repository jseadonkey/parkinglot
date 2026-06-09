/** Operator-friendly pipeline error text (hide raw AWS SDK noise). */

export function formatWorkflowError(raw: string | null | undefined): string | null {
  if (!raw?.trim()) return null;
  const msg = raw.trim();
  if (msg.includes("NoSuchBucket")) {
    return "Draft storage bucket was missing when this run failed. The bucket is provisioned now — rerun the pipeline for this parcel.";
  }
  if (msg.includes("PutObject") && msg.includes("bucket")) {
    return "Could not save draft files to object storage. Check STORAGE_BUCKET on the Droplet.";
  }
  if (msg.length > 160) {
    return `${msg.slice(0, 160)}…`;
  }
  return msg;
}
