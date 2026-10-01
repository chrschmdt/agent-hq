import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"

import { SiteAnalytics } from "@/components/shell/site-analytics"
import { siteUrl } from "@/lib/site"
import { cn } from "@/lib/utils"

import { Providers } from "./providers"
import "./globals.css"

const sans = Geist({ subsets: ["latin"], variable: "--font-sans" })
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" })

const DESCRIPTION =
  "The control room for a team of AI agents running customer operations for an online store."

export const metadata: Metadata = {
  metadataBase: siteUrl(),
  title: { default: "AHQ", template: "%s | AHQ" },
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    siteName: "AHQ",
    title: "AHQ: AI agents at work",
    description: DESCRIPTION,
    url: "/",
  },
  twitter: {
    card: "summary_large_image",
    title: "AHQ: AI agents at work",
    description: DESCRIPTION,
  },
}

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={cn("font-sans antialiased", sans.variable, mono.variable)}
    >
      <body>
        <Providers>{children}</Providers>
        <SiteAnalytics />
      </body>
    </html>
  )
}
