import type { Metadata } from "next";
import "./globals.css";
import { LiveProvider } from "@/lib/live";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = {
  title: "Build-Up Clipper",
  description: "Turn a full match into a validated compilation of opponent GK build-up sequences.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* Linked rather than bundled: the tool must still build and run on a
            machine with no internet, falling back to the local serif/mono. */}
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Serif:ital@0;1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <LiveProvider>
          <Shell>{children}</Shell>
        </LiveProvider>
      </body>
    </html>
  );
}
