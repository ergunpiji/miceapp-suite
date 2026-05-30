import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";

const geist = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "PrizmaDesk — Kurumsal Finans & İK Yönetim Sistemi",
  description:
    "Fatura, HBF, bordro, izin ve onay akışlarını tek platformda yönetin. Türk KOBİ'leri için tasarlandı.",
  openGraph: {
    title: "PrizmaDesk",
    description: "Kurumsal Finans & İK Yönetim Sistemi",
    locale: "tr_TR",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr" className={`${geist.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
