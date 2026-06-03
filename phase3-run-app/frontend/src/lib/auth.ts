// Google sign-in (GIS) + in-memory ID-token store.
export class TokenStore {
  private token: string | null = null;
  private expMs = 0;
  set(token: string, expMs: number) {
    this.token = token;
    this.expMs = expMs;
  }
  get(): string | null {
    return this.token && Date.now() < this.expMs ? this.token : null;
  }
  clear() {
    this.token = null;
    this.expMs = 0;
  }
}

export const tokenStore = new TokenStore();

// Initialize Google Identity Services and prompt for sign-in.
// clientId = import.meta.env.VITE_OAUTH_CLIENT_ID
export function initGoogleSignIn(clientId: string, onSignedIn: (email: string) => void) {
  // @ts-expect-error google is injected by the GIS script in index.html
  google.accounts.id.initialize({
    client_id: clientId,
    callback: (resp: { credential: string }) => {
      const claims = JSON.parse(atob(resp.credential.split(".")[1]));
      tokenStore.set(resp.credential, (claims.exp ?? 0) * 1000);
      onSignedIn(claims.email);
    },
  });
  // @ts-expect-error
  google.accounts.id.prompt();
}
