#!/usr/bin/env bash
# M3 Task 10: first manual deploy of the backend to Cloud Run + IAP on cfd-lemnisca.
# Run as Owner. PREREQ: OAuth consent screen configured (Console > Google Auth
# Platform > Audience = Internal + Branding) — IAP won't work without it.
# After the first manual deploy, GitHub Actions (.github/workflows/deploy.yml) handles deploys.
set -uo pipefail

PROJECT_ID="cfd-lemnisca"
PROJECT_NUMBER="380489820300"
REGION="us-central1"
SERVICE="of-batch-app"
BACKEND_SA="of-batch-backend@${PROJECT_ID}.iam.gserviceaccount.com"
IAP_SA="service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"
IMAGE="us-central1-docker.pkg.dev/${PROJECT_ID}/openfoam/of-backend:0.1.0"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # = phase3-run-app

say(){ printf '\n=== %s ===\n' "$1"; }

say "1. Build + push backend image (amd64)"
docker buildx build --platform linux/amd64 -f "${REPO_ROOT}/backend/Dockerfile" \
  -t "${IMAGE}" --push "${REPO_ROOT}"

say "2. Deploy to Cloud Run as the backend SA, no public access"
gcloud run deploy "${SERVICE}" --image "${IMAGE}" --region "${REGION}" \
  --service-account "${BACKEND_SA}" --no-allow-unauthenticated --project "${PROJECT_ID}"

say "3. Enable IAP on the service"
gcloud beta run services update "${SERVICE}" --region "${REGION}" --iap --project "${PROJECT_ID}"

say "4. Let IAP invoke the service"
gcloud run services add-iam-policy-binding "${SERVICE}" --region "${REGION}" \
  --member="serviceAccount:${IAP_SA}" --role="roles/run.invoker" --project "${PROJECT_ID}"

say "5. Grant the whole org access via IAP"
gcloud beta iap web add-iam-policy-binding --resource-type=cloud-run --service="${SERVICE}" \
  --region="${REGION}" --member="domain:lemnisca.bio" \
  --role="roles/iap.httpsResourceAccessor" --project "${PROJECT_ID}"

say "6. MANUAL: set OF_IAP_AUDIENCE so the app can verify IAP JWTs"
cat <<EOF
The IAP JWT 'aud' for this service must be set as env OF_IAP_AUDIENCE on the service.
Find it: Console > Security > Identity-Aware Proxy > the of-batch-app row > (3-dot) >
  'Get JWT audience code', OR derive the backend-service audience. Then run:

  gcloud run services update ${SERVICE} --region ${REGION} \\
    --update-env-vars OF_IAP_AUDIENCE=<AUDIENCE> --project ${PROJECT_ID}

Until OF_IAP_AUDIENCE is set, the app rejects all /api calls (401) by design.
EOF

say "7. Verify"
URL="$(gcloud run services describe ${SERVICE} --region ${REGION} --project ${PROJECT_ID} --format='value(status.url)')"
echo "Service URL: ${URL}"
echo "Open it in a browser as a lemnisca.bio account -> IAP sign-in -> placeholder page."
echo "curl -s ${URL}/healthz without auth should be blocked by IAP (302/403)."
