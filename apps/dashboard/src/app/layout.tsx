import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Memora Dashboard",
  description: "Caregiver admin dashboard for the Memora smart-glasses memory assistant.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-ink-950 text-neutral-100 antialiased">{children}</body>
    </html>
  );
}
