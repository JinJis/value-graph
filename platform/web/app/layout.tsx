import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "ValueGraph",
  description: "Ask anything about markets, stocks, news, and the economy — with sources.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
