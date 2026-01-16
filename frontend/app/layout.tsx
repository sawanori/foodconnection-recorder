import { Providers } from './providers';
import './globals.css';

export const metadata = {
  title: 'Food Connection Recorder',
  description: 'Web実績ページ自動巡回・録画システム',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body className="bg-gray-100">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
