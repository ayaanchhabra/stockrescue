"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import PageShell from "@/components/PageShell";
import { clearRetailerToken, getRetailerSettings, saveRetailerToken } from "@/lib/api";

export default function AccessPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function connect(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSuccess(false);
    saveRetailerToken(token);
    try {
      await getRetailerSettings();
      setSuccess(true);
      router.push("/");
    } catch (caught) {
      clearRetailerToken();
      setError(caught instanceof Error ? caught.message : "Could not verify the API token.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell>
      <div className="mx-auto max-w-xl space-y-6">
        <Link href="/" className="text-sm text-neutral-500 underline">← Back to dashboard</Link>
        <div>
          <p className="text-xs uppercase tracking-widest text-emerald-400">Retailer access</p>
          <h1 className="mt-2 font-display text-3xl">Connect your StockRescue API</h1>
          <p className="mt-3 text-sm leading-relaxed text-neutral-400">
            Paste the retailer bearer token issued by your project administrator. The token is kept in this browser tab&apos;s session storage and is not embedded in the application bundle.
          </p>
        </div>
        <form onSubmit={connect} className="panel space-y-4 p-6">
          <label className="block space-y-2 text-sm">
            <span className="text-neutral-300">Retailer API token</span>
            <input
              type="password"
              autoComplete="off"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              required
              minLength={24}
              className="w-full rounded-xl border border-white/15 bg-black/40 px-4 py-3 text-white outline-none focus:border-emerald-400"
              placeholder="Paste your issued token"
            />
          </label>
          <button disabled={busy || token.trim().length < 24} className="rounded-full bg-emerald-400 px-6 py-3 text-sm font-semibold text-black disabled:opacity-50">
            {busy ? "Verifying…" : "Verify and connect"}
          </button>
          {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
          {success && <p className="text-sm text-emerald-300">Token verified.</p>}
          <p className="text-xs text-neutral-500">Use HTTPS outside localhost. This is a lightweight hackathon-demo token entry flow, not a substitute for a production OAuth/session system.</p>
        </form>
        <button type="button" onClick={() => { clearRetailerToken(); setToken(""); setError(null); }} className="text-xs text-neutral-500 underline">Clear this browser session&apos;s token</button>
      </div>
    </PageShell>
  );
}
