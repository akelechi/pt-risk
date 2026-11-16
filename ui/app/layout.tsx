import type { Metadata } from "next";
import "../styles/tokens.css";
import "./globals.css";

// Families are named by the tokens (--font-ui, --font-mono, --font-display), so the faces are
// loaded under their real names. Josefin Sans is the display fallback named in docs/brand.md §3.
const FONTS_URL =
  "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&family=Josefin+Sans:wght@600;700&display=swap";

export const metadata: Metadata = {
  title: "Roseton Ledger",
  description: "Per-plant commercial model: offers, prices, dispatch and cash, hour by hour.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href={FONTS_URL} />
      </head>
      <body>{children}</body>
    </html>
  );
}
