import type { CSSProperties } from "react";

type SpinnerProps = {
  size?: number;
  label?: string;
};

const bars = Array.from({ length: 12 });

export function Spinner({ size = 20, label = "Loading" }: SpinnerProps) {
  return (
    <span
      className="ios-spinner-status"
      role="status"
      aria-label={label}
      style={{ "--spinner-size": `${size}px` } as CSSProperties}
    >
      <span className="ios-spinner" aria-hidden="true">
        {bars.map((_, index) => (
          <span
            className="ios-spinner-bar"
            key={index}
            style={{
              opacity: 1 - (index * 0.88) / 11,
              transform: `translate(-50%, -50%) rotate(${index * 30}deg) translateY(calc(var(--spinner-size) * -0.35))`,
            }}
          />
        ))}
      </span>
    </span>
  );
}
