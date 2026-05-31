"use client";

type FieldLabelProps = {
  label: string;
  help: string;
};

/** Label with hover/focus tooltip for non-technical operators. */
export function FieldLabel({ label, help }: FieldLabelProps) {
  return (
    <span className="field-label muted">
      {label}
      <button type="button" className="help-tip" aria-label={`About ${label}`}>
        ?
        <span className="help-tip-popup" role="tooltip">
          {help}
        </span>
      </button>
    </span>
  );
}
