import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[10px] border text-sm font-semibold transition-[background,border-color,color,box-shadow,transform] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/20 disabled:pointer-events-none disabled:opacity-40 active:scale-[0.97] [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "border-white/25 bg-gradient-to-b from-[#e0e0e0] to-[#b8b8b8] text-[#111] shadow-[0_4px_14px_-4px_rgba(0,0,0,0.3),inset_0_1px_0_rgba(255,255,255,0.6)] hover:shadow-[0_6px_18px_-8px_rgba(0,0,0,0.12)]",
        destructive:
          "border-red-900/20 bg-red-700 text-white hover:bg-red-800",
        outline:
          "border-black/15 bg-white/60 text-[var(--ink-2)] hover:border-black/20 hover:bg-white/90 hover:text-[var(--ink)] hover:shadow-[0_6px_18px_-8px_rgba(0,0,0,0.1)]",
        secondary:
          "border-black/10 bg-black/5 text-[var(--ink)] hover:bg-black/10",
        ghost:
          "border-transparent bg-transparent text-[var(--ink-2)] hover:bg-black/5 hover:text-[var(--ink)]",
        link: "border-transparent bg-transparent text-[var(--ink)] underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        lg: "h-10 px-6",
        icon: "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant,
  size,
  type = "button",
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants>) {
  return (
    <button
      type={type}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
