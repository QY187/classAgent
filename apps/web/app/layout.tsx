import type { ReactNode } from "react";
import "./globals.css";
import AppShell from "../components/AppShell";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body suppressHydrationWarning><AppShell>{children}</AppShell></body>
    </html>
  );
}
