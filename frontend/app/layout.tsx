import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AVATAR_MODEL_URL } from "@/components/avatar/state";

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
            JS bootstrap instead of starting after it.

            No crossOrigin here, deliberately. A preload is only reused for a
            later request whose CORS mode matches it, and drei's useGLTF fetches
            the model same-origin without CORS. With crossOrigin="anonymous" the
            preloaded copy was therefore never claimed and the browser fetched
            the whole model a SECOND time — the download counted twice on exactly
            the connection least able to afford it. */}
        <link rel="preload" href={AVATAR_MODEL_URL} as="fetch" fetchPriority="high" />
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
