import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "Промснаб — коммерческие предложения", description: "Рабочее место менеджера промышленного B2B" };
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="ru"><body>{children}</body></html>;
}
