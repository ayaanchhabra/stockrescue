"use client";

import { useState } from "react";
import { createExperiment } from "@/lib/api";

export default function CreateExperimentButton({
  planId,
  rank,
}: {
  planId: number | null;
  rank: number;
}) {
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [message, setMessage] = useState("");

  if (planId === null) {
    return <p className="text-xs text-gray-500">Plan wasn&apos;t saved, so an experiment can&apos;t be created from it.</p>;
  }

  async function onClick() {
    setState("loading");
    try {
      const exp = await createExperiment(planId as number, rank);
      setMessage(`Experiment #${exp.id ?? "?"} created (${exp.status ?? "proposed"}).`);
      setState("done");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Something went wrong.");
      setState("error");
    }
  }

  if (state === "done") return <p className="text-sm text-green-700">{message}</p>;

  return (
    <div className="space-y-1">
      <button
        onClick={onClick}
        disabled={state === "loading"}
        className="rounded bg-black px-3 py-1.5 text-sm text-white disabled:opacity-50"
      >
        {state === "loading" ? "Creating…" : "Create experiment"}
      </button>
      {state === "error" && <p className="text-sm text-red-600">{message}</p>}
    </div>
  );
}
