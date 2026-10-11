import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Shell } from "@/components/Shell";
import { GuardianProvider } from "@/lib/guardian-context";
import "./globals.css";

const sans = Geist({ variable: "--font-geist", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Guardian",
  description: "Safety checks for every AI agent action",
};

// Apply the saved theme before first paint so dark mode doesn't flash.
const themeScript = `try{if(localStorage.getItem("guardian-theme")==="dark")document.documentElement.classList.add("dark")}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="h-full">
        <GuardianProvider>
          <Shell>{children}</Shell>
        </GuardianProvider>
      </body>
    </html>
  );
}
