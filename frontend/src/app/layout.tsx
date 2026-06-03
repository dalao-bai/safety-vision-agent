import "./styles.css";

export const metadata = {
  title: "Safety Vision Agent",
  description: "多轮对话式施工安全隐患识别专家 Agent"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
