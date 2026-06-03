import { ApiClient } from "./api";
import { tokenStore } from "./auth";

// Same-origin (FastAPI serves the SPA), token from the in-memory store.
export const api = new ApiClient("", () => tokenStore.get());

export const OAUTH_CLIENT_ID = (import.meta.env.VITE_OAUTH_CLIENT_ID as string) ?? "";
