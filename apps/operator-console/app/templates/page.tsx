"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { TEMPLATE_TABS } from "../../lib/templateChannels";
import { bridgeUrl } from "../../lib/paths";
import { canMutate, useAuth } from "../../lib/useAuth";

type TemplateSummary = {
  slug: string;
  name: string;
  channel: string;
  subject: string | null;
  body: string;
  updated_by: string | null;
  updated_at: string;
};

type Preview = {
  slug: string;
  subject: string | null;
  body: string;
};

export default function TemplatesPage() {
  const auth = useAuth();
  const allowEdit = canMutate(auth);

  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string>(TEMPLATE_TABS[0].slug);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [editor, setEditor] = useState("admin@example.com");
  const [placeholders, setPlaceholders] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const tabMeta = useMemo(
    () => TEMPLATE_TABS.find((t) => t.slug === selectedSlug) ?? TEMPLATE_TABS[0],
    [selectedSlug],
  );
  const selected = templates.find((t) => t.slug === selectedSlug) ?? null;

  const loadMeta = useCallback(async () => {
    const res = await fetch(bridgeUrl("outreach-templates/meta"), { cache: "no-store" });
    if (!res.ok) {
      return;
    }
    const data = (await res.json()) as { placeholders: string[] };
    setPlaceholders(data.placeholders);
  }, []);

  const loadTemplates = useCallback(async () => {
    setError(null);
    const res = await fetch(bridgeUrl("outreach-templates"), { cache: "no-store" });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = (await res.json()) as { detail?: string };
        if (j.detail) detail = j.detail;
      } catch {
        /* ignore */
      }
      setError(`Failed to load templates (${detail})`);
      return;
    }
    const data = (await res.json()) as TemplateSummary[];
    setTemplates(data);
    if (data.length > 0 && !data.some((t) => t.slug === selectedSlug)) {
      setSelectedSlug(data[0].slug);
    }
  }, [selectedSlug]);

  const loadSelected = useCallback(async (slug: string) => {
    setError(null);
    setSaved(null);
    setPreview(null);
    const res = await fetch(bridgeUrl(`outreach-templates/${slug}`), { cache: "no-store" });
    if (!res.ok) {
      setError(`Failed to load template (${res.status})`);
      return;
    }
    const data = (await res.json()) as TemplateSummary;
    setSubject(data.subject ?? "");
    setBody(data.body);
  }, []);

  useEffect(() => {
    void loadMeta();
    void loadTemplates();
  }, [loadMeta, loadTemplates]);

  useEffect(() => {
    if (selectedSlug) {
      void loadSelected(selectedSlug);
    }
  }, [selectedSlug, loadSelected]);

  async function save() {
    if (!selectedSlug || !allowEdit) {
      return;
    }
    setError(null);
    setSaved(null);
    const res = await fetch(bridgeUrl(`outreach-templates/${selectedSlug}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        body,
        subject: selected?.channel === "email" ? subject : null,
        updated_by: editor,
      }),
    });
    if (!res.ok) {
      const detail = await res.text();
      setError(`Save failed (${res.status}): ${detail}`);
      return;
    }
    setSaved("Saved.");
    await loadTemplates();
  }

  async function runPreview() {
    if (!selectedSlug) {
      return;
    }
    setError(null);
    const res = await fetch(bridgeUrl(`outreach-templates/${selectedSlug}/preview`), {
      method: "POST",
    });
    if (!res.ok) {
      const detail = await res.text();
      setError(`Preview failed (${res.status}): ${detail}`);
      return;
    }
    setPreview((await res.json()) as Preview);
  }

  return (
    <div className="page-content main-wide">
      <div className="template-tabs" role="tablist" aria-label="Template channels">
        {TEMPLATE_TABS.map((tab) => {
          const loaded = templates.some((t) => t.slug === tab.slug);
          return (
            <button
              key={tab.slug}
              type="button"
              role="tab"
              aria-selected={tab.slug === selectedSlug}
              className={tab.slug === selectedSlug ? "template-tab-pill active" : "template-tab-pill"}
              onClick={() => setSelectedSlug(tab.slug)}
              disabled={templates.length > 0 && !loaded}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {error ? <div className="error">{error}</div> : null}
      {saved ? <div className="success">{saved}</div> : null}

      <div className="panel template-editor-panel">
        <p className="muted" style={{ margin: "0 0 1rem" }}>
          {tabMeta.hint}
        </p>

        {allowEdit ? (
          <div className="toolbar-row" style={{ marginBottom: "1rem" }}>
            <label className="toolbar-field">
              <span className="muted">Saved as</span>
              <input
                value={editor}
                onChange={(e) => setEditor(e.target.value)}
                placeholder="name@company.com"
                autoComplete="username"
              />
            </label>
          </div>
        ) : (
          <p className="muted" style={{ marginBottom: "1rem" }}>
            Sign in as an admin to edit templates.
          </p>
        )}

        {selected ? (
          <>
            <div className="page-header" style={{ marginBottom: "0.5rem" }}>
              <div className="muted" style={{ fontSize: "0.85rem" }}>
                {selected.name}
                {selected.updated_by ? ` · last edited by ${selected.updated_by}` : ""}
              </div>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button type="button" onClick={() => void runPreview()}>
                  Preview sample
                </button>
                {allowEdit ? (
                  <button className="primary" type="button" onClick={() => void save()}>
                    Save
                  </button>
                ) : null}
              </div>
            </div>

            {selected.channel === "email" ? (
              <div style={{ marginBottom: "1rem" }}>
                <label className="toolbar-field" style={{ width: "100%" }}>
                  <span className="muted">Email subject</span>
                  <input
                    style={{ width: "100%" }}
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    readOnly={!allowEdit}
                  />
                </label>
              </div>
            ) : null}

            <label className="toolbar-field" style={{ width: "100%" }}>
              <span className="muted">
                {selected.channel === "phone"
                  ? "Voice script"
                  : selected.channel === "sms"
                    ? "Text message body"
                    : selected.channel === "email"
                      ? "Email body"
                      : "Letter body"}
              </span>
              <textarea
                className="template-body"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={selected.channel === "sms" ? 8 : 18}
                readOnly={!allowEdit}
              />
            </label>

            <div className="muted template-placeholders">
              Placeholders:{" "}
              {placeholders.map((p) => (
                <code key={p}>{`{{ ${p} }}`}</code>
              ))}
              · Use <code>{`{{ situs_address or mailing_address }}`}</code> for fallbacks.
            </div>
          </>
        ) : (
          <p className="muted">Loading template…</p>
        )}
      </div>

      {preview ? (
        <div className="panel preview-panel">
          <strong>Sample preview</strong>
          <p className="muted" style={{ margin: "0.35rem 0 0" }}>
            Filled with example parcel data — not a live send.
          </p>
          {preview.subject ? (
            <div style={{ marginTop: "0.75rem" }}>
              <span className="muted">Subject: </span>
              {preview.subject}
            </div>
          ) : null}
          <pre className="preview-body">{preview.body}</pre>
        </div>
      ) : null}
    </div>
  );
}
