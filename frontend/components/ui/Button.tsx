import { forwardRef, type ButtonHTMLAttributes } from "react";
import Link from "next/link";
import { cx } from "@/lib/format";
import { Spinner } from "./Spinner";
import { focusRing } from "./styles";

type Variant = "primary" | "secondary" | "soft" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const base = cx(
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors active:translate-y-px",
  "disabled:cursor-not-allowed disabled:opacity-50 whitespace-nowrap",
  focusRing,
);
const variants: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700",
  secondary: "border border-line bg-white text-ink shadow-sm hover:bg-surface-sunken",
  soft: "bg-brand-50 text-brand-700 hover:bg-brand-100",
  ghost: "text-ink-muted hover:bg-surface-sunken hover:text-ink",
  danger: "bg-red-600 text-white hover:bg-red-700",
};
const sizes: Record<Size, string> = { sm: "h-9 px-3 text-sm", md: "h-11 px-4 text-sm", lg: "h-12 px-6 text-base" };

export function buttonClass(variant: Variant = "primary", size: Size = "md", className?: string) {
  return cx(base, variants[variant], sizes[size], className);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, disabled, className, children, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={buttonClass(variant, size, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
});

/** Square icon-only button. `label` becomes the accessible name and the tooltip. */
export const IconButton = forwardRef<HTMLButtonElement, { label: string } & ButtonProps>(function IconButton(
  { label, variant = "ghost", size = "md", className, children, ...buttonProps },
  ref,
) {
  return (
    <Button
      ref={ref}
      variant={variant}
      size={size}
      className={cx("shrink-0 !px-0", size === "sm" ? "w-9" : size === "lg" ? "w-12" : "w-11", className)}
      aria-label={label}
      title={label}
      {...buttonProps}
    >
      {children}
    </Button>
  );
});

export function ButtonLink({
  href,
  variant = "primary",
  size = "md",
  className,
  children,
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)}>
      {children}
    </Link>
  );
}
