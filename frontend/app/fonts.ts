import { Unbounded, Instrument_Sans } from "next/font/google";

export const display = Unbounded({
  subsets: ["latin"],
  weight: ["600"],
  variable: "--font-display",
});

export const body = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-body",
});
