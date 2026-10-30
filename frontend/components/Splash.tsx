"use client";

import { Unbounded } from "next/font/google";
import { useEffect, useState } from "react";

const display = Unbounded({ subsets: ["latin"], weight: ["600"] });

export default function Splash() {
  const [phase, setPhase] = useState<"show" | "exit" | "gone">("show");

  useEffect(() => {
    const t1 = setTimeout(() => setPhase("exit"), 2400);
    const t2 = setTimeout(() => setPhase("gone"), 3400);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, []);

  if (phase === "gone") return null;

  return (
    <div
      className={`splash-curtain fixed inset-0 z-50 flex flex-col items-center justify-center bg-black ${
        phase === "exit" ? "splash-exit" : ""
      }`}
      style={{ backgroundColor: "#000000" }}
    >
      <div className="overflow-hidden px-6">
        <h1
          className={`splash-word ${display.className} text-4xl md:text-7xl`}
          style={{ color: "#ffffff", opacity: 1, letterSpacing: "-0.03em" }}
        >
          StockRescue<span style={{ color: "#34d399" }}>.</span>
        </h1>
      </div>
      <div className="splash-line mt-6 h-px w-40 md:w-72" style={{ backgroundColor: "#ffffff" }} />
      <p
        className="splash-tag mt-5 text-xs uppercase md:text-sm"
        style={{ color: "#ffffff", letterSpacing: "0.3em" }}
      >
        Turn slow stock into sales
      </p>
    </div>
  );
}
