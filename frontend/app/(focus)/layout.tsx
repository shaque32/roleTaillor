import { DotBackground } from "@/components/fx/DotBackground";
import { Logo } from "@/components/shell/Logo";

export default function FocusLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-80 overflow-hidden">
        <DotBackground fade />
      </div>
      <header className="relative bg-transparent">
        <div className="mx-auto flex h-16 max-w-xl items-center px-4 sm:px-6">
          <Logo />
        </div>
      </header>
      <main id="main" className="relative mx-auto max-w-xl px-4 pb-16 pt-6 sm:px-6">
        {children}
      </main>
    </div>
  );
}
