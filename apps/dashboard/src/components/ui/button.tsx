import { cn } from "@/lib/cn";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "ghost" | "outline";

const variants: Record<Variant, string> = {
  primary: "bg-accent-500 text-white hover:bg-accent-600",
  ghost: "text-neutral-400 hover:text-neutral-100 hover:bg-ink-800",
  outline: "border border-ink-600 text-neutral-300 hover:border-ink-500 hover:text-neutral-100",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  children: ReactNode;
}

export function Button({ variant = "outline", className, children, ...props }: Props) {
  return (
    <button
      className={cn(
        "rounded-md px-4 py-2 text-sm font-medium transition-colors",
        variants[variant],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
