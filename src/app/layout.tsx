import type { Metadata } from "next";
import { Inter } from "next/font/google";
import localFont from "next/font/local";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const author = localFont({
  src: [
    {
      path: "../fonts/Author-Variable.woff2",
      style: "normal",
    },
    {
      path: "../fonts/Author-VariableItalic.woff2",
      style: "italic",
    },
  ],
  variable: "--font-author",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Dot Reader · Assistive BCI Communication",
  description: "Assistive communication system powered by EEG sensorimotor rhythms and real-time Morse decoding",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${author.variable} dark`} suppressHydrationWarning>
      <body
        className="min-h-screen bg-[var(--ds-bg)] text-[var(--ds-text-primary)] antialiased font-sans selection:bg-white/20 selection:text-white"
        suppressHydrationWarning
      >
        {children}
      </body>
    </html>
  );
}
