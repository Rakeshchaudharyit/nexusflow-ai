import type { Metadata } from "next";
import "./globals.css";
import "./precision.css";
import { AuthProvider } from "@/components/auth-provider";

export const metadata: Metadata = {
  title: "NexusFlow AI · Agent Infrastructure",
  description:
    "Multi-agent orchestration, MCP tooling, execution traces and human oversight.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
