import { AppNav } from "@/components/shell/AppNav";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AppNav />
      <main id="main" className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        {children}
      </main>
    </>
  );
}
