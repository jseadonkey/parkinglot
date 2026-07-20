"use client";

import { useEffect, useState } from "react";

import { bridgeUrl } from "../lib/paths";

type SiteImageMeta = {
  parcel_id: string;
  available: boolean;
  lat?: number | null;
  lon?: number | null;
  street_view_url?: string | null;
  satellite_map_url?: string | null;
};

type Props = {
  parcelId: string;
  /** Compact thumb for the scored list; larger hero on the detail page. */
  variant?: "thumb" | "hero";
  className?: string;
};

export function ParcelSitePhoto({ parcelId, variant = "thumb", className }: Props) {
  const [meta, setMeta] = useState<SiteImageMeta | null>(null);
  const [imgFailed, setImgFailed] = useState(false);

  const w = variant === "hero" ? 720 : 160;
  const h = variant === "hero" ? 420 : 120;
  const imgUrl = bridgeUrl(
    `parcels/${parcelId}/site-image?width=${w}&height=${h}&source=satellite&v=lotline2`,
  );

  useEffect(() => {
    if (variant !== "hero") return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(bridgeUrl(`parcels/${parcelId}/site-image-meta`), { cache: "no-store" });
        if (!res.ok) return;
        const data = (await res.json()) as SiteImageMeta;
        if (!cancelled) setMeta(data);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [parcelId, variant]);

  if (variant === "thumb") {
    return (
      <div className={className} style={{ width: 160, minWidth: 160 }}>
        {!imgFailed ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imgUrl}
            alt="Property aerial view"
            width={160}
            height={120}
            loading="lazy"
            onError={() => setImgFailed(true)}
            style={{
              display: "block",
              width: 160,
              height: 120,
              objectFit: "cover",
              borderRadius: 6,
              border: "1px solid var(--border)",
              background: "#0a0e14",
            }}
          />
        ) : (
          <div
            className="muted"
            style={{
              width: 160,
              height: 120,
              display: "grid",
              placeItems: "center",
              borderRadius: 6,
              border: "1px dashed var(--border)",
              fontSize: "0.75rem",
            }}
          >
            No photo
          </div>
        )}
      </div>
    );
  }

  if (meta && !meta.available) {
    return <p className="muted">No map location on file for this parcel.</p>;
  }

  return (
    <div className={className || "panel"} style={{ padding: "0.85rem 1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "baseline" }}>
        <h2 style={{ margin: 0, fontSize: "1rem" }}>Property view</h2>
        <span className="muted" style={{ fontSize: "0.8rem" }}>
          Aerial with lot outline · Street View link below
        </span>
      </div>
      {!imgFailed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={imgUrl}
          alt="Property view"
          width={720}
          height={420}
          onError={() => setImgFailed(true)}
          style={{
            display: "block",
            width: "100%",
            maxWidth: 720,
            height: "auto",
            marginTop: "0.75rem",
            borderRadius: 8,
            border: "1px solid var(--border)",
            background: "#0a0e14",
          }}
        />
      ) : (
        <p className="muted" style={{ marginTop: "0.75rem" }}>
          Photo unavailable right now.
        </p>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.85rem", marginTop: "0.75rem" }}>
        {meta?.street_view_url ? (
          <a href={meta.street_view_url} target="_blank" rel="noreferrer">
            Open Street View →
          </a>
        ) : null}
        {meta?.satellite_map_url ? (
          <a href={meta.satellite_map_url} target="_blank" rel="noreferrer">
            Open satellite map →
          </a>
        ) : null}
      </div>
    </div>
  );
}
