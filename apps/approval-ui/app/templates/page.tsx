"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminNav } from "../components/AdminNav";
import { apiBase } from "../lib/api";

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
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [editor, setEditor] = useState("reviewer@example.com");
  const [placeholders, setPlaceholders] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const selected = templates.find((t) => t.slug === selectedSlug) ?? null;

  const loadMeta = useCallback(async () => {
    const res = await fetch(`${apiBase}/outreach-templates/meta`, { cache: "no-store" });
    if (!res.ok) {
      return;
    }
    const data = (await res.json()) as { placeholders: string[] };
    setPlaceholders(data.placeholders);
  }, []);

  const loadTemplates = useCallback(async () => {
    setError(null);
    const res = await fetch(`${apiBase}/outreach-templates`, { cache: "no-store" });
    if (!res.ok) {
      setError(`Failed to load templates (${res.status})`);
      return;
    }
    const data = (await res.json()) as TemplateSummary[];
    setTemplates(data);
    if (data.length > 0 && !selectedSlug) {
      setSelectedSlug(data[0].slug);
    }
  }, [selectedSlug]);

  const loadSelected = useCallback(async (slug: string) => {
    setError(null);
    setSaved(null);
    setPreview(null);
    const res = await fetch(`${apiBase}/outreach-templates/${slug}`, { cache: "no-store" });
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
    if (!selectedSlug) {
      return;
    }
    setError(null);
    setSaved(null);
    const res = await fetch(`${apiBase}/outreach-templates/${selectedSlug}`, {
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
    const res = await fetch(`${apiBase}/outreach-templates/${selectedSlug}/preview`, {
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
    <>
      <AdminNav active="templates" />
      <main>
        <h1>Message templates</h1>
        <p className="muted">
          Edit the letter, email, and phone script copy used for owner outreach. Nothing is sent from this screen —
          sending stays disabled until counsel approval and Lob integration.
        </p>

        <div className="panel" style={{ marginTop: "1.5rem" }}>
          <label className="muted" htmlFor="editor">
            Editor identity
          </label>
          <div style={{ marginTop: "0.35rem" }}>
            <input
              id="editor"
              value={editor}
              onChange={(e) => setEditor(e.target.value)}
              placeholder="name@company.com"
            />
          </div>
        </div>

        {error ? <div className="error">{error}</div> : null}
        {saved ? <div className="success">{saved}</div> : null}

        <div className="template-layout">
          <aside className="panel template-list">
            <div className="muted" style={{ marginBottom: "0.75rem" }}>
              Templates
            </div>
            {templates.map((t) => (
              <button
                key={t.slug}
                type="button"
                className={t.slug === selectedSlug ? "template-tab active" : "template-tab"}
                onClick={() => setSelectedSlug(t.slug)}
              >
                <strong>{t.name}</strong>
                <span className="muted">{t.channel}</span>
              </button>
            ))}
          </aside>

          <section className="panel template-editor">
            {selected ? (
              <>
                <div className="row" style={{ borderBottom: "none", paddingTop: 0 }}>
                  <div>
                    <strong>{selected.name}</strong>
                    <div className="muted" style={{ marginTop: "0.25rem" }}>
                      Channel: {selected.channel}
                      {selected.updated_by ? ` · last edited by ${selected.updated_by}` : ""}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button type="button" onClick={() => void runPreview()}>
                      Preview sample
                    </button>
                    <button className="primary" type="button" onClick={() => void save()}>
                      Save
                    </button>
                  </div>
                </div>

                {selected.channel === "email" ? (
                  <div style={{ marginTop: "1rem" }}>
                    <label className="muted" htmlFor="subject">
                      Email subject
                    </label>
                    <input
                      id="subject"
                      style={{ width: "100%", marginTop: "0.35rem" }}
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                    />
                  </div>
                ) : null}

                <div style={{ marginTop: "1rem" }}>
                  <label className="muted" htmlFor="body">
                    Body {selected.channel === "phone" ? "(call script)" : ""}
                  </label>
                  <textarea id="body" value={body} onChange={(e) => setBody(e.target.value)} rows={18} />
                </div>

                <div className="muted" style={{ marginTop: "1rem" }}>
                  Placeholders:{" "}
                  {placeholders.map((p) => (
                    <code key={p} style={{ marginRight: "0.5rem" }}>
                      {`{{ ${p} }}`}
                    </code>
                  ))}
                  · Use <code>{`{{ situs_address or mailing_address }}`}</code> for fallbacks.
                </div>
              </>
            ) : (
              <p className="muted">No templates loaded yet.</p>
            )}
          </section>
        </div>

        {preview ? (
          <div className="panel preview-panel">
            <strong>Sample preview</strong>
            <p className="muted">Filled with example parcel data — not a live send.</p>
            {preview.subject ? (
              <div style={{ marginTop: "0.75rem" }}>
                <span className="muted">Subject: </span>
                {preview.subject}
              </div>
            ) : null}
            <pre className="preview-body">{preview.body}</pre>
          </div>
        ) : null}
      </main>
    </>
  );
}
