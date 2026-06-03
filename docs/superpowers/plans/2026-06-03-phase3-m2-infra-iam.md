# Phase 3 — M2: Infra / IAM / IAP / WIF / Artifact Registry — Setup Runbook

> **Execution model:** This is a GCP **setup runbook**, not autonomous-Codex code. Steps are run by a human in a terminal (`gcloud`), because they hit real GCP and several need **Owner**. The orchestrator (Claude) runs the **read-only verification** after each task. Steps use checkbox (`- [ ]`) syntax.
>
> **Reference spec:** `docs/superpowers/specs/2026-06-01-phase3-run-app-design.md` (§5, §8).

**Goal:** Stand up the GCP foundation the web app needs — APIs, a private Artifact Registry image, two least-privilege service accounts with bucket-scoped IAM, the IAP prerequisites, a GitHub→GCP Workload Identity Federation path for CI, and a GCS lifecycle rule — all namespaced `of-…` so BioHermes is untouched.

**Constants (this project):**
- `PROJECT_ID = project-688a4c78-5d5b-45b3-b5d`
- `PROJECT_NUMBER = 746208330214`
- `REGION = us-central1`
- `BUCKET = of-cases`
- Backend SA = `of-batch-backend@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com`
- Job SA = `of-batch-job@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com`
- AR image (target) = `us-central1-docker.pkg.dev/project-688a4c78-5d5b-45b3-b5d/openfoam/openfoam:12.0.0`

**You must supply two values before starting** (write them here):
- `GH_OWNER/GH_REPO` = `Lemniscabio/GCP_openFoam_setup`  (the GitHub repo that will deploy via Actions; case-sensitive)
- App access = **all of `lemnisca.bio`** (decided 2026-06-03) → M3 binds `domain:lemnisca.bio` to IAP; no group needed.

**What is NOT in M2 (deferred to M3, because it needs the deployed Cloud Run service):**
- Enabling IAP *on the service*, granting the IAP service agent `roles/run.invoker`, and granting `domain:lemnisca.bio` → `roles/iap.httpsResourceAccessor` on the resource. M2 only does the IAP *prerequisites* (API + OAuth consent; access policy decided = whole org).

---

### Task 0: Refresh auth (kartikey)

- [ ] **Step 1:** Re-auth both CLI and ADC (interactive — run with `!` prefix in the session):
```
! gcloud auth login
! gcloud auth application-default login
```
- [ ] **Step 2:** Pin project + verify:
```bash
gcloud config set project project-688a4c78-5d5b-45b3-b5d
gcloud config get-value project
```
Expected: `project-688a4c78-5d5b-45b3-b5d`.

---

### Task 1: Grant kartikey the admin roles (pushkar / Owner — one-time)

`roles/editor` (kartikey's current level) **cannot** set IAM policy, configure IAP, or create WIF. pushkar grants the two project-level admin roles once (Step 1). After that, because `projectIamAdmin` includes project-level `setIamPolicy`, **kartikey can self-grant the remaining resource-admin roles** (Step 1b) — no further pushkar round-trip.

**Permission nuance that bites in Task 5:** `projectIamAdmin` only authorizes **project-level** bindings. Binding a role *on a resource* — the SA itself (Token Creator), a bucket, an AR repo — needs that resource's `setIamPolicy`, which lives in `roles/iam.serviceAccountAdmin`, `roles/storage.admin`, and `roles/artifactregistry.admin` respectively. Without them Task 5 Steps 1, 4, 5 fail with `PERMISSION_DENIED: ...setIamPolicy`.

- [ ] **Step 1 (pushkar runs — one-time):**
```bash
gcloud projects add-iam-policy-binding project-688a4c78-5d5b-45b3-b5d \
  --member="user:kartikey.attri@lemnisca.bio" --role="roles/resourcemanager.projectIamAdmin"
gcloud projects add-iam-policy-binding project-688a4c78-5d5b-45b3-b5d \
  --member="user:kartikey.attri@lemnisca.bio" --role="roles/iap.admin"
```
- [ ] **Step 1b (kartikey self-grants — works via projectIamAdmin):**
```bash
for ROLE in roles/iam.serviceAccountAdmin roles/storage.admin \
            roles/artifactregistry.admin roles/iam.workloadIdentityPoolAdmin; do
  gcloud projects add-iam-policy-binding project-688a4c78-5d5b-45b3-b5d \
    --member="user:kartikey.attri@lemnisca.bio" --role="$ROLE"
done
```
(These are broad standing roles; trim later if you want tighter long-term hygiene. `workloadIdentityPoolAdmin` is needed for Task 7; the other three for Task 5.)
- [ ] **Step 2 (verify, kartikey):**
```bash
gcloud projects get-iam-policy project-688a4c78-5d5b-45b3-b5d \
  --flatten="bindings[].members" \
  --filter="bindings.members:kartikey.attri@lemnisca.bio" \
  --format="table(bindings.role)"
```
Expected: includes `roles/resourcemanager.projectIamAdmin` and `roles/iap.admin` (plus existing roles).

---

### Task 2: Enable required APIs (kartikey)

- [ ] **Step 1:**
```bash
gcloud services enable \
  run.googleapis.com iap.googleapis.com iamcredentials.googleapis.com \
  storage.googleapis.com batch.googleapis.com compute.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  cloudresourcemanager.googleapis.com logging.googleapis.com \
  --project=project-688a4c78-5d5b-45b3-b5d
```
- [ ] **Step 2 (verify):**
```bash
gcloud services list --enabled --project=project-688a4c78-5d5b-45b3-b5d \
  --filter="config.name:(run iap iamcredentials batch artifactregistry)" \
  --format="value(config.name)"
```
Expected: all of `run`, `iap`, `iamcredentials`, `batch`, `artifactregistry` listed.

---

### Task 3: Artifact Registry repo + migrate the image (kartikey)

Move off personal Docker Hub to a private, IAM-gated in-project registry.

- [ ] **Step 1: Create the repo**
```bash
gcloud artifacts repositories create openfoam \
  --repository-format=docker --location=us-central1 \
  --description="OpenFOAM Batch runtime images" \
  --project=project-688a4c78-5d5b-45b3-b5d
```
- [ ] **Step 2: Configure docker auth to AR**
```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
```
- [ ] **Step 3: Build (amd64!) and push to AR**

⚠️ Must be `linux/amd64` — building on the Apple Silicon Mac defaults to arm64, which Batch rejects (see the `case_0001` failure). Use buildx:
```bash
cd /Users/kartikey/Desktop/work_products/NEW_GCP_OF_SCRIPTS
docker buildx build --platform linux/amd64 \
  -f openfoam-batch/Dockerfile \
  -t us-central1-docker.pkg.dev/project-688a4c78-5d5b-45b3-b5d/openfoam/openfoam:12.0.0 \
  --push openfoam-batch
```
- [ ] **Step 4: Update `core/config.py` default to the AR ref**

Change the `image_uri` default from `docker.io/kartikeyattri/openfoam:12.0.0` to
`us-central1-docker.pkg.dev/project-688a4c78-5d5b-45b3-b5d/openfoam/openfoam:12.0.0`, and update the assertion in `phase3-run-app/tests/test_config.py` (`"/openfoam:12" in s.image_uri` still holds; keep `endswith(":12.0.0")`). Run `cd phase3-run-app && .venv/bin/pytest -q` (expect 35 passed) and commit.
- [ ] **Step 5 (verify):**
```bash
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/project-688a4c78-5d5b-45b3-b5d/openfoam \
  --format="table(IMAGE,TAGS)"
```
Expected: `openfoam` image with tag `12.0.0`.

---

### Task 4: Create the two service accounts (kartikey)

- [ ] **Step 1:**
```bash
gcloud iam service-accounts create of-batch-backend \
  --display-name="OF Batch web backend (Cloud Run)" \
  --project=project-688a4c78-5d5b-45b3-b5d
gcloud iam service-accounts create of-batch-job \
  --display-name="OF Batch job VM identity" \
  --project=project-688a4c78-5d5b-45b3-b5d
```
- [ ] **Step 2 (verify):**
```bash
gcloud iam service-accounts list --project=project-688a4c78-5d5b-45b3-b5d \
  --filter="email:of-batch-" --format="value(email)"
```
Expected: both `of-batch-backend@…` and `of-batch-job@…`.

---

### Task 5: IAM bindings — least privilege (kartikey, needs projectIamAdmin from Task 1)

- [ ] **Step 1: Backend SA — sign POST policies via signBlob (Token Creator on ITSELF)**
```bash
gcloud iam service-accounts add-iam-policy-binding \
  of-batch-backend@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com \
  --member="serviceAccount:of-batch-backend@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project=project-688a4c78-5d5b-45b3-b5d
```
- [ ] **Step 2: Backend SA — submit Batch jobs + act as the job SA**
```bash
gcloud projects add-iam-policy-binding project-688a4c78-5d5b-45b3-b5d \
  --member="serviceAccount:of-batch-backend@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com" \
  --role="roles/batch.jobsEditor"
gcloud iam service-accounts add-iam-policy-binding \
  of-batch-job@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com \
  --member="serviceAccount:of-batch-backend@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser" \
  --project=project-688a4c78-5d5b-45b3-b5d
```
- [ ] **Step 3: Job SA — Batch agent reporting + logging**
```bash
gcloud projects add-iam-policy-binding project-688a4c78-5d5b-45b3-b5d \
  --member="serviceAccount:of-batch-job@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com" \
  --role="roles/batch.agentReporter"
gcloud projects add-iam-policy-binding project-688a4c78-5d5b-45b3-b5d \
  --member="serviceAccount:of-batch-job@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"
```
- [ ] **Step 4: Both SAs — bucket-scoped storage (NOT project-wide)**
```bash
gcloud storage buckets add-iam-policy-binding gs://of-cases \
  --member="serviceAccount:of-batch-backend@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
gcloud storage buckets add-iam-policy-binding gs://of-cases \
  --member="serviceAccount:of-batch-job@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```
- [ ] **Step 5: Job SA — pull from Artifact Registry**
```bash
gcloud artifacts repositories add-iam-policy-binding openfoam --location=us-central1 \
  --member="serviceAccount:of-batch-job@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader" \
  --project=project-688a4c78-5d5b-45b3-b5d
```
- [ ] **Step 6 (verify):**
```bash
gcloud projects get-iam-policy project-688a4c78-5d5b-45b3-b5d \
  --flatten="bindings[].members" \
  --filter="bindings.members:(of-batch-backend OR of-batch-job)" \
  --format="table(bindings.role, bindings.members)"
gcloud storage buckets get-iam-policy gs://of-cases --format=json | grep -A2 of-batch
```
Expected: backend has `batch.jobsEditor`; job has `batch.agentReporter`+`logging.logWriter`; both have `storage.objectAdmin` on the bucket.

---

### Task 6: IAP prerequisites — OAuth consent + access group (kartikey + Workspace admin)

- [ ] **Step 1: Configure the consent screen (new "Google Auth Platform" UI).** In the Console under **Google Auth Platform**: **Audience** → set **User type = Internal** (restricts sign-in to the `lemnisca.bio` org); **Branding** → set app name "OpenFOAM Batch" + support email. **Do NOT create an OAuth client** under "Clients" — IAP auto-creates its own Google-managed OAuth client when enabled on the Cloud Run service in M3. *(No clean gcloud equivalent; do it in Console.)*
- [ ] **Step 2: No access group needed — access = the whole org.** Decision (2026-06-03): any `lemnisca.bio` user may use the app. So instead of a group/individual list, M3 binds `domain:lemnisca.bio` → `roles/iap.httpsResourceAccessor` on the IAP resource. With Audience=Internal already set, this admits all org accounts and excludes everyone else. Nothing to create here.

> The service-level IAP toggle + the `domain:lemnisca.bio` → `roles/iap.httpsResourceAccessor` binding are done in **M3** once the Cloud Run service exists.

---

### Task 7: Workload Identity Federation for GitHub Actions (kartikey, needs Task 1)

Keyless GitHub→GCP auth for CI deploys. One-time; the finicky parts are the attribute condition and the `principalSet` string.

- [ ] **Step 1: Create the pool**
```bash
gcloud iam workload-identity-pools create github-pool \
  --location=global --display-name="GitHub Actions pool" \
  --project=project-688a4c78-5d5b-45b3-b5d
```
- [ ] **Step 2: Create the GitHub OIDC provider (locked to your repo)**

Replace `Lemniscabio/https://github.com/Lemniscabio/GCP_openFoam_setup` with your actual repo:
```bash
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global --workload-identity-pool=github-pool \
  --display-name="GitHub provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='Lemniscabio/GCP_openFoam_setup'" \
  --project=project-688a4c78-5d5b-45b3-b5d
```
- [ ] **Step 3: Create the deploy SA + its deploy roles**
```bash
gcloud iam service-accounts create of-ci-deployer \
  --display-name="GitHub Actions deployer" --project=project-688a4c78-5d5b-45b3-b5d
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding project-688a4c78-5d5b-45b3-b5d \
    --member="serviceAccount:of-ci-deployer@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com" \
    --role="$ROLE"
done
```
- [ ] **Step 4: Let the repo's WIF identity impersonate the deploy SA**

Replace `Lemniscabio/https://github.com/Lemniscabio/GCP_openFoam_setup`:
```bash
gcloud iam service-accounts add-iam-policy-binding \
  of-ci-deployer@project-688a4c78-5d5b-45b3-b5d.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/746208330214/locations/global/workloadIdentityPools/github-pool/attribute.repository/Lemniscabio/GCP_openFoam_setup" \
  --project=project-688a4c78-5d5b-45b3-b5d
```
- [ ] **Step 5 (verify):**
```bash
gcloud iam workload-identity-pools providers describe github-provider \
  --location=global --workload-identity-pool=github-pool \
  --project=project-688a4c78-5d5b-45b3-b5d --format="value(attributeCondition)"
```
Expected: prints `assertion.repository=='GH_OWNER/GH_REPO'`. (The GitHub Actions workflow YAML that consumes this is written in M3's CI task — it uses provider resource `projects/746208330214/locations/global/workloadIdentityPools/github-pool/providers/github-provider` and SA `of-ci-deployer@…`.)

---

### Task 8: GCS lifecycle rule on of-cases (kartikey, optional but recommended)

Untarred input trees cost a bit more; auto-tier old objects.

- [ ] **Step 1:** Write `infra/of-cases-lifecycle.json`:
```json
{ "rule": [
  { "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
    "condition": {"age": 60, "matchesPrefix": ["cases/"]} },
  { "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
    "condition": {"age": 180, "matchesPrefix": ["results/"]} }
]}
```
- [ ] **Step 2:** Apply + verify:
```bash
gcloud storage buckets update gs://of-cases --lifecycle-file=infra/of-cases-lifecycle.json
gcloud storage buckets describe gs://of-cases --format="value(lifecycle)"
```
Expected: the two rules are shown.

---

## Verification summary (orchestrator runs read-only)

After the human steps, Claude confirms via SDK/gcloud read-only: APIs enabled (Task 2), AR image present (3), both SAs exist (4), IAM bindings correct + bucket-scoped (5), WIF provider condition set (7), lifecycle applied (8). Anything missing → back to that task.

## Hand-off to M3
With M2 done, M3 (backend) can: deploy the FastAPI service to Cloud Run **as `of-batch-backend@`** pulling the AR image, then **enable IAP on the service**, grant the IAP service agent `roles/run.invoker`, and grant `ACCESS_GROUP` → `roles/iap.httpsResourceAccessor`. The CI task in M3 wires the GitHub Actions workflow to the WIF provider from Task 7.

## What needs whom
- **pushkar (Owner):** Task 1 only (grant kartikey the two admin roles). Everything else is kartikey.
- **Workspace admin:** Task 6 Step 2 (create the Google Group), if kartikey can't.
- **kartikey:** Tasks 0, 2–5, 6 (Step 1), 7, 8.
