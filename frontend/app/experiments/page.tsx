"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { experimentAction, listExperiments } from "@/lib/api";
import type { Experiment, ExperimentStatus } from "@/types/experiment";

const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;

const STATUS_CLS: Record<ExperimentStatus, string> = {
  proposed: "bg-gray-100 text-gray-800",
  approved: "bg-blue-100 text-blue-800",
  running: "bg-amber-100 text-amber-800",
  completed: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
  cancelled: "bg-red-100 text-red-800",
};

const isoDay = (offsetDays: number) =>
  new Date(Date.now() + offsetDays * 86400000).toISOString().slice(0, 10);

function ExperimentCard({ e, onChanged }: { e: Experiment; onChanged: () => void }) {
  const [name, setName] = useState("");
  const [start, setStart] = useState(isoDay(0));
  const [end, setEnd] = useState(isoDay(14));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run(action: "approve" | "reject" | "start" | "cancel", body?: Record<string, unknown>) {
    setBusy(true);
    setErr(null);
    try {
      await experimentAction(e.id, action, body);
      onChanged();
    } catch (x) {
      setErr(x instanceof Error ? x.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const btn = "rounded px-3 py-1.5 text-sm disabled:opacity-50";

  return (
    <article className="space-y-3 rounded-lg border p-5">
      <header className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase text-gray-500">
            #{e.id} · {e.strategy_type} · plan {e.plan_id ?? "n/a"}
          </div>
          <h3 className="font-semibold">{e.title}</h3>
        </div>
        <span className={`rounded px-2 py-0.5 text-xs ${STATUS_CLS[e.status]}`}>{e.status}</span>
      </header>

      <p className="text-sm text-gray-700">{e.proposed_action}</p>

      <dl className="grid grid-cols-3 gap-3 text-sm">
        <div><dt className="text-gray-500">Price</dt><dd>{inr(e.proposed_price)}</dd></div>
        <div><dt className="text-gray-500">Margin</dt><dd>{e.calculated_margin_pct}%</dd></div>
        <div><dt className="text-gray-500">Test cost</dt><dd>{inr(e.estimated_cost)}</dd></div>
      </dl>

      {e.approved_by && (
        <p className="text-xs text-gray-500">Approved by {e.approved_by}</p>
      )}
      {e.start_date && (
        <p className="text-xs text-gray-500">Runs {e.start_date} to {e.end_date}</p>
      )}

      {e.status === "proposed" && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={name}
            onChange={(ev) => setName(ev.target.value)}
            placeholder="Your name"
            className="rounded border px-2 py-1.5 text-sm"
          />
          <button
            disabled={busy || !name.trim()}
            onClick={() => run("approve", { approved_by: name.trim() })}
            className={`${btn} bg-black text-white`}
          >
            Approve
          </button>
          <button disabled={busy} onClick={() => run("reject")} className={`${btn} border`}>
            Reject
          </button>
        </div>
      )}

      {e.status === "approved" && (
        <div className="flex flex-wrap items-center gap-2">
          <input type="date" value={start} onChange={(ev) => setStart(ev.target.value)} className="rounded border px-2 py-1.5 text-sm" />
          <span className="text-sm text-gray-500">to</span>
          <input type="date" value={end} onChange={(ev) => setEnd(ev.target.value)} className="rounded border px-2 py-1.5 text-sm" />
          <button
            disabled={busy || !start || !end}
            onClick={() => run("start", { start_date: start, end_date: end })}
            className={`${btn} bg-black text-white`}
          >
            Start
          </button>
          <button disabled={busy} onClick={() => run("cancel")} className={`${btn} border`}>
            Cancel
          </button>
        </div>
      )}

      {e.status === "running" && (
        <div className="flex items-center gap-3">
          <button disabled={busy} onClick={() => run("cancel")} className={`${btn} border`}>
            Cancel
          </button>
          <span className="text-xs text-gray-500">Recording the outcome comes next.</span>
        </div>
      )}

      {err && <p className="text-sm text-red-600">{err}</p>}
    </article>
  );
}

export default function ExperimentsPage() {
  const [items, setItems] = useState<Experiment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listExperiments().then(setItems).catch((x) => setError(x.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <Link href="/" className="text-sm text-gray-500 underline">← Back to dashboard</Link>
      <h1 className="text-2xl font-semibold">Experiments</h1>
      {error && <p className="text-red-600">{error}</p>}
      {!items && !error && <p>Loading…</p>}
      {items && items.length === 0 && <p className="text-gray-600">No experiments yet.</p>}
      <div className="space-y-4">
        {items?.map((e) => <ExperimentCard key={e.id} e={e} onChanged={load} />)}
      </div>
    </main>
  );
}
