import type { ReactNode } from "react";

export const metadata = {
  title: "ValueGraph Studio",
  description: "Build a theme, run CVE, process tickets, publish.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
