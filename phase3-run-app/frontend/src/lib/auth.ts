// Google sign-in (GIS) + ID-token store, persisted to localStorage so a page
// refresh keeps you signed in, with a hard 60-minute session cap (relogin after).
const STORAGE_KEY = "of_session";
const MAX_SESSION_MS = 60 * 60 * 1000; // 60 minutes

export class TokenStore {
  private token: string | null = null;
  private expMs = 0;
  private email = "";

  constructor() {
    this.restore();
  }

  set(token: string, googleExpMs: number, email = "") {
    this.token = token;
    // expire at the sooner of the Google token's own exp or our 60-min cap
    this.expMs = Math.min(googleExpMs || Infinity, Date.now() + MAX_SESSION_MS);
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
      callback: (resp: { credential: string }) => {
        const claims = JSON.parse(atob(resp.credential.split(".")[1]));
        tokenStore.set(resp.credential, (claims.exp ?? 0) * 1000, claims.email);
        onSignedIn(claims.email);
      },
    });
    const btn = document.getElementById("gsi-button");
    if (btn) g.renderButton(btn, { theme: "outline", size: "large", text: "signin_with" });
    g.prompt(); // also show One Tap
  };
  start();
}
