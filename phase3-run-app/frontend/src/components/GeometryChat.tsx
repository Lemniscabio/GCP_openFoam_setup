import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "../lib/client";

type ChatMessage = { role: "user" | "model"; content: string };

// In-memory only: the conversation survives leaving and returning to the Generate tab
// while the page is open (this module stays loaded), but a browser reload clears it.
// Intentionally NOT persisted to storage.
let MEMORY: ChatMessage[] = [];

const INTRO =
  "Describe the stirred-tank reactor you want — size, bottom (dished/flat), impellers, " +
  "baffles, rpm, single- or two-phase. I'll ask if anything's missing, then build it.";

// Conversational geometry creation as a single unified chat box: scrollable messages on
// top, a styled input bar attached at the bottom. When the agent has a complete spec it
// surfaces a "Generate this geometry" action that hands the spec to the existing preview.
export function GeometryChat({
  disabled,
  busyPreview,
  onGenerate,
}: {
  disabled: boolean;
  busyPreview: boolean;
  onGenerate: (spec: Record<string, any>) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => MEMORY);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingSpec, setPendingSpec] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  // ChatGPT-style: start typing anywhere and the chat input takes focus + the keystroke.
  useEffect(() => {
    if (disabled) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;       // leave shortcuts alone
      if (e.key.length !== 1) return;                        // only printable characters
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || el?.isContentEditable) return;
      inputRef.current?.focus();                             // the char then lands in it
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [disabled]);

  useEffect(() => { MEMORY = messages; }, [messages]); // keep the in-memory copy in sync

  function clearChat() {
    MEMORY = [];
    setMessages([]);
    setPendingSpec(null);
    setError(null);
  }

  async function send() {
    const text = input.trim();
    if (!text || sending || disabled) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setPendingSpec(null);
    setError(null);
    setSending(true);
    try {
      const response = await api.generateChat({ messages: next });
      setMessages([...next, { role: "model", content: response.reply }]);
      if (response.spec) setPendingSpec(response.spec);
    } catch (e) {
      setError(String(e));
      setMessages([...next, { role: "model", content: "⚠ I hit an error. Try again, or use “Do it manually”." }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        background: "var(--glass-1)",
        border: "1px solid var(--line-2)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "0 10px 30px -18px rgba(0,0,0,0.12)",
      }}
    >
      {/* header */}
      {messages.length > 0 && (
        <div style={{ display: "flex", justifyContent: "flex-end", padding: "6px 10px", borderBottom: "1px solid var(--line-2)", background: "var(--glass-2)" }}>
          <button
            type="button"
            onClick={clearChat}
            style={{ fontSize: 12, color: "var(--ink-2)", background: "transparent", border: 0, cursor: "pointer" }}
          >
            ↺ New chat
          </button>
        </div>
      )}

      {/* messages */}
      <div
        ref={scrollRef}
        className="chat-scroll"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          minHeight: 280,
          maxHeight: 460,
          overflowY: "auto",
          padding: 16,
        }}
      >
        {messages.length === 0 && (
          <div style={{ margin: "auto", maxWidth: 440, textAlign: "center", color: "var(--ink-2)", fontSize: 13, lineHeight: 1.6 }}>
            {INTRO}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.role === "user" ? "user" : "bot"}`}>
            {m.content}
          </div>
        ))}
        {sending && (
          <div className="chat-bubble bot" aria-label="Assistant is typing">
            <span className="chat-typing"><span /><span /><span /></span>
          </div>
        )}
      </div>

      {/* spec-ready CTA (inside the box, above the input bar) */}
      {pendingSpec && (
        <div
          style={{
            display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
            padding: "10px 14px", borderTop: "1px solid var(--line-2)", background: "var(--glass-2)",
          }}
        >
          <span style={{ fontSize: 13, color: "var(--ink)" }}>Spec ready — generate the geometry preview?</span>
          <Button disabled={disabled || busyPreview} onClick={() => onGenerate(pendingSpec)}>
            {busyPreview ? "Generating…" : "Generate this geometry →"}
          </Button>
        </div>
      )}

      {/* input bar (attached to the box) */}
      <div
        style={{
          display: "flex", gap: 8, alignItems: "flex-end",
          padding: 10, borderTop: "1px solid var(--line-2)", background: "var(--glass-2)",
        }}
      >
        <textarea
          ref={inputRef}
          className="input"
          style={{ flex: 1, minHeight: 42, maxHeight: 140, resize: "none" }}
          placeholder={disabled ? "Read-only" : "Describe your reactor…  (Enter to send, Shift+Enter for newline)"}
          value={input}
          disabled={disabled || sending}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <Button disabled={disabled || sending || !input.trim()} onClick={send}>
          {sending ? "…" : "Send"}
        </Button>
      </div>
      {error && <div style={{ color: "#dc2626", fontSize: 12, padding: "0 12px 10px" }}>ERROR: {error}</div>}
    </div>
  );
}
