import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Memora Dashboard",
  description: "Dummy device + dashboard for the Memora smart-glasses backend.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-neutral-950 text-neutral-100 antialiased">{children}</body>
    </html>
  );
}
