"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import PageShell from "@/components/PageShell";
import { getDashboard } from "@/lib/api";

type Flagged = {
  product_pk: number;
  sku: string;
  product_name: string;
  category?: string;
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
  thresholds: Record<string, number>;
  products_needing_attention: Flagged[];
};

const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;

const RULES: Record<string, { label: string; cls: string }> = {
  no_recent_sales: { label: "No recent sales", cls: "bg-rose-400/10 text-rose-300 ring-rose-400/25" },
  aged_stock: { label: "Aged stock", cls: "bg-amber-400/10 text-amber-300 ring-amber-400/25" },
  low_sales_velocity: { label: "Slow seller", cls: "bg-sky-400/10 text-sky-300 ring-sky-400/25" },
};
const FALLBACK = { label: "Flagged", cls: "bg-white/5 text-neutral-300 ring-white/10" };

const STEPS = [
  { n: "01", title: "Upload your stock", text: "Drop in a CSV of inventory and recent sales." },
  { n: "02", title: "Pick what to rescue", text: "Get ranked options, each with the evidence behind it." },
  { n: "03", title: "Test before you discount", text: "Run one small experiment, then record what happened." },
];

function reasons(p: Flagged, t: Record<string, number>) {
  const out: string[] = [];
  if (p.rules_triggered.includes("no_recent_sales"))
    out.push(`No sales in the last ${t.sales_window_days ?? 30} days`);
  if (p.rules_triggered.includes("aged_stock"))
    out.push(`On the shelf for ${t.aged_stock_days ?? 90}+ days`);
  if (p.rules_triggered.includes("low_sales_velocity") && p.stock_cover_days)
    out.push(`At this pace, stock lasts about ${Math.round(p.stock_cover_days)} days`);
  return out.join(". ");
}

function CountUp({ value, prefix = "" }: { value: number; prefix?: string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setN(value);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min((t - t0) / 1400, 1);
      setN(Math.round(value * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <span className="num">{prefix}{n.toLocaleString("en-IN")}</span>;
}

function Ring({ pct }: { pct: number }) {
  const [on, setOn] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setOn(true), 200);
    return () => clearTimeout(t);
  }, []);
  const r = 54;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative h-36 w-36 shrink-0">
      <svg viewBox="0 0 140 140" className="h-full w-full -rotate-90">
        <circle cx="70" cy="70" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="12" />
        <circle
          cx="70" cy="70" r={r} fill="none" stroke="#34d399" strokeWidth="12" strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={on ? c * (1 - pct / 100) : c}
          style={{ transition: "stroke-dashoffset 1.2s cubic-bezier(.22,1,.36,1)" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="font-display text-2xl">{pct}%</div>
        <div className="text-[10px] uppercase tracking-widest text-neutral-500">stuck</div>
      </div>
    </div>
  );
}

export default function Home() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    getDashboard<Dashboard>().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error && !data)
    return (
      <PageShell>
        <div className="panel p-6">
          <div className="font-medium text-red-300">Could not load your dashboard</div>
          <p className="mt-1 text-sm text-neutral-400">{error}</p>
        </div>
      </PageShell>
    );

  if (!data)
    return (
      <PageShell>
        <div className="space-y-5">
          <div className="h-6 w-48 animate-pulse rounded-full bg-white/5" />
          <div className="h-16 w-3/4 animate-pulse rounded-2xl bg-white/5" />
          <div className="h-6 w-1/2 animate-pulse rounded-lg bg-white/5" />
          <div className="grid gap-4 pt-8 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-52 animate-pulse rounded-3xl bg-white/5" />
            ))}
          </div>
        </div>
      </PageShell>
    );

  const products = [...data.products_needing_attention].sort(
    (a, b) => b.inventory_cost_tied_up - a.inventory_cost_tied_up
  );
  const counts: Record<string, number> = {};
  for (const p of products) for (const r of p.rules_triggered) counts[r] = (counts[r] ?? 0) + 1;

  const filtered = filter === "all" ? products : products.filter((p) => p.rules_triggered.includes(filter));
  const visible = showAll ? filtered : filtered.slice(0, 6);
  const maxCost = Math.max(...products.map((p) => p.inventory_cost_tied_up), 1);
  const top = products[0];

  const total = data.total_inventory_cost_tied_up;
  const stuck = data.flagged_inventory_cost_tied_up;
  const free = Math.max(total - stuck, 0);
  const pctStuck = total ? Math.round((stuck / total) * 100) : 0;

  const dots = Math.min(data.total_products, 60);
  const flaggedDots = data.total_products ? Math.round((data.needs_attention_count / data.total_products) * dots) : 0;

  const filters = [
    { key: "all", label: `All ${products.length}` },
    ...Object.keys(RULES).map((k) => ({ key: k, label: `${RULES[k].label} ${counts[k] ?? 0}` })),
  ];

  const delay = (ms: number) => ({ animationDelay: `${ms}ms` });

  return (
    <PageShell>
      <div className="pointer-events-none fixed inset-x-0 top-0 -z-10 h-[640px]">
        <div className="bg-grid absolute inset-0" />
        <div className="absolute -top-40 left-1/2 h-[420px] w-[760px] -translate-x-1/2 rounded-full bg-emerald-400/20 blur-[120px]" />
      </div>

      {/* HERO */}
      <section className="pt-4 md:pt-10">
        <div className="fade-up inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs text-neutral-300" style={delay(0)}>
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
          </span>
          Based on your latest inventory upload
        </div>

        <h1 className="fade-up font-display mt-6 max-w-4xl text-4xl leading-[1.08] tracking-tight md:text-6xl" style={delay(100)}>
          <span className="text-shine"><CountUp value={stuck} prefix="₹" /></span>
          <br />
          is stuck in stock that isn&apos;t selling.
        </h1>

        <p className="fade-up mt-6 max-w-2xl text-lg leading-relaxed text-neutral-400" style={delay(220)}>
          That&apos;s cash you&apos;ve already spent. StockRescue shows which {data.needs_attention_count} products to
          move first and lets you test a plan on a small scale before you discount anything.
        </p>

        <div className="fade-up mt-9 flex flex-wrap items-center gap-3" style={delay(320)}>
          {top && (
            <Link
              href={`/rescue/${top.product_pk}`}
              className="group rounded-full bg-emerald-400 px-7 py-3.5 text-sm font-semibold text-black shadow-[0_0_40px_-8px_rgba(52,211,153,0.8)] transition hover:bg-emerald-300"
            >
              Rescue the biggest one <span className="inline-block transition group-hover:translate-x-1">→</span>
            </Link>
          )}
          <Link href="/upload" className="rounded-full border border-white/15 px-7 py-3.5 text-sm transition hover:bg-white/5">
            Upload new inventory
          </Link>
        </div>
      </section>

      {/* BENTO */}
      <section className="mt-16 grid gap-4 lg:grid-cols-3">
        <div className="panel fade-up p-6" style={delay(420)}>
          <div className="text-xs uppercase tracking-widest text-neutral-500">Where your money is</div>
          <div className="mt-5 flex items-center gap-5">
            <Ring pct={pctStuck} />
            <div className="space-y-3 text-sm">
              <div>
                <div className="flex items-center gap-2 text-neutral-400">
                  <span className="h-2 w-2 rounded-full bg-emerald-400" /> Stuck
                </div>
                <div className="num text-lg font-semibold">{inr(stuck)}</div>
              </div>
              <div>
                <div className="flex items-center gap-2 text-neutral-400">
                  <span className="h-2 w-2 rounded-full bg-white/20" /> Moving freely
                </div>
                <div className="num text-lg font-semibold">{inr(free)}</div>
              </div>
            </div>
          </div>
        </div>

        <div className="panel fade-up p-6" style={delay(500)}>
          <div className="text-xs uppercase tracking-widest text-neutral-500">Your catalog</div>
          <div className="mt-4 flex items-baseline gap-2">
            <span className="font-display text-4xl">{data.needs_attention_count}</span>
            <span className="text-neutral-400">of {data.total_products} need attention</span>
          </div>
          <div className="mt-5 flex flex-wrap gap-1.5">
            {Array.from({ length: dots }).map((_, i) => (
              <span
                key={i}
                className={`h-3 w-3 rounded-[4px] ${i < flaggedDots ? "bg-emerald-400" : "bg-white/10"}`}
              />
            ))}
          </div>
          {data.not_enough_data_count > 0 && (
            <p className="mt-4 text-xs text-neutral-500">
              {data.not_enough_data_count} products have too little sales history to judge.
            </p>
          )}
        </div>

        {top && (
          <div className="panel fade-up relative overflow-hidden p-6" style={delay(580)}>
            <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-emerald-400/20 blur-3xl" />
            <div className="relative">
              <div className="text-xs uppercase tracking-widest text-emerald-400">Biggest opportunity</div>
              <div className="mt-4 text-xl font-medium leading-snug">{top.product_name}</div>
              <div className="mt-1 text-sm text-neutral-500">{top.sku} · {top.quantity_in_stock} in stock</div>
              <div className="num mt-5 font-display text-3xl">{inr(top.inventory_cost_tied_up)}</div>
              <div className="text-xs text-neutral-500">tied up in this one product</div>
              <Link
                href={`/rescue/${top.product_pk}`}
                className="mt-5 inline-block rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-black transition hover:bg-emerald-300"
              >
                Get a plan →
              </Link>
            </div>
          </div>
        )}
      </section>

      <details className="mt-4 text-sm text-neutral-500">
        <summary className="cursor-pointer select-none hover:text-neutral-300">How these numbers are calculated</summary>
        <p className="mt-2 max-w-3xl leading-relaxed">
          Stock cost is quantity in stock multiplied by unit cost. A product is flagged when it had no sales in the
          last {data.thresholds.sales_window_days ?? 30} days, has been held for {data.thresholds.aged_stock_days ?? 90}+
          days, or would take more than {data.thresholds.low_sales_cover_days ?? 180} days to sell at its recent pace.
        </p>
      </details>

      {/* QUEUE */}
      <section className="mt-20">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="font-display text-2xl tracking-tight md:text-3xl">Your rescue queue</h2>
            <p className="mt-2 text-neutral-400">Ranked by how much cash each product has locked up.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {filters.map((f) => (
              <button
                key={f.key}
                type="button"
                aria-pressed={filter === f.key}
                onClick={() => { setFilter(f.key); setShowAll(false); }}
                className={`rounded-full border px-4 py-1.5 text-sm transition ${
                  filter === f.key
                    ? "border-emerald-400 bg-emerald-400 font-medium text-black"
                    : "border-white/15 text-neutral-300 hover:bg-white/5"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {products.length === 0 ? (
          <div className="panel mt-8 p-10 text-center">
            <div className="text-lg font-medium">No slow-moving stock found</div>
            <p className="mt-1 text-sm text-neutral-400">Upload fresh sales data to check again.</p>
            <Link href="/upload" className="mt-5 inline-block rounded-full bg-emerald-400 px-6 py-2.5 text-sm font-semibold text-black">
              Upload inventory
            </Link>
          </div>
        ) : (
          <ul className="mt-8 space-y-3">
            {visible.map((p, i) => {
              const rank = products.indexOf(p) + 1;
              const isTop = rank === 1;
              return (
                <li
                  key={p.product_pk}
                  className={`group rounded-2xl border p-5 transition md:p-6 ${
                    isTop
                      ? "border-emerald-400/30 bg-emerald-400/[0.04]"
                      : "border-white/10 bg-white/[0.02] hover:border-white/20 hover:bg-white/[0.04]"
                  }`}
                >
                  <div className="flex flex-wrap items-start gap-5 md:flex-nowrap">
                    <div className="font-display w-10 shrink-0 text-xl text-neutral-600">
                      {String(rank).padStart(2, "0")}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-3">
                        <div className="text-lg font-medium">{p.product_name}</div>
                        {isTop && (
                          <span className="rounded-full bg-emerald-400 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-black">
                            Start here
                          </span>
                        )}
                      </div>
                      <div className="mt-1 text-sm text-neutral-500">
                        {p.sku}{p.category ? ` · ${p.category}` : ""} · {p.quantity_in_stock} in stock
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {p.rules_triggered.map((r) => {
                          const rule = RULES[r] ?? FALLBACK;
                          return (
                            <span key={r} className={`rounded-full px-2.5 py-1 text-xs ring-1 ring-inset ${rule.cls}`}>
                              {rule.label}
                            </span>
                          );
                        })}
                      </div>
                      <p className="mt-3 text-sm text-neutral-400">{reasons(p, data.thresholds)}</p>
                    </div>

                    <div className="flex w-full items-center justify-between gap-6 md:w-auto md:flex-col md:items-end">
                      <div className="text-right">
                        <div className="num text-2xl font-semibold">{inr(p.inventory_cost_tied_up)}</div>
                        <div className="text-xs text-neutral-500">tied up</div>
                      </div>
                      <Link
                        href={`/rescue/${p.product_pk}`}
                        className={`rounded-full px-5 py-2.5 text-sm font-semibold transition ${
                          isTop
                            ? "bg-emerald-400 text-black hover:bg-emerald-300"
                            : "border border-white/20 text-white hover:border-emerald-400 hover:bg-emerald-400 hover:text-black"
                        }`}
                      >
                        Get a plan →
                      </Link>
                    </div>
                  </div>

                  <div className="mt-5 h-1 overflow-hidden rounded-full bg-white/5">
                    <div
                      className="h-full rounded-full bg-emerald-400/70"
                      style={{ width: `${Math.max(5, Math.round((p.inventory_cost_tied_up / maxCost) * 100))}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {filtered.length > 6 && (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="mt-6 rounded-full border border-white/15 px-6 py-2.5 text-sm text-neutral-300 transition hover:bg-white/5"
          >
            {showAll ? "Show fewer" : `Show all ${filtered.length}`}
          </button>
        )}
      </section>

      {/* HOW IT WORKS */}
      <section className="mt-24">
        <h2 className="font-display text-2xl tracking-tight md:text-3xl">How it works</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {STEPS.map((s) => (
            <div key={s.n} className="panel p-6">
              <div className="font-display text-sm text-emerald-400">{s.n}</div>
              <div className="mt-3 text-lg font-medium">{s.title}</div>
              <p className="mt-2 text-sm leading-relaxed text-neutral-400">{s.text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CLOSING CTA */}
      {top && (
        <section className="panel relative mt-24 overflow-hidden p-8 text-center md:p-14">
          <div className="absolute left-1/2 top-0 h-48 w-[480px] -translate-x-1/2 rounded-full bg-emerald-400/20 blur-3xl" />
          <div className="relative">
            <h2 className="font-display mx-auto max-w-2xl text-2xl leading-tight tracking-tight md:text-4xl">
              Don&apos;t discount blindly. Start with {top.product_name}.
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-neutral-400">
              {inr(top.inventory_cost_tied_up)} is waiting on one shelf. Get ranked options in seconds and test the best
              one first.
            </p>
            <Link
              href={`/rescue/${top.product_pk}`}
              className="mt-8 inline-block rounded-full bg-emerald-400 px-8 py-3.5 text-sm font-semibold text-black shadow-[0_0_40px_-8px_rgba(52,211,153,0.8)] transition hover:bg-emerald-300"
            >
              Get the plan →
            </Link>
          </div>
        </section>
      )}
    </PageShell>
  );
}
