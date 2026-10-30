"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Dashboard" },
  { href: "/upload", label: "Upload" },
  { href: "/experiments", label: "Experiments" },
];

export default function NavLinks() {
  const path = usePathname();
  return (
    <nav className="flex gap-6 text-sm">
      {links.map((l) => {
        const active =
          l.href === "/" ? path === "/" || path.startsWith("/rescue") : path.startsWith(l.href);
        return (
          <Link
            key={l.href}
            href={l.href}
            className={active ? "text-white" : "text-neutral-400 hover:text-white"}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
