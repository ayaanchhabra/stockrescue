import Link from "next/link";
import { Suspense } from "react";
import NavLinks from "./NavLinks";

export default function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-neutral-800 bg-black/80 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <Link href="/" className="font-display text-lg tracking-tight">
          StockRescue<span className="text-emerald-400">.</span>
        </Link>
        <Suspense fallback={null}>
          <NavLinks />
        </Suspense>
      </div>
    </header>
  );
}
