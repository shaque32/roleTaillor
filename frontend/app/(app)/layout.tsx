import { AppNav } from "@/components/shell/AppNav";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AppNav />
      <main id="main" className="mx-auto max-w-5xl px-4 pb-28 pt-8 sm:px-6 md:pb-16 md:pt-10">
        {children}
      </main>
    </>
  );
}
