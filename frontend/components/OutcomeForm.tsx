"use client";

import { useState } from "react";
import { recordOutcome } from "@/lib/api";
import type { Experiment } from "@/types/experiment";

type Key = "name" | "units" | "days" | "price" | "cost" | "extra" | "baseUnits" | "baseDays";

const FIELDS: { key: Key; label: string; hint?: string }[] = [
  { key: "name", label: "Product name" },
  { key: "units", label: "Units sold" },
  { key: "days", label: "Days the test ran" },
  { key: "price", label: "Actual selling price (₹)", hint: "Net of any discount" },
  { key: "cost", label: "Unit cost (₹)", hint: "Prefilled from price and margin" },
  { key: "extra", label: "Extra campaign costs (₹)" },
  { key: "baseUnits", label: "Baseline units (optional)", hint: "Units sold in the period before" },
  { key: "baseDays", label: "Baseline days (optional)" },
];

const inputCls = "mt-1 w-full rounded border px-2 py-1.5 text-sm";

function daysBetween(a: string | null, b: string | null) {
  if (!a || !b) return 14;
  const d = Math.round((new Date(b).getTime() - new Date(a).getTime()) / 86400000);
  return d > 0 ? d : 1;
}

export default function OutcomeForm({ e, onDone }: { e: Experiment; onDone: () => void }) {
  const price = Number(e.proposed_price) || 0;
  const margin = Number(e.calculated_margin_pct) || 0;
  const [f, setF] = useState<Record<Key, string>>({
    name: e.title.includes(": ") ? e.title.split(": ").slice(1).join(": ") : e.title,
    units: "",
    days: String(daysBetween(e.start_date, e.end_date)),
    price: String(price),
    cost: String(Math.round(price * (1 - margin / 100))),
    extra: String(e.estimated_cost ?? 0),
    baseUnits: "",
    baseDays: "",
  });
  const [notes, setNotes] = useState("");
  const [simulated, setSimulated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setErr(null);
    const units = Number(f.units);
    const days = Number(f.days);
    if (f.units === "" || !Number.isInteger(units) || units < 0) {
      setErr("Units sold must be a whole number, 0 or more.");
      return;
    }
    if (!Number.isInteger(days) || days < 1) {
      setErr("Days must be a whole number, at least 1.");
      return;
    }
    const hasBase = f.baseUnits !== "" || f.baseDays !== "";
    if (hasBase && (f.baseUnits === "" || f.baseDays === "")) {
      setErr("Fill both baseline fields, or leave both empty.");
      return;
    }
    setBusy(true);
    try {
      await recordOutcome(e.id, {
        is_simulated: simulated,
        items: [
          {
            product_id: f.name,
            units_sold: units,
            actual_selling_price: Number(f.price),
            unit_cost: Number(f.cost),
          },
        ],
        additional_costs: Number(f.extra),
        target_units_sold: units,
        actual_days: days,
        baseline_units: hasBase ? Number(f.baseUnits) : null,
        baseline_days: hasBase ? Number(f.baseDays) : null,
        notes: notes.trim() || null,
      });
      onDone();
    } catch (x) {
      setErr(x instanceof Error ? x.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded border bg-gray-50 p-4">
      <h4 className="text-sm font-medium">Record the result</h4>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {FIELDS.map((fd) => (
          <label key={fd.key} className="block text-sm">
            <span className="text-gray-700">{fd.label}</span>
            <input
              className={inputCls}
              value={f[fd.key]}
              onChange={(ev) => setF({ ...f, [fd.key]: ev.target.value })}
            />
            {fd.hint && <span className="block text-xs text-gray-500">{fd.hint}</span>}
          </label>
        ))}
      </div>
      <label className="block text-sm">
        <span className="text-gray-700">Notes (optional)</span>
        <textarea className={inputCls} rows={2} value={notes} onChange={(ev) => setNotes(ev.target.value)} />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={simulated} onChange={(ev) => setSimulated(ev.target.checked)} />
        This is simulated / demo data, not real sales
      </label>
      <button
        onClick={submit}
        disabled={busy}
        className="rounded bg-black px-3 py-1.5 text-sm text-white disabled:opacity-50"
      >
        {busy ? "Saving…" : "Save outcome"}
      </button>
      {err && <p className="text-sm text-red-600">{err}</p>}
    </div>
  );
}
export default function OutcomeForm({ e, onDone }: { e: Experiment; onDone: () => void }) {
  const price = Number(e.proposed_price) || 0;
  const margin = Number(e.calculated_margin_pct) || 0;
  const [f, setF] = useState<Record<Key, string>>({
    name: e.title.includes(": ") ? e.title.split(": ").slice(1).join(": ") : e.title,
    units: "",
    days: String(daysBetween(e.start_date, e.end_date)),
    price: String(price),
    cost: String(Math.round(price * (1 - margin / 100))),
    extra: String(e.estimated_cost ?? 0),
    baseUnits: "",
    baseDays: "",
  });
  const [notes, setNotes] = useState("");
  const [simulated, setSimulated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setErr(null);
    const units = Number(f.units);
    const days = Number(f.days);
    if (f.units === "" || !Number.isInteger(units) || units < 0) {
      setErr("Units sold must be a whole number, 0 or more.");
      return;
    }
    if (!Number.isInteger(days) || days < 1) {
      setErr("Days must be a whole number, at least 1.");
      return;
    }
    const hasBase = f.baseUnits !== "" || f.baseDays !== "";
    if (hasBase && (f.baseUnits === "" || f.baseDays === "")) {
      setErr("Fill both baseline fields, or leave both empty.");
      return;
    }
    setBusy(true);
    try {
      await recordOutcome(e.id, {
        is_simulated: simulated,
        items: [
          {
            product_id: f.name,
            units_sold: units,
            actual_selling_price: Number(f.price),
            unit_cost: Number(f.cost),
          },
        ],
        additional_costs: Number(f.extra),
        target_units_sold: units,
        actual_days: days,
        baseline_units: hasBase ? Number(f.baseUnits) : null,
        baseline_days: hasBase ? Number(f.baseDays) : null,
        notes: notes.trim() || null,
      });
      onDone();
    } catch (x) {
      setErr(x instanceof Error ? x.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded border bg-gray-50 p-4">
      <h4 className="text-sm font-medium">Record the result</h4>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {FIELDS.map((fd) => (
          <label key={fd.key} className="block text-sm">
            <span className="text-gray-700">{fd.label}</span>
            <input
              className={inputCls}
              value={f[fd.key]}
              onChange={(ev) => setF({ ...f, [fd.key]: ev.target.value })}
            />
            {fd.hint && <span className="block text-xs text-gray-500">{fd.hint}</span>}
          </label>
        ))}
      </div>
      <label className="block text-sm">
        <span className="text-gray-700">Notes (optional)</span>
        <textarea className={inputCls} rows={2} value={notes} onChange={(ev) => setNotes(ev.target.value)} />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={simulated} onChange={(ev) => setSimulated(ev.target.checked)} />
        This is simulated / demo data, not real sales
      </label>
      <button
        onClick={submit}
        disabled={busy}
        className="rounded bg-black px-3 py-1.5 text-sm text-white disabled:opacity-50"
      >
        {busy ? "Saving…" : "Save outcome"}
      </button>
      {err && <p className="text-sm text-red-600">{err}</p>}
    </div>
  );
}
