import { useEffect, useState, type ReactNode } from "react";
import { initGoogleSignIn, tokenStore } from "../lib/auth";
import { OAUTH_CLIENT_ID } from "../lib/client";

// Shows the Google sign-in prompt until a valid org token is present, then renders children.
export function SignInGate({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(() => (tokenStore.get() ? "" : null));
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

  if (email === null) {
    return (
      <div className="signin">
        <div className="panel signin-card">
          <div className="brand-mark">OF</div>
          <h1 className="signin-title">OpenFOAM Batch</h1>
          <p className="signin-sub">Sign in with your lemnisca.bio account to continue.</p>
          <div id="gsi-button" />
          {error && <p className="signin-error">{error}</p>}
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
