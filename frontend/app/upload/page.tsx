"use client";

import Link from "next/link";
import { useState } from "react";
import { importInventory, previewInventory } from "@/lib/api";
import type { ImportResult } from "@/types/inventory";
import type { PreviewResult } from "@/types/preview";

const ACTION_CLS: Record<string, string> = {
  new: "bg-green-100 text-green-800",
  will_update: "bg-blue-100 text-blue-800",
  invalid: "bg-red-100 text-red-800",
};

const ACTION_LABEL: Record<string, string> = {
  new: "New",
  will_update: "Will update",
  invalid: "Invalid",
};

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onPreview() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setPreview(await previewInventory(file));
    } catch (e) {
      setPreview(null);
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function onImport() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await importInventory(file));
      setPreview(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const importable = preview ? preview.total_rows - preview.invalid_count : 0;

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-8">
      <Link href="/" className="text-sm text-gray-500 underline">← Back to dashboard</Link>
      <h1 className="text-2xl font-semibold">Upload inventory</h1>
      <p className="text-sm text-gray-600">
        CSV, up to 2 MB and 2,000 rows. Preview checks the file first and saves nothing.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept=".csv"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setPreview(null);
            setResult(null);
            setError(null);
          }}
          className="text-sm"
        />
        <button
          onClick={onPreview}
          disabled={!file || busy}
          className="rounded bg-black px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          {busy && !preview ? "Checking…" : "Preview"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {result && (
        <div className="space-y-2 rounded border border-green-300 bg-green-50 p-4 text-sm">
          <div className="font-medium">
            Imported {result.imported_count} products: {result.created_count} new,{" "}
            {result.updated_count} updated, {result.skipped_count} skipped.
          </div>
          <Link href="/" className="underline">View dashboard</Link>
        </div>
      )}

      {preview && (
        <section className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              ["Rows", preview.total_rows],
              ["New", preview.new_count],
              ["Will update", preview.update_count],
              ["Invalid", preview.invalid_count],
            ].map(([label, n]) => (
              <div key={label} className="rounded-lg border p-3">
                <div className="text-sm text-gray-500">{label}</div>
                <div className="text-xl font-semibold">{n}</div>
              </div>
            ))}
          </div>

          {preview.warning_count > 0 && (
            <p className="text-sm text-amber-700">{preview.warning_count} warning(s). Rows with warnings can still be imported.</p>
          )}

          <div className="max-h-96 overflow-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-50 text-left">
                <tr>
                  <th className="p-2">Row</th>
                  <th className="p-2">SKU</th>
                  <th className="p-2">Product</th>
                  <th className="p-2">Action</th>
                  <th className="p-2">Issues</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row_number} className="border-t align-top">
                    <td className="p-2">{r.row_number}</td>
                    <td className="p-2">{r.product_id}</td>
                    <td className="p-2">{String(r.values.product_name ?? "")}</td>
                    <td className="p-2">
                      <span className={`rounded px-2 py-0.5 text-xs ${ACTION_CLS[r.action] ?? "bg-gray-100"}`}>
                        {ACTION_LABEL[r.action] ?? r.action}
                      </span>
                    </td>
                    <td className="p-2 text-xs">
                      {r.errors.map((x, i) => (
                        <div key={"e" + i} className="text-red-700">{x.field}: {x.message}</div>
                      ))}
                      {r.warnings.map((x, i) => (
                        <div key={"w" + i} className="text-amber-700">{x.field}: {x.message}</div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <button
            onClick={onImport}
            disabled={busy || importable === 0}
            className="rounded bg-black px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {busy ? "Importing…" : `Import ${importable} valid rows`}
          </button>
          {preview.invalid_count > 0 && (
            <p className="text-xs text-gray-500">Invalid rows are skipped. Valid rows still import.</p>
          )}
        </section>
      )}
    </main>
  );
}
