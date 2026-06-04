import { useReducedMotion, type Variants } from "framer-motion";

export function usePanelVariants(): Variants {
  const reduce = useReducedMotion();
  return {
    hidden: { opacity: 0, y: reduce ? 0 : 8 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.2, ease: [0.23, 1, 0.32, 1] },
    },
    exit: {
      opacity: 0,
      y: reduce ? 0 : -4,
      transition: { duration: 0.15, ease: "easeIn" },
    },
  };
}

export function useListItemVariants(): Variants {
  const reduce = useReducedMotion();
  return {
    hidden: { opacity: 0, y: reduce ? 0 : 6 },
    visible: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.18,
        ease: [0.23, 1, 0.32, 1],
        delay: reduce ? 0 : i * 0.04,
      },
    }),
  };
}
