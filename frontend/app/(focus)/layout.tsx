import { Logo } from "@/components/shell/Logo";

export default function FocusLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-14 max-w-3xl items-center px-4 sm:px-6">
          <Logo />
        </div>
      </header>
      <main id="main" className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
        {children}
      </main>
    </>
  );
}
