import * as React from "react";

import { cn } from "@/lib/utils";

function Progress({
  className,
  value,
  ...props
}: React.ComponentProps<"div"> & { value?: number | null }) {
  const pct = Math.max(0, Math.min(100, value ?? 0));

  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-black/10",
        className,
      )}
      {...props}
    >
      <div
        className="h-full w-full flex-1 rounded-full bg-[var(--ink)] transition-transform duration-200 ease-[cubic-bezier(0.23,1,0.32,1)]"
        style={{ transform: `translateX(-${100 - pct}%)` }}
      />
    </div>
  );
}

export { Progress };
