import type { Metadata } from "next";
import "./globals.css";
import Splash from "@/components/Splash";
import SiteHeader from "@/components/SiteHeader";
import { body, display } from "./fonts";

export const metadata: Metadata = {
  title: "StockRescue",
  description: "Turn slow-moving inventory into tested sales experiments.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${display.variable} ${body.variable}`}>
        <Splash />
        <SiteHeader />
        {children}
      </body>
    </html>
  );
}
