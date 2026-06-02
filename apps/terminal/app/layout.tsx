import type { ReactNode } from "react";

export const metadata = {
  title: "ValueGraph Terminal",
  description: "Supply-chain intelligence, visualized.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
