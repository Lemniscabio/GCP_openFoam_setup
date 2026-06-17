# Integration — Wire Parts A+B into the Part C app

> Driven by codex (Claude pre-provisions + reviews). Build + test LOCALLY first; deploy later.

**Goal:** Add a "Generate" path to the existing `phase3-run-app` (Part C): natural-language prompt
(or a parameter form) → Part A geometry + Part B case (server-side, light Python) → three.js
preview + textual dict review → write the case into Part C's GCS (`cases/<project>/case_xxxx/case/`)
→ from there the EXISTING Cases→Submit→Batch(command.sh: blockMesh→snappy→topoSet→foamRun)→
Status→Results flow runs unchanged.

**Architecture:** A+B = a case-generator front-end feeding Part C. Generation is light (Cloud Run);
meshing+solving already happen in Batch via the generated `command.sh`. Extraction = Gemini
(`google-genai`, structured JSON → validated STRParams; env `GEMINI_API_KEY`, model gemini-2.5-flash).

**Decisions:** backend imports `str_cad`/`str_cad.ofcase` (adds cadquery+trimesh+google-genai to the
backend env/image — bigger image, accepted); generate writes the case straight to GCS via the backend
SA (no browser signed-URL upload); RBAC-gate generate with `require_runner`; preview rebuilds from
params on create (deterministic, no cache).

---

## Backend tasks

### I1 — Make str_cad importable by the backend + deps
- Local: `phase3-run-app/.venv` → `pip install -e ../part-a-cad` + `pip install cadquery trimesh google-genai`.
- Packaging: add `str-cad @ file:../part-a-cad` (or copy) + the three deps to `requirements-backend.txt`;
  update `backend/Dockerfile` to COPY `part-a-cad` and `pip install ./part-a-cad` before COPY core.
- Acceptance: `phase3-run-app/.venv/bin/python -c "import str_cad, str_cad.ofcase.build, str_cad.extract"` ok.

### I2 — core/generate.py (pure generation, no GCS)
- `build_case_local(*, prompt=None, params=None, case_params_dict=None, gemini_key=None, out_dir) -> dict`:
  if prompt → `str_cad.extract.extract_str_params(prompt, api_key=gemini_key)`; elif params →
  `STRParams.model_validate(params)`. CaseParams from case_params_dict (defaults ok). Then
  `str_cad.builder` build geometry → `str_cad.ofcase.build.build_case(cp, geo_dir, out_dir)`.
  Return `{str_params, case_params, case_dir, geometry_dir}`.
- `read_region_stls(geometry_dir) -> dict[name,bytes]` for preview.
- Test: with `params=` (no LLM) builds a case dir with the expected files (reuse the golden params).

### I3 — write generated case into Part C GCS + register
- core/generate.py `commit_case(case_dir, project, uploaded_by) -> case_id`: allocate a case_id
  (reuse existing naming/case_records), upload the whole `case/` tree to
  `cases/<project>/case_xxxx/case/` via core/storage GcsStorage, write the READY marker +
  metadata.json placement exactly as the existing finalize path does, and register the of_cases
  record. Mirror `routes_cases.py:finalize` semantics so the case is indistinguishable from an
  uploaded one. Test against the InMemory storage/repo fakes.

### I4 — routes_generate.py
- `POST /api/generate/preview` {prompt?|params?, case_params?} → builds in a temp dir, returns
  {str_params, case_params, stls: {region: base64}} (NO GCS write). require_runner.
- `POST /api/generate/create` {project, params, case_params?} → build + commit_case → {case_id}.
  require_runner. (Create takes the resolved params from the preview step, so no second LLM call.)
- Register the router in backend/main.py. Read GEMINI_API_KEY from env in deps.

## Frontend tasks

### I5 — STL viewer + deps
- `npm i three` (+ types). `components/StlViewer.tsx`: render an array of STL blobs/bytes with
  three.js (OrbitControls, distinct light grey materials per region, auto-fit camera).

### I6 — GenerateView.tsx
- Section 1 (new, first tab): a prompt textarea + a "Generate preview" button → calls
  /api/generate/preview → shows (a) the resolved STR params (editable fields), (b) the three.js
  preview of the 6 STLs, (c) a collapsible "case config" text view (controlDict/MRFProperties/0\.U
  snippets). A project picker + "Create case" → /api/generate/create → toast + jump to Cases.
- api.ts: add generatePreview()/generateCreate(). Add the nav entry + route in App.tsx.

## Verify (local, by kartikey)
- `GEMINI_API_KEY=… uvicorn backend.main:app` + `npm run dev`; prompt → preview (3D + params) →
  Create → case appears in Cases → Submit → (optionally) a real Batch run to Results.
