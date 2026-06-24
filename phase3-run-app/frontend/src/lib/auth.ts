// Google sign-in (GIS) + ID-token store, persisted to localStorage so a page
// refresh keeps you signed in. The token follows the Google ID token's own
// ~1h expiry; while the tab is active it is silently re-issued before expiry
// (see startSessionKeepAlive) so an active user is never logged out mid-work.
const STORAGE_KEY = "of_session";

// Re-issue the Google ID token this long before it expires, while the user is active.
const RENEW_LEAD_MS = 5 * 60 * 1000; // 5 min
// Stop renewing (let the session lapse) after this much inactivity.
const IDLE_TIMEOUT_MS = 12 * 60 * 60 * 1000; // 12 h
const CHECK_INTERVAL_MS = 60 * 1000; // 60 s
const RENEW_THROTTLE_MS = 90 * 1000; // don't re-attempt renewal more than this often

// Local-dev test hook: set localStorage.of_auth_renew_lead_ms to a large value
// (e.g. 4000000) to force a renewal attempt on the next tick right after sign-in,
// so silent renewal can be verified in seconds instead of waiting ~1h.
function renewLeadMs(): number {
  try {
    const raw = Number(localStorage.getItem("of_auth_renew_lead_ms"));
    if (Number.isFinite(raw) && raw > 0) return raw;
  } catch {
    /* ignore */
  }
  return RENEW_LEAD_MS;
}

export class TokenStore {
  private token: string | null = null;
  private expMs = 0;
  private email = "";

  constructor() {
    this.restore();
  }

  set(token: string, googleExpMs: number, email = "") {
    this.token = token;
    // Follow the Google ID token's own expiry (defensive 55-min fallback if absent).
    this.expMs = googleExpMs || Date.now() + 55 * 60 * 1000;
    this.email = email;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, exp: this.expMs, email }));
    } catch {
      /* storage unavailable — fall back to in-memory only */
    }
  }

  get(): string | null {
    return this.token && Date.now() < this.expMs ? this.token : null;
  }

  getEmail(): string {
    return this.get() ? this.email : "";
  }

  expiresAt(): number {
    return this.expMs;
  }

  clear() {
    this.token = null;
    this.expMs = 0;
    this.email = "";
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }

  private restore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const o = JSON.parse(raw) as { token: string; exp: number; email?: string };
      if (o.token && Date.now() < o.exp) {
        this.token = o.token;
        this.expMs = o.exp;
        this.email = o.email ?? "";
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      /* corrupt entry — ignore */
    }
  }
}

export const tokenStore = new TokenStore();

// Set once GIS is initialized: silently re-issues a fresh credential (One Tap auto-select).
let gisRenew: (() => void) | null = null;
let lastActivityMs = Date.now();
let lastRenewAttempt = 0;

function markActivity() {
  // visibilitychange fires on tab hide too; only count the tab becoming visible.
  if (document.visibilityState === "hidden") return;
  lastActivityMs = Date.now();
}

function tryRenew() {
  if (!gisRenew) return;
  if (Date.now() - lastRenewAttempt < RENEW_THROTTLE_MS) return;
  lastRenewAttempt = Date.now();
  gisRenew();
}

// Initialize Google Identity Services and prompt for sign-in.
// clientId = import.meta.env.VITE_OAUTH_CLIENT_ID
export function initGoogleSignIn(clientId: string, onSignedIn: (email: string) => void) {
  const start = (attempt = 0) => {
    // GIS script (index.html) is async — wait until window.google is ready.
    const g = (window as unknown as { google?: { accounts?: { id?: any } } }).google?.accounts?.id;
    if (!g) {
      if (attempt > 100) throw new Error("Google sign-in script failed to load");
      setTimeout(() => start(attempt + 1), 100);
      return;
    }
    g.initialize({
      client_id: clientId,
      auto_select: true, // allow silent re-issue for an already-consented single session
      callback: (resp: { credential: string }) => {
        const claims = JSON.parse(atob(resp.credential.split(".")[1]));
        tokenStore.set(resp.credential, (claims.exp ?? 0) * 1000, claims.email);
        onSignedIn(claims.email);
      },
    });
    // Re-issuing the credential = re-prompting One Tap; with auto_select + an existing
    // session this is silent and fires the callback above with a fresh token.
    gisRenew = () => { try { g.prompt(); } catch { /* ignore */ } };
    const btn = document.getElementById("gsi-button");
    if (btn) g.renderButton(btn, { theme: "outline", size: "large", text: "signin_with" });
    g.prompt(); // also show One Tap
  };
  start();
}

// Keep an active session alive: re-issue the Google token before it expires while the
// user is active; only invoke onExpired (logout) once the token has lapsed AND the user
// has been idle past IDLE_TIMEOUT_MS (or no renewer is available). Returns a cleanup fn.
export function startSessionKeepAlive(onExpired: () => void): () => void {
  const events = ["pointerdown", "keydown", "wheel", "touchstart", "visibilitychange"];
  events.forEach((e) => window.addEventListener(e, markActivity, { passive: true }));
  lastActivityMs = Date.now();

  const tick = () => {
    const remaining = tokenStore.expiresAt() - Date.now();
    const idle = Date.now() - lastActivityMs;
    const active = idle < IDLE_TIMEOUT_MS;
    if (remaining <= 0) {
      if (active && gisRenew) tryRenew(); // active but lapsed — try to recover silently
      else onExpired();
      return;
    }
    if (remaining < renewLeadMs() && active) tryRenew();
  };

  const id = window.setInterval(tick, CHECK_INTERVAL_MS);
  tick(); // run once immediately
  return () => {
    window.clearInterval(id);
    events.forEach((e) => window.removeEventListener(e, markActivity));
  };
}
