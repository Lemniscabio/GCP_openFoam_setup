#!/usr/bin/env bash
# M2 setup for the dedicated CFD-pipeline project (cfd-lemnisca).
# Run as a user with OWNER on cfd-lemnisca. Idempotent-ish: re-running tolerates
# "already exists". Run whole (bash setup-cfd-lemnisca.sh) or section by section.
#
# NOT covered here (do these separately):
#   - OAuth consent screen: Console > Google Auth Platform > Audience = Internal,
#     Branding app name + support email. (No gcloud equivalent.)
#   - IAP ON the Cloud Run service + domain:lemnisca.bio -> roles/iap.httpsResourceAccessor
#     + IAP service agent roles/run.invoker  -> these are M3 (need the deployed service).
set -uo pipefail

PROJECT_ID="cfd-lemnisca"
PROJECT_NUMBER="380489820300"
REGION="us-central1"
BUCKET="cfd-lemnisca-cases"          # of-cases is globally taken by the old project
GH_REPO="Lemniscabio/GCP_openFoam_setup"
IMAGE="us-central1-docker.pkg.dev/${PROJECT_ID}/openfoam/openfoam:12.0.0"
BACKEND_SA="of-batch-backend@${PROJECT_ID}.iam.gserviceaccount.com"
JOB_SA="of-batch-job@${PROJECT_ID}.iam.gserviceaccount.com"
CI_SA="of-ci-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

say(){ printf '\n=== %s ===\n' "$1"; }

say "0. Pin project + sanity-check you have access"
gcloud config set project "${PROJECT_ID}"
gcloud projects get-iam-policy "${PROJECT_ID}" \
  --flatten="bindings[].members" \
  --filter="bindings.members:kartikey.attri@lemnisca.bio" \
  --format="table(bindings.role)"
echo ">> You should see roles/owner above. If not, have the project creator grant you Owner before continuing."

say "1. Enable APIs"
gcloud services enable \
  run.googleapis.com iap.googleapis.com iamcredentials.googleapis.com \
  storage.googleapis.com batch.googleapis.com compute.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  cloudresourcemanager.googleapis.com logging.googleapis.com \
  --project="${PROJECT_ID}"

say "2. Artifact Registry repo"
gcloud artifacts repositories create openfoam \
  --repository-format=docker --location="${REGION}" \
  --description="OpenFOAM Batch runtime images" \
  --project="${PROJECT_ID}" || echo "(repo may already exist — continuing)"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

say "3. Build (linux/amd64!) + push runtime image  [takes a few minutes]"
# MUST be amd64 — Mac default arm64 fails Batch image pull.
docker buildx build --platform linux/amd64 \
  -f "${REPO_ROOT}/openfoam-batch/Dockerfile" \
  -t "${IMAGE}" --push "${REPO_ROOT}/openfoam-batch"

say "4. Service accounts"
gcloud iam service-accounts create of-batch-backend \
  --display-name="OF Batch web backend (Cloud Run)" --project="${PROJECT_ID}" || echo "(exists)"
gcloud iam service-accounts create of-batch-job \
  --display-name="OF Batch job VM identity" --project="${PROJECT_ID}" || echo "(exists)"

say "5. IAM bindings (least privilege)"
# backend signs POST policies as itself
gcloud iam service-accounts add-iam-policy-binding "${BACKEND_SA}" \
  --member="serviceAccount:${BACKEND_SA}" \
  --role="roles/iam.serviceAccountTokenCreator" --project="${PROJECT_ID}"
# backend submits Batch jobs + acts as the job SA
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${BACKEND_SA}" --role="roles/batch.jobsEditor"
gcloud iam service-accounts add-iam-policy-binding "${JOB_SA}" \
  --member="serviceAccount:${BACKEND_SA}" \
  --role="roles/iam.serviceAccountUser" --project="${PROJECT_ID}"
# job SA: agent reporting + logs + pull image
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${JOB_SA}" --role="roles/batch.agentReporter"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${JOB_SA}" --role="roles/logging.logWriter"
gcloud artifacts repositories add-iam-policy-binding openfoam --location="${REGION}" \
  --member="serviceAccount:${JOB_SA}" --role="roles/artifactregistry.reader" \
  --project="${PROJECT_ID}"

say "6. Fresh bucket + lifecycle"
gcloud storage buckets create "gs://${BUCKET}" \
  --location="${REGION}" --uniform-bucket-level-access --project="${PROJECT_ID}" || echo "(exists)"
# bucket-scoped storage for both SAs
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${BACKEND_SA}" --role="roles/storage.objectAdmin"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${JOB_SA}" --role="roles/storage.objectAdmin"
# lifecycle: tier old inputs/results
cat > /tmp/of-lifecycle.json <<'JSON'
{ "rule": [
  { "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
    "condition": {"age": 60, "matchesPrefix": ["cases/"]} },
  { "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
    "condition": {"age": 180, "matchesPrefix": ["results/"]} }
]}
JSON
gcloud storage buckets update "gs://${BUCKET}" --lifecycle-file=/tmp/of-lifecycle.json

say "7. Workload Identity Federation (own pool — no shared github-pool here)"
gcloud iam workload-identity-pools create of-github-pool \
  --location=global --display-name="OF Batch GitHub Actions pool" \
  --project="${PROJECT_ID}" || echo "(exists)"
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global --workload-identity-pool=of-github-pool \
  --display-name="GitHub provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${GH_REPO}'" \
  --project="${PROJECT_ID}" || echo "(provider may exist — verify its condition with describe)"
gcloud iam service-accounts create of-ci-deployer \
  --display-name="GitHub Actions deployer" --project="${PROJECT_ID}" || echo "(exists)"
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CI_SA}" --role="${ROLE}"
done
gcloud iam service-accounts add-iam-policy-binding "${CI_SA}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/of-github-pool/attribute.repository/${GH_REPO}" \
  --project="${PROJECT_ID}"

say "DONE. Verify:"
echo "  gcloud iam service-accounts list --project=${PROJECT_ID} --filter='email:of-'"
echo "  gcloud artifacts docker tags list ${IMAGE%:*}"
echo "  gcloud iam workload-identity-pools providers describe github-provider --location=global --workload-identity-pool=of-github-pool --project=${PROJECT_ID} --format='value(attributeCondition)'"
echo "Still manual: OAuth consent (Audience=Internal) in Console; IAP-on-service + domain binding are M3."
