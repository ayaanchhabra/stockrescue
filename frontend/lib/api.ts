import type { ImportResult } from "@/types/inventory";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit) {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "network", "Can't reach the backend. Is it running?");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      res.status,
      body.error ?? "unknown",
      body.message ?? body.detail?.toString() ?? `Request failed (${res.status})`
    );
  }
  const data = (await res.json()) as T;
  return { data, headers: res.headers };
}

export async function getHealth() {
  return (await request<{ status: string; qloo_key_configured: boolean }>("/health")).data;
}

function csvForm(file: File) {
  const form = new FormData();
  form.append("file", file);
  return form;
}

export async function previewInventory(file: File) {
  return (await request<ImportResult>("/inventory/preview", { method: "POST", body: csvForm(file) })).data;
}

export async function importInventory(file: File) {
  return (await request<ImportResult>("/inventory/import", { method: "POST", body: csvForm(file) })).data;
}

export async function getDashboard<T = unknown>() {
  return (await request<T>("/inventory/dashboard")).data;
}

import type { RescuePlan } from "@/types/rescue";

export async function getRescuePlan(productPk: number, refreshQloo = false) {
  const { data, headers } = await request<RescuePlan>(`/rescue/${productPk}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_qloo: refreshQloo }),
  });
  const id = headers.get("X-Rescue-Plan-Id");
  return { plan: data, planId: id ? Number(id) : null };
}

export async function createExperiment(planId: number, rank: number) {
  return (
    await request<{ id?: number; status?: string }>(
      `/rescue/plans/${planId}/strategies/${rank}/experiment`,
      { method: "POST" }
    )
  ).data;
}

import type { Experiment } from "@/types/experiment";

export async function listExperiments() {
  return (await request<Experiment[]>("/experiments")).data;
}

export async function experimentAction(
  id: number,
  action: "approve" | "reject" | "start" | "cancel",
  body?: Record<string, unknown>
) {
  return (
    await request<Experiment>(`/experiments/${id}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    })
  ).data;
}
