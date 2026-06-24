import { useEffect, useState, type ReactNode } from "react";
import { initGoogleSignIn, startSessionKeepAlive, tokenStore } from "../lib/auth";
import { OAUTH_CLIENT_ID, ALLOWED_DOMAIN } from "../lib/client";

// Shows the Google sign-in prompt until a valid org token is present, then renders children.
// A non-@lemnisca.bio account gets a friendly "not authorized" screen (the backend
// enforces this for real via the hd claim; this is just clean UX).
export function SignInGate({ children }: { children: ReactNode }) {
  // restore a persisted session (survives refresh) — email comes back too
  const [email, setEmail] = useState<string | null>(() =>
    tokenStore.get() ? tokenStore.getEmail() || "" : null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (email !== null) return;
    if (!OAUTH_CLIENT_ID) {
      setError("VITE_OAUTH_CLIENT_ID not configured at build time");
      return;
    }
    try {
      initGoogleSignIn(OAUTH_CLIENT_ID, (e) => setEmail(e));
    } catch (e) {
      setError(String(e));
    }
  }, [email]);

  // Keep an active session alive: the Google token is silently re-issued before it
  // expires while the user is active, so there's no mid-work logout. Only fall back to
  // the sign-in screen once the token has actually lapsed and renewal couldn't recover it.
  useEffect(() => {
    if (email === null) return;
    return startSessionKeepAlive(() => {
      tokenStore.clear();
      setEmail(null);
    });
  }, [email]);

  const authorized = email === "" || (!!email && email.toLowerCase().endsWith(`@${ALLOWED_DOMAIN}`));

  if (email !== null && !authorized) {
    return (
      <div className="signin">
        <div className="panel signin-card">
          <div className="brand-mark">OF</div>
          <h1 className="signin-title">Not authorized</h1>
          <p className="signin-sub">
            <code style={{ fontFamily: "var(--f-mono)" }}>{email}</code> isn't a <strong>@{ALLOWED_DOMAIN}</strong> account.
            This app is restricted to {ALLOWED_DOMAIN} members.
          </p>
          <button className="btn-add" onClick={() => { tokenStore.clear(); location.reload(); }}>
            Sign in with a different account
          </button>
        </div>
      </div>
    );
  }

  if (email === null) {
    return (
      <div className="signin">
        <div className="panel signin-card">
          <div className="brand-mark">OF</div>
          <h1 className="signin-title">OpenFOAM Batch</h1>
          <p className="signin-sub">Sign in with your {ALLOWED_DOMAIN} account to continue.</p>
          <div id="gsi-button" />
          {error && <p className="signin-error">{error}</p>}
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
