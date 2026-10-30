"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import PageShell from "@/components/PageShell";
import { getRetailerSettings, saveRetailerSettings } from "@/lib/api";
import type { RetailerSettings } from "@/types/settings";

type NumberField = { key: string; label: string; min?: number; max?: number; step?: number };
const constraintFields: NumberField[] = [
  { key: "min_margin_pct", label: "Minimum gross margin (%)", min: 0, max: 99.99, step: 0.01 },
  { key: "max_discount_pct", label: "Maximum discount (%)", min: 0, max: 100, step: 0.01 },
  { key: "max_campaign_budget", label: "Maximum campaign budget (₹)", min: 0, step: 0.01 },
];
const strategyFields: NumberField[] = [
  { key: "test_units", label: "Test units", min: 1, step: 1 },
  { key: "test_days", label: "Test duration (days)", min: 1, step: 1 },
  { key: "bundle_campaign_cost", label: "Bundle campaign cost (₹)", min: 0, step: 0.01 },
  { key: "reposition_campaign_cost", label: "Reposition campaign cost (₹)", min: 0, step: 0.01 },
  { key: "promotion_campaign_cost", label: "Promotion campaign cost (₹)", min: 0, step: 0.01 },
];

export default function SettingsPage() {
  const [settings, setSettings] = useState<RetailerSettings | null>(null);
  const [restricted, setRestricted] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getRetailerSettings().then((value) => {
      setSettings(value);
      setRestricted(value.constraints.restricted_product_ids.join(", "));
    }).catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load settings."))
      .finally(() => setLoading(false));
  }, []);

  function setConstraint(key: string, value: number) {
    setSettings((current) => current ? {
      ...current, constraints: { ...current.constraints, [key]: value },
    } : current);
  }

  function setStrategy(key: string, value: number) {
    setSettings((current) => current ? {
      ...current, strategy: { ...current.strategy, [key]: value },
    } : current);
  }

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const payload = {
        ...settings,
        constraints: {
          ...settings.constraints,
          restricted_product_ids: restricted.split(",").map((sku) => sku.trim()).filter(Boolean),
        },
      };
      const saved = await saveRetailerSettings(payload);
      setSettings(saved);
      setRestricted(saved.constraints.restricted_product_ids.join(", "));
      setMessage("Retailer settings saved. New plans and experiments will use this configuration.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save settings.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <PageShell><p className="text-sm text-neutral-400">Loading retailer settings…</p></PageShell>;
  if (!settings) return <PageShell><p className="text-sm text-red-300">{error ?? "Settings are unavailable."}</p><Link href="/access" className="mt-4 inline-block underline">Connect API access</Link></PageShell>;

  return (
    <PageShell>
      <div className="mx-auto max-w-3xl space-y-6">
        <Link href="/" className="text-sm text-neutral-500 underline">← Back to dashboard</Link>
        <div>
          <p className="text-xs uppercase tracking-widest text-emerald-400">Commercial configuration</p>
          <h1 className="mt-2 font-display text-3xl">Retailer settings</h1>
          <p className="mt-2 text-sm text-neutral-400">These saved INR settings are used by recommendation generation and experiment validation. Existing experiments keep their original settings snapshot.</p>
        </div>
        <form onSubmit={save} className="space-y-5">
          <section className="panel space-y-4 p-6">
            <h2 className="font-semibold">Hard commercial constraints</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {constraintFields.map((field) => (
                <label key={field.key} className="space-y-1 text-sm">
                  <span className="text-neutral-300">{field.label}</span>
                  <input type="number" required min={field.min} max={field.max} step={field.step ?? "any"}
                    value={settings.constraints[field.key as keyof RetailerSettings["constraints"]] as number}
                    onChange={(event) => setConstraint(field.key, Number(event.target.value))}
                    className="w-full rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-white" />
                </label>
              ))}
            </div>
            <label className="block space-y-1 text-sm">
              <span className="text-neutral-300">Restricted product SKUs (comma-separated)</span>
              <textarea value={restricted} onChange={(event) => setRestricted(event.target.value)} rows={2}
                className="w-full rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-white" placeholder="SKU-001, SKU-002" />
            </label>
          </section>
          <section className="panel space-y-4 p-6">
            <h2 className="font-semibold">Experiment defaults and campaign estimates</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {strategyFields.map((field) => (
                <label key={field.key} className="space-y-1 text-sm">
                  <span className="text-neutral-300">{field.label}</span>
                  <input type="number" required min={field.min} step={field.step ?? "any"}
                    value={settings.strategy[field.key as keyof RetailerSettings["strategy"]] as number}
                    onChange={(event) => setStrategy(field.key, Number(event.target.value))}
                    className="w-full rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-white" />
                </label>
              ))}
            </div>
          </section>
          {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
          {message && <p role="status" className="text-sm text-emerald-300">{message}</p>}
          <button disabled={saving} className="rounded-full bg-emerald-400 px-6 py-3 text-sm font-semibold text-black disabled:opacity-50">
            {saving ? "Saving…" : "Save retailer settings"}
          </button>
        </form>
      </div>
    </PageShell>
  );
}
