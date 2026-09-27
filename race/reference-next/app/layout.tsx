import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Expense Tracker",
  description: "Track expenses, budgets and monthly summaries.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav>
          <strong>Expense Tracker</strong>
          <Link href="/">Expenses</Link>
          <Link href="/summary">Summary</Link>
          <Link href="/import">Import</Link>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
