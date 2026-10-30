"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, getDashboard, getHealth } from "@/lib/api";

type Flagged = {
  product_pk: number;
  sku: string;
  product_name: string;
  quantity_in_stock: number;
  inventory_cost_tied_up: number;
  rules_triggered: string[];
  stock_cover_days: number | null;
};

type Dashboard = {
  total_products: number;
  needs_attention_count: number;
  not_enough_data_count: number;
  total_inventory_cost_tied_up: number;
  flagged_inventory_cost_tied_up: number;
  rule_counts: Record<string, number>;
  rule_descriptions: Record<string, string>;
  metric_descriptions: Record<string, string>;
  products_needing_attention: Flagged[];
};

const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

const RULE_LABEL: Record<string, string> = {
  no_recent_sales: "No recent sales",
  aged_stock: "Aged stock",
  low_sales_velocity: "Low sales velocity",
};

function Stat({ label, value, note, delay }: { label: string; value: string; note: string; delay: number }) {
  return (
    <div className="card rise p-5" style={{ animationDelay: `${delay}ms` }}>
      <div className="text-xs uppercase tracking-widest text-[var(--muted)]">{label}</div>
      <div className="num mt-2 font-display text-4xl">{value}</div>
      <details className="mt-3 text-xs text-[var(--muted)]">
        <summary className="cursor-pointer select-none">How is this calculated?</summary>
        <p className="mt-2 leading-relaxed">{note}</p>
      </details>
    </div>
  );
}

export default function OverviewPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [qloo, setQloo] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboard<Dashboard>()
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load the dashboard."));
    getHealth()
      .then((h) => setQloo(h.qloo_key_configured))
      .catch(() => setQloo(null));
  }, []);

  return (
    <main className="mx-auto max-w-6xl px-5 pb-20 pt-12">
      <section className="rise">
        <p className="text-xs uppercase tracking-[0.25em] text-[var(--accent)]">Independent bookstores</p>
        <h1 className="mt-3 max-w-3xl font-display text-5xl leading-[1.05] tracking-tight md:text-6xl">
          Slow stock, <em className="text-[var(--accent)]">smarter</em> experiments.
        </h1>
        <p className="mt-4 max-w-xl text-[var(--muted)]">
          Find what is sitting still, see the options worth testing before you discount, and measure what actually works.
        </p>
        {qloo !== null && (
          <p className="mt-4 inline-flex items-center gap-2 rounded-full border border-[var(--line)] px-3 py-1 text-xs text-[var(--muted)]">
            <span className={`h-2 w-2 rounded-full ${qloo ? "bg-emerald-600" : "bg-amber-500"}`} />
            {qloo ? "Qloo connected" : "Qloo key not set: plans use store data only"}
          </p>
        )}
      </section>

      {error && (
        <div className="card mt-10 border-red-300 bg-red-50 p-5 text-sm">
          <div className="font-medium">Could not load the dashboard</div>
          <div className="mt-1 text-red-800">{error}</div>
        </div>
      )}

      {!data && !error && (
        <div className="mt-10 grid gap-4 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card h-32 animate-pulse" />
          ))}
        </div>
      )}

      {data && (
        <>
          <section className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Products" value={String(data.total_products)} note={data.metric_descriptions.total_products} delay={100} />
            <Stat label="Need attention" value={String(data.needs_attention_count)} note={data.metric_descriptions.needs_attention_count} delay={200} />
            <Stat label="Cost tied up" value={money.format(data.total_inventory_cost_tied_up)} note={data.metric_descriptions.total_inventory_cost_tied_up} delay={300} />
            <Stat label="Tied up in flagged stock" value={money.format(data.flagged_inventory_cost_tied_up)} note={data.metric_descriptions.flagged_inventory_cost_tied_up} delay={400} />
          </section>

          {data.not_enough_data_count > 0 && (
            <p className="mt-4 text-sm text-[var(--muted)]">
              {data.not_enough_data_count} products have no sales data. They are not judged as unpopular.
            </p>
          )}

          <section className="mt-10 grid gap-3 md:grid-cols-3">
            {Object.entries(data.rule_counts).map(([rule, n]) => (
              <div key={rule} className="rounded-xl border border-[var(--line)] p-4">
                <div className="flex items-baseline justify-between">
                  <span className="font-medium">{RULE_LABEL[rule] ?? rule}</span>
                  <span className="num font-display text-2xl">{n}</span>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-[var(--muted)]">{data.rule_descriptions[rule]}</p>
              </div>
            ))}
          </section>

          <section className="mt-12">
            <h2 className="font-display text-3xl tracking-tight">Start with these</h2>
            <p className="mt-1 text-sm text-[var(--muted)]">Ranked by cost tied up, highest first.</p>
            <div className="card mt-5 divide-y divide-[var(--line)] overflow-hidden">
              {data.products_needing_attention.map((p) => (
                <div key={p.product_pk} className="flex flex-wrap items-center justify-between gap-3 p-4">
                  <div className="min-w-0">
                    <div className="font-medium">{p.product_name}</div>
                    <div className="mt-1 flex flex-wrap gap-2 text-xs text-[var(--muted)]">
                      <span>{p.sku}</span>
                      <span>·</span>
                      <span>{p.quantity_in_stock} in stock</span>
                      {p.rules_triggered.map((r) => (
                        <span key={r} className="rounded-full bg-[var(--paper)] px-2 py-0.5">
                          {RULE_LABEL[r] ?? r}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-5">
                    <span className="num font-display text-xl">{money.format(p.inventory_cost_tied_up)}</span>
                    <Link
                      href={`/rescue/${p.product_pk}`}
                      className="rounded-full bg-[var(--ink)] px-4 py-2 text-sm text-[var(--paper)] transition hover:bg-[var(--accent)]"
                    >
                      Open Rescue Lab
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
