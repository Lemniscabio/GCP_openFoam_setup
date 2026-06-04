import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center justify-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10.5px] font-bold whitespace-nowrap transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/20 [&>svg]:size-3",
  {
    variants: {
      variant: {
        default:
          "border-black/10 bg-black/80 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.18)]",
        secondary: "border-black/10 bg-black/5 text-[var(--ink-2)]",
        destructive: "border-red-900/20 bg-red-700 text-white",
        outline: "border-black/15 bg-transparent text-[var(--ink)]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />;
}

export { Badge, badgeVariants };
