"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import PageShell from "@/components/PageShell";
import { getRescuePlan } from "@/lib/api";
import CreateExperimentButton from "@/components/CreateExperimentButton";
import type { EvidenceSource, RescuePlan, Strategy } from "@/types/rescue";

const SOURCE: Record<EvidenceSource, { label: string; cls: string }> = {
  qloo: { label: "Qloo", cls: "border-violet-400/40 text-violet-300" },
  retailer_data: { label: "Your data", cls: "border-sky-400/40 text-sky-300" },
  calculation: { label: "Calculated", cls: "border-emerald-400/40 text-emerald-300" },
  llm: { label: "AI", cls: "border-amber-400/40 text-amber-300" },
  assumption: { label: "Assumption", cls: "border-neutral-600 text-neutral-400" },
};

const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;

function Label({ children }: { children: React.ReactNode }) {
  return <h4 className="text-xs uppercase tracking-widest text-neutral-500">{children}</h4>;
}

function StrategyCard({ s, planId }: { s: Strategy; planId: number | null }) {
  const e = s.economics;
  const stats: [string, string][] = [
    ["Price", inr(e.selling_price)],
    ["Margin", `${e.margin_pct}%`],
    ["Discount", `${e.discount_pct}%`],
    ["Test cost", inr(e.estimated_experiment_cost)],
  ];

  return (
    <article className="border border-neutral-800 p-6 md:p-8">
      <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-widest text-neutral-500">
        <span className="text-emerald-400">Option {s.rank}</span>
        <span>·</span>
        <span>{s.type}</span>
        <span>·</span>
        <span>Effort: {s.operational_effort}</span>
      </div>
      <h3 className="font-display mt-3 text-xl tracking-tight md:text-2xl">{s.name}</h3>
      <p className="mt-2 max-w-2xl text-neutral-400">{s.summary}</p>

      <dl className="mt-6 grid grid-cols-2 gap-6 border-y border-neutral-800 py-5 md:grid-cols-4">
        {stats.map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs uppercase tracking-widest text-neutral-500">{k}</dt>
            <dd className="num mt-1 text-lg">{v}</dd>
          </div>
        ))}
      </dl>

      {s.llm_explanation && (
        <div className="mt-6 border-l-2 border-amber-400/60 pl-4">
          <div className="text-xs uppercase tracking-widest text-amber-300">AI explanation</div>
          <p className="mt-1 text-neutral-300">{s.llm_explanation}</p>
        </div>
      )}

      <div className="mt-6">
        <Label>Evidence</Label>
        <ul className="mt-3 space-y-2 text-sm">
          {s.evidence.map((ev, i) => (
            <li key={i} className="flex gap-3">
              <span
                className={`h-fit shrink-0 rounded-sm border px-2 py-0.5 text-xs ${SOURCE[ev.source].cls}`}
              >
                {SOURCE[ev.source].label}
              </span>
              <span className="text-neutral-300">{ev.note}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-6 grid gap-6 md:grid-cols-2">
        {s.assumptions.length > 0 && (
          <div>
            <Label>Assumptions</Label>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-neutral-400">
              {s.assumptions.map((a, i) => <li key={i}>{a}</li>)}
            </ul>
          </div>
        )}
        {s.risks.length > 0 && (
          <div>
            <Label>Risks</Label>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-neutral-400">
              {s.risks.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </div>
        )}
      </div>

      <div className="mt-6">
        <Label>How to test it</Label>
        <p className="mt-3 text-sm text-neutral-300">{s.test_plan}</p>
      </div>

      <p className="mt-6 text-xs text-neutral-500">{s.rank_reason.explanation}</p>
      <p className="mt-1 text-xs italic text-neutral-600">{s.outcome_disclaimer}</p>

      <div className="mt-6">
        <CreateExperimentButton planId={planId} rank={s.rank} />
      </div>
    </article>
  );
}

function RescueContent() {
  const { pk } = useParams<{ pk: string }>();
  const [plan, setPlan] = useState<RescuePlan | null>(null);
  const [planId, setPlanId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    getRescuePlan(Number(pk))
      .then((r) => { setPlan(r.plan); setPlanId(r.planId); })
      .catch((e) => setError(e.message));
  }, [pk]);

  const partial = plan ? Object.keys(plan.stages_failed).length > 0 : false;

  return (
    <PageShell>
      <Link href="/" className="text-sm text-neutral-400 hover:text-white">← Back to dashboard</Link>

      {error && <p className="mt-8 text-red-400">{error}</p>}
      {!plan && !error && <p className="mt-8 text-neutral-400">Building your rescue plan…</p>}

      {plan && (
        <div className="mt-8 space-y-8">
          <div>
            <h1 className="font-display text-3xl tracking-tight md:text-4xl">{plan.product_name}</h1>
            <p className="mt-3 text-neutral-400">
              Ranked ways to move this product. Pick one and run it as a small experiment.
            </p>
            {planId !== null && <p className="mt-1 text-xs text-neutral-600">Plan #{planId}</p>}
          </div>

          {plan.qloo_note && (
            <div className="border border-amber-400/30 p-4 text-sm text-amber-200">{plan.qloo_note}</div>
          )}

          {partial && (
            <div className="border border-red-400/30 p-4 text-sm">
              <div className="font-medium text-red-300">This plan is partial.</div>
              <div className="mt-1 text-neutral-400">{plan.limitations}</div>
            </div>
          )}

          <div className="space-y-6">
            {plan.strategies.map((s) => <StrategyCard key={s.rank} s={s} planId={planId} />)}
          </div>

          {plan.rejected.length > 0 && (
            <section>
              <h2 className="font-display text-xl tracking-tight">Options we ruled out</h2>
              <ul className="mt-4 divide-y divide-neutral-800 border-y border-neutral-800 text-sm">
                {plan.rejected.map((r, i) => (
                  <li key={i} className="py-4">
                    <div>{r.name}</div>
                    <div className="mt-1 text-neutral-500">{r.reasons.join(" ")}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {!partial && <p className="text-xs text-neutral-600">{plan.limitations}</p>}
        </div>
      )}
    </PageShell>
  );
}

export default function RescuePage() {
  return (
    <Suspense
      fallback={
        <PageShell>
          <p className="text-neutral-400">Loading…</p>
        </PageShell>
      }
    >
      <RescueContent />
    </Suspense>
  );
}
