import { ApiClient } from "./api";
import { tokenStore } from "./auth";
export type {
  CaseInfo,
  DownloadLink,
  ManagedUser,
  Me,
  ProjectInfo,
  ResultFile,
  ResultRun,
  JobEvent,
  JobLog,
  RunRecord,
  RunSummary,
} from "./api";

// Same-origin (FastAPI serves the SPA), token from the in-memory store.
export const api = new ApiClient("", () => tokenStore.get());

export const OAUTH_CLIENT_ID = (import.meta.env.VITE_OAUTH_CLIENT_ID as string) ?? "";
export const ALLOWED_DOMAIN = (import.meta.env.VITE_ALLOWED_DOMAIN as string) || "lemnisca.bio";
