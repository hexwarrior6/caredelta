import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CareDelta",
  description: "Source-backed clinical change radar for safer handoffs.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
