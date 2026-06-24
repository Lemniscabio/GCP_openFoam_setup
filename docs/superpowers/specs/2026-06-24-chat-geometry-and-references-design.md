# Chat-driven geometry creation + references recipe — Design

**Date:** 2026-06-24
**Status:** Approved for planning
**Covers:** #4 (chat agent for geometry creation, replacing the form as the primary
on-ramp) and #3 (a `references/` folder + a clear recipe for adding a new case *type*).

## Problem

Geometry creation today is a structured form in the Generate tab. Gaurav prefers a
natural-language prompt because specifying a reactor is non-trivial, and a conversational
agent can **ask clarifying questions before generating** instead of silently defaulting.
Separately, the steps to add a *new* reactor family/case type (like the existing
single-phase and two-phase references) are documented only inside `ARCHITECTURE.md` and
aren't surfaced as a clear, followable recipe with a home for new reference cases.

## Goals

- **#4:** A chat-first geometry-creation experience in the Generate tab. The agent
  converses to produce a valid `STRParams` spec — the *same* object the form produces —
  asking clarifying questions when something is ambiguous or missing, then hands off to the
  existing deterministic preview/create flow. The structured form is kept as a one-click
  **"Do it manually"** fallback.
- **#3:** A top-level `references/` folder holding the seed reference cases, plus a
  `references/README.md` recipe a developer or coding agent (codex) follows to add a new
  case type (geometry family + OF writers + variation params).

### Non-goals (YAGNI)

- The chat agent does **not** add new case types, run cases, debug, or compute physics. It
  only fills the geometry/operating spec. (Adding case types is the #3 human/codex recipe.)
- No MCP server. The agent's interface is the `STRParams` schema (small, fixed); there is
  nothing to "discover," so MCP indirection adds no value for this scope.
- No server-side conversation store in v1 (the frontend holds the message history).

## Key design principle (preserves determinism)

The agent produces *input*, not code. Its only output is a valid `STRParams` JSON spec.
It therefore needs the **schema** (fields, types, allowed values, correlations) — **not**
the geometry code. It never computes physics or geometry; the existing deterministic
generators consume the spec exactly as they do for the form. The agent's one tool,
`validate_spec`, runs the *real* `STRParams.model_validate`, so it cannot finalize an
invalid spec and self-corrects against true rules. The LLM is a conversational
form-filler, nothing more.

## #4 Architecture

### UX & flow (Generate tab)

- **Default view = Chat.** The user describes the reactor in natural language. A small
  **"Do it manually"** button above the chat switches to the **existing structured form**
  (kept intact as the deterministic fallback / power path); a control toggles back to chat.
- The agent **asks clarifying questions** when the description is ambiguous or missing
  required fields, then **proposes the resolved spec in the chat and asks for confirmation**
  ("Here's what I'll build: … — generate?").
- On confirmation, the frontend calls the **existing** `/api/generate/preview` with the
  finalized spec → the **same 3D preview** the form produces. The agent **stops at
  preview.** From there the existing flow is unchanged: inspect/edit case files → Create /
  variations. The agent never creates a case itself.

### Backend

- **New endpoint:** `POST /api/generate/chat` with body `{ messages: ChatMessage[] }`
  (the full running conversation; stateless — no server session store in v1).
- The handler calls **Gemini** (`gemini-2.5-flash`) with:
  - a **system prompt** containing a compact `STRParams` schema description — fields,
    required vs optional, allowed values (`dished`/`flat`, `rushton`,
    `single_phase`/`two_phase`), and the auto-fill correlations (blade L=D/4, H=D/5,
    baffle=T/12, etc.). Derived from the pydantic model so it does not drift from code.
  - one tool/function **`validate_spec(spec) -> {ok, errors}`** that runs
    `STRParams.model_validate` and returns validity. The agent uses it to self-check
    before finalizing.
- **Response shape:** `{ reply: str, spec: dict | null }`. While `spec` is null the agent
  is still clarifying (show `reply` in the chat). When `spec` is non-null it is the
  validated, ready spec; the frontend hands it to `/api/generate/preview`.
- **Gemini plumbing (re-add — removed earlier):** add `google-genai` as a backend
  dependency; restore the `GEMINI_API_KEY` Cloud Run secret wiring in
  `.github/workflows/deploy.yml`. The `gemini-api-key` secret still exists in Secret
  Manager (confirmed), so no new secret needs creating. A `gemini_api_key` dep helper is
  re-added in `backend/deps.py`. A `OF_DEV_NO_IAP`-style dev fallback is not needed; local
  dev reads the key from `.env.local`.

### New / changed files (indicative)

- `phase3-run-app/backend/routes_generate.py` — add `chat` route.
- `phase3-run-app/backend/schemas.py` — `ChatReq`, `ChatResp`, `ChatMessage`.
- `phase3-run-app/core/geometry_chat.py` (new) — the Gemini agent: builds the schema
  prompt, runs the conversation, exposes `validate_spec`, returns `{reply, spec}`.
- `phase3-run-app/core/schema_doc.py` (new) — derive the compact schema description from
  `str_cad.schema.STRParams` (single source of truth).
- `phase3-run-app/backend/deps.py` — re-add `gemini_api_key`.
- `phase3-run-app/frontend/src/views/GenerateView.tsx` — chat-first UI + "Do it manually"
  toggle to the existing form; on finalized spec, drive the existing preview path.
- `phase3-run-app/frontend/src/components/GeometryChat.tsx` (new) — the chat component.
- `phase3-run-app/frontend/src/lib/api.ts` — `generateChat` method.
- `.github/workflows/deploy.yml` — restore `--update-secrets GEMINI_API_KEY`.

## #3 Architecture (references folder + recipe)

- Create top-level **`references/`**; move `singlephase/` and `twophase/` into it as the
  seed reference cases. Update the path references in `README.md` and `docs/ARCHITECTURE.md`
  (and `part-a-cad` golden tests / `_default_log_fetcher` only if they reference those
  paths — verify; the part-a-cad golden tests read `examples/*.json`, not the sibling dirs,
  so they are unaffected, but confirm during implementation).
- Add **`references/README.md`** — the explicit recipe to add a new case type:
  1. Add a reference case folder under `references/<name>/` (the known-good target).
  2. Register a geometry family/impeller in `part-a-cad/str_cad/geometry/registry.py`.
  3. Add the `ofcase/` writers (or a new `ofcase/<physics>/`), dispatched in `build_case`.
  4. Expose its variation params (the geometry-fixed axes) in `variations.py` and the UI.
  5. Add golden tests against the new reference.
- This recipe is for a **developer or codex** — the runtime chat agent does not use it.

## Data flow (end to end)

`user prompt → /api/generate/chat (Gemini + validate_spec) → {reply | finalized spec}`.
On finalized spec: `→ /api/generate/preview (deterministic geometry + case) → 3D preview
+ case-file editor → /api/generate/create or /variations` (all unchanged).

## Error handling

- Gemini unavailable / key missing / rate-limited → the chat surfaces a clear error and
  points the user to **"Do it manually"** (the form). No hard single point of failure.
- Agent proposes an invalid spec → `validate_spec` returns errors → the agent must correct
  before it can finalize (frontend only previews a non-null, validated spec).
- Malformed model output (non-JSON spec) → treated as still-clarifying; the agent is
  re-prompted to produce a valid spec, or the user falls back to the form.

## Testing

- `core/schema_doc.py`: the derived schema description includes every required field +
  allowed values + correlations.
- `validate_spec`: accepts the golden specs, rejects known-invalid ones (e.g. liquid >
  tank height, impellers don't fit).
- `/api/generate/chat` with a **mocked** Gemini: a clarify turn returns `spec=null` + a
  question; a finalize turn returns a validated `spec`. No real LLM in unit tests.
- Finalized spec flows through `/api/generate/preview` (reuse existing generate tests).
- Frontend: `GeometryChat` renders messages, sends history, switches to the form via
  "Do it manually" (vitest).
- The `references/` move does not break part-a-cad tests (they use `examples/*.json`).

## Risks

- **LLM dependency for the primary path** — mitigated by the "Do it manually" form fallback.
- **Misinterpretation** — mitigated by the explicit confirm-the-resolved-spec step before
  preview, and `validate_spec` enforcing schema validity.
- **Re-adding a removed dependency (Gemini)** — small, well-understood; the secret already
  exists. The difference from the removed one-shot extractor: this is multi-turn and asks
  before generating, and the form remains available.

## Build order

Both ship in this cycle. Suggested sequence: #3 (references move + recipe — small,
foundational, low-risk) → #4 backend (schema_doc, geometry_chat, chat route, Gemini
re-wire) → #4 frontend (chat component + "Do it manually" toggle) → deploy.
