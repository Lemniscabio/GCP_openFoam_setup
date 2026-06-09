import { useEffect, useRef, useState } from "react";

type ToastProps = {
  message: string | null;
  onDismiss: () => void;
  duration?: number;
};

const EXIT_DURATION = 160;

export function Toast({ message, onDismiss, duration = 3500 }: ToastProps) {
  const [renderedMessage, setRenderedMessage] = useState(message);
  const [exiting, setExiting] = useState(false);
  const autoDismissTimer = useRef<number | undefined>(undefined);
  const exitTimer = useRef<number | undefined>(undefined);
  const onDismissRef = useRef(onDismiss);

  useEffect(() => {
    onDismissRef.current = onDismiss;
  }, [onDismiss]);

  useEffect(() => {
    window.clearTimeout(autoDismissTimer.current);
    window.clearTimeout(exitTimer.current);

    if (!message) {
      if (renderedMessage) {
        setExiting(true);
        exitTimer.current = window.setTimeout(() => setRenderedMessage(null), EXIT_DURATION);
      }
      return () => window.clearTimeout(exitTimer.current);
    }

    setRenderedMessage(message);
    setExiting(false);
    autoDismissTimer.current = window.setTimeout(() => {
      setExiting(true);
      exitTimer.current = window.setTimeout(() => {
        setRenderedMessage(null);
        onDismissRef.current();
      }, EXIT_DURATION);
    }, duration);

    return () => {
      window.clearTimeout(autoDismissTimer.current);
      window.clearTimeout(exitTimer.current);
    };
  }, [duration, message]);

  function dismiss() {
    window.clearTimeout(autoDismissTimer.current);
    window.clearTimeout(exitTimer.current);
    setExiting(true);
    exitTimer.current = window.setTimeout(() => {
      setRenderedMessage(null);
      onDismissRef.current();
    }, EXIT_DURATION);
  }

  if (!renderedMessage) return null;

  return (
    <div
      className={`toast${exiting ? " toast--exiting" : ""}`}
      role="status"
      aria-live="polite"
    >
      <span>{renderedMessage}</span>
      <button className="toast-dismiss" type="button" onClick={dismiss} aria-label="Dismiss notification">
        &times;
      </button>
    </div>
  );
}
