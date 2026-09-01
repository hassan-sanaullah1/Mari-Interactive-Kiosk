import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-ui",
  display: "swap",
});

export const metadata: Metadata = {
  title: "MARI · Interactive Kiosk",
  description: "Speech-to-speech assistant kiosk",
};

export const viewport: Viewport = {
  themeColor: "#04121f",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <head>
        {/* Kick off the avatar model fetch as early as possible — before React
            mounts and before the dynamically-imported three.js scene chunk
            loads — so the network transfer of the (large) .glb overlaps with
            JS bootstrap instead of starting after it. */}
        <link rel="preload" href="/models/girl13.glb" as="fetch" crossOrigin="anonymous" fetchPriority="high" />
      </head>
      <body>
        {/* Apply the stored theme before first paint so there's no flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{if(localStorage.getItem('mari-theme')==='light')document.documentElement.dataset.theme='light'}catch(e){}",
          }}
        />
        {children}
      </body>
    </html>
  );
}
