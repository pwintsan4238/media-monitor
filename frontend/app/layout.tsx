import type { Metadata } from "next";
import { Inter, Newsreader } from "next/font/google";
import "./globals.css";
import AppShell from "@/components/AppShell";

// Only Latin faces are loaded. Burmese text uses the operating system's Myanmar font.
const sans = Inter({ variable: "--font-inter", subsets: ["latin"], display: "swap" });
const serif = Newsreader({ variable: "--font-newsreader", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: "Media Monitor",
  description: "Focused search and press briefs across a fixed set of Burmese-language news sources",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${sans.variable} ${serif.variable} antialiased`}
    >
      <body className="min-h-dvh flex flex-col">
        <a href="#main" className="skip-link">Skip to content</a>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
