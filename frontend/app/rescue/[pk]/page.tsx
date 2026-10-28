"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { getRescuePlan } from "@/lib/api";
import CreateExperimentButton from "@/components/CreateExperimentButton";
import type { EvidenceSource, RescuePlan, Strategy } from "@/types/rescue";

const SOURCE_STYLE: Record<EvidenceSource, { label: string; cls: string }> = {
  qloo: { label: "Qloo", cls: "bg-purple-100 text-purple-800" },
  retailer_data: { label: "Your data", cls: "bg-blue-100 text-blue-800" },
  calculation: { label: "Calculated", cls: "bg-green-100 text-green-800" },
  llm: { label: "AI", cls: "bg-pink-100 text-pink-800" },
  assumption: { label: "Assumption", cls: "bg-gray-100 text-gray-700" },
};

const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;

function StrategyCard({ s, planId }: { s: Strategy; planId: number | null }) {
  const e = s.economics;
  return (
    <article className="space-y-4 rounded-lg border p-5">
      <header>
        <div className="text-xs uppercase tracking-wide text-gray-500">
          #{s.rank} · {s.type} · effort: {s.operational_effort}
        </div>
        <h3 className="text-lg font-semibold">{s.name}</h3>
        <p className="text-sm text-gray-700">{s.summary}</p>
      </header>

      <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
        <div><dt className="text-gray-500">Price</dt><dd>{inr(e.selling_price)}</dd></div>
        <div><dt className="text-gray-500">Margin</dt><dd>{e.margin_pct}%</dd></div>
        <div><dt className="text-gray-500">Discount</dt><dd>{e.discount_pct}%</dd></div>
        <div><dt className="text-gray-500">Test cost</dt><dd>{inr(e.estimated_experiment_cost)}</dd></div>
      </dl>

      {s.llm_explanation && (
        <div className="rounded border-l-4 border-pink-400 bg-pink-50 p-3 text-sm">
          <div className="mb-1 text-xs font-semibold uppercase text-pink-700">AI explanation</div>
          {s.llm_explanation}
        </div>
      )}

      <div>
        <h4 className="mb-1 text-sm font-medium">Evidence</h4>
        <ul className="space-y-1 text-sm">
          {s.evidence.map((ev, i) => (
            <li key={i} className="flex gap-2">
              <span className={`h-fit shrink-0 rounded px-2 py-0.5 text-xs ${SOURCE_STYLE[ev.source].cls}`}>
                {SOURCE_STYLE[ev.source].label}
              </span>
              <span>{ev.note}</span>
            </li>
          ))}
        </ul>
      </div>

      {s.assumptions.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-medium">Assumptions</h4>
          <ul className="list-disc pl-5 text-sm text-gray-700">
            {s.assumptions.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </div>
      )}

      {s.risks.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-medium">Risks</h4>
          <ul className="list-disc pl-5 text-sm text-gray-700">
            {s.risks.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      <div>
        <h4 className="mb-1 text-sm font-medium">Test plan</h4>
        <p className="text-sm text-gray-700">{s.test_plan}</p>
      </div>

      <p className="text-xs text-gray-500">{s.rank_reason.explanation}</p>
      <p className="text-xs italic text-gray-500">{s.outcome_disclaimer}</p>
      <CreateExperimentButton planId={planId} rank={s.rank} />
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

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <Link href="/" className="text-sm text-gray-500 underline">← Back to dashboard</Link>

      {error && <p className="text-red-600">{error}</p>}
      {!plan && !error && <p>Building rescue plan…</p>}

      {plan && (
        <>
          <h1 className="text-2xl font-semibold">{plan.product_name}</h1>
          {planId !== null && <p className="text-xs text-gray-500">Plan #{planId}</p>}

          {plan.qloo_note && (
            <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">{plan.qloo_note}</div>
          )}

          {Object.keys(plan.stages_failed).length > 0 && (
            <div className="rounded border border-red-200 bg-red-50 p-3 text-sm">
              <div className="font-medium">This plan is partial.</div>
              <div>{plan.limitations}</div>
            </div>
          )}

          <div className="space-y-5">
            {plan.strategies.map((s) => <StrategyCard key={s.rank} s={s} planId={planId} />)}
          </div>

          {plan.rejected.length > 0 && (
            <section>
              <h2 className="mb-2 text-lg font-medium">Options we ruled out</h2>
              <ul className="space-y-2 text-sm">
                {plan.rejected.map((r, i) => (
                  <li key={i} className="rounded border p-3">
                    <div className="font-medium">{r.name}</div>
                    <div className="text-gray-600">{r.reasons.join(" ")}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <p className="text-xs text-gray-500">{plan.limitations}</p>
        </>
      )}
    </main>
  );
}

export default function RescuePage() {
  return (
    <Suspense fallback={<main className="p-8">Loading…</main>}>
      <RescueContent />
    </Suspense>
  );
}
