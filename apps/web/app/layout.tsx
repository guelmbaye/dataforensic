import type { Metadata } from "next";

import { TopBar } from "@/components/TopBar";
import "./globals.css";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://dataforensic.vylantic.com";

const DESCRIPTION =
  "The organizational memory engine for DataHub. An agent that investigates data " +
  "incidents, proves the cause with evidence, and turns every resolution into " +
  "reusable knowledge.";

// The icon links are generated from app/icon.png, app/apple-icon.png and
// app/favicon.ico. Declaring them again here would only risk drifting from the
// files that are actually shipped.
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "DATAFORENSIC AI",
    template: "%s · DATAFORENSIC AI",
  },
  description: DESCRIPTION,
  applicationName: "DATAFORENSIC AI",
  openGraph: {
    type: "website",
    siteName: "DATAFORENSIC AI",
    title: "DATAFORENSIC AI — the organizational memory engine for DataHub",
    description: DESCRIPTION,
    images: [{ url: "/logo.png", width: 960, height: 240, alt: "DATAFORENSIC AI" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "DATAFORENSIC AI",
    description: DESCRIPTION,
    images: ["/logo.png"],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
        />
      </head>
      <body>
        <TopBar />
        {children}
      </body>
    </html>
  );
}
