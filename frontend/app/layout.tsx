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
