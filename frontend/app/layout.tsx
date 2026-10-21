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
        {/* No <link rel="preload"> for the avatar.
            It looks like free parallelism, but the model is fetched as six
            parallel byte ranges (lib/avatar-fetch.ts) because this host throttles
            per connection — a preload would be a seventh connection pulling the
            whole file serially, competing with the six that are doing the real
            work, and its response is not the one the loader ends up using. The
            fetch starts as soon as the avatar chunk evaluates, which is early
            enough. */}
      </head>
      <body>
        {/* Apply the theme before first paint so there's no flash: the stored
            choice if there is one, else light on mobile/portrait (the same
            max-aspect-ratio: 6/5 breakpoint the CSS uses everywhere) and dark
            on desktop. Kept in sync with lib/theme.ts's readTheme(), which
            can't run this early — localStorage isn't available during SSR. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var t=localStorage.getItem('mari-theme');if(t==='light'){document.documentElement.dataset.theme='light'}else if(t!=='dark'&&window.matchMedia('(max-aspect-ratio: 6/5)').matches){document.documentElement.dataset.theme='light'}}catch(e){}",
          }}
        />
        {children}
      </body>
    </html>
  );
}
