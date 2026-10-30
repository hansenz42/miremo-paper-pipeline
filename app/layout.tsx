import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  title: 'Miremo · Paper Studio',
  description: '阅读论文，追踪每一个术语的来源。',
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
