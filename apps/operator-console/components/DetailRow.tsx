"use client";

import type { ReactNode } from "react";
import { FieldLabel } from "./FieldLabel";

type DetailRowProps = {
  label: string;
  help: string;
  value: ReactNode;
  hint?: string | null;
};

export function DetailRow({ label, help, value, hint }: DetailRowProps) {
  return (
    <div className="row">
      <FieldLabel label={label} help={help} />
      <div className="detail-value">
        <div>{value}</div>
        {hint ? <div className="field-hint">{hint}</div> : null}
      </div>
    </div>
  );
}
