"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getDashboard } from "@/lib/api";
import type { Dashboard } from "@/types/dashboard";

const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;

const RULE_LABELS: Record<string, string> = {
  no_recent_sales: "No recent sales",
  aged_stock: "Aged stock",
  low_sales_velocity: "Low sales velocity",
};

export default function Home() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboard<Dashboard>().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <main className="p-8 text-red-600">{error}</main>;
  if (!data) return <main className="p-8">Loading…</main>;

  const stats = [
    { label: "Products", value: data.total_products },
    { label: "Need attention", value: data.needs_attention_count },
    { label: "Not enough data", value: data.not_enough_data_count },
    { label: "Cost tied up (flagged)", value: inr(data.flagged_inventory_cost_tied_up) },
  ];

  return (
    <main className="mx-auto max-w-5xl p-8 space-y-8">
      <h1 className="text-2xl font-semibold">StockRescue</h1>

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-lg border p-4">
            <div className="text-sm text-gray-500">{s.label}</div>
            <div className="text-xl font-semibold">{s.value}</div>
          </div>
        ))}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-medium">Products needing attention</h2>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="p-3">Product</th>
                <th className="p-3">Stock</th>
                <th className="p-3">Cost tied up</th>
                <th className="p-3">Why flagged</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {data.products_needing_attention.map((p) => (
                <tr key={p.product_pk} className="border-t align-top">
                  <td className="p-3">
                    <div className="font-medium">{p.product_name}</div>
                    <div className="text-gray-500">{p.sku}</div>
                  </td>
                  <td className="p-3">{p.quantity_in_stock}</td>
                  <td className="p-3">{inr(p.inventory_cost_tied_up)}</td>
                  <td className="p-3">
                    {p.rules_triggered.map((r) => (
                      <span key={r} className="mr-1 inline-block rounded bg-amber-100 px-2 py-0.5 text-xs">
                        {RULE_LABELS[r] ?? r}
                      </span>
                    ))}
                  </td>
                  <td className="p-3 text-right">
                    <Link href={`/rescue/${p.product_pk}`} className="rounded bg-black px-3 py-1.5 text-white">
                      Rescue
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
