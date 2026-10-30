"use client";

import { useEffect, useState } from "react";
import { getOutcome } from "@/lib/api";
import type { Experiment } from "@/types/experiment";
import type { OutcomeOut } from "@/types/outcome";

const HIDDEN = new Set(["limitations", "accounting_basis"]);

function fmt(key: string, v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") {
    const o = v as { available?: boolean };
    if (o.available === false) return "Not provided";
    return JSON.stringify(v);
  }
  if (typeof v === "number") {
    if (/(revenue|cost|profit)/.test(key) && !key.includes("pct")) return `₹${v.toLocaleString("en-IN")}`;
    if (key.includes("pct")) return `${v}%`;
  }
  return String(v);
}

export default function OutcomeView({ e }: { e: Experiment }) {
  const [o, setO] = useState<OutcomeOut | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getOutcome(e.id).then(setO).catch((x) => setErr(x.message));
  }, [e.id]);

  if (err) return <p className="text-sm text-red-600">{err}</p>;
  if (!o) return <p className="text-sm text-gray-500">Loading outcome…</p>;

  return (
    <div className="space-y-3 rounded border bg-gray-50 p-4">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-medium">Outcome</h4>
        <span
          className={`rounded px-2 py-0.5 text-xs ${
            o.is_simulated ? "bg-amber-100 text-amber-800" : "bg-green-100 text-green-800"
          }`}
        >
          {o.is_simulated ? "Simulated data" : "Observed"}
        </span>
      </div>
      <dl>
        {Object.entries(o.calculated).filter(([k]) => !HIDDEN.has(k)).map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 border-b py-1 text-sm">
            <dt className="text-gray-600">{k.replace(/_/g, " ")}</dt>
            <dd className="text-right">{fmt(k, v)}</dd>
          </div>
        ))}
      </dl>
      {o.limitations.length > 0 && (
        <ul className="list-disc pl-5 text-xs text-gray-600">
          {o.limitations.map((l, i) => (
            <li key={i}>{String(l)}</li>
          ))}
        </ul>
      )}
      {o.notes && <p className="text-sm text-gray-700">Notes: {o.notes}</p>}
    </div>
  );
}
