#!/bin/bash
# Local dev backend for the Generate (Parts A+B) integration.
#   - loads GEMINI_API_KEY from .env.local (gitignored)
#   - OF_DEV_NO_IAP=1 bypasses Google sign-in (returns a dev runner)
#   - serves on :8000 so the Vite dev server (:8080) can proxy /api to it
# Frontend:  cd frontend && VITE_API_TARGET=http://localhost:8000 npm run dev
set -e
cd "$(dirname "$0")"

if [ -f .env.local ]; then
  set -a; . ./.env.local; set +a
fi

if [ -z "$GEMINI_API_KEY" ]; then
  echo "WARNING: GEMINI_API_KEY is empty — prompt extraction will 400. Paste it into .env.local." >&2
fi

export OF_DEV_NO_IAP=1
# Use the CURRENT project-aware runtime (deploy.yml pins this). config.py's default is the
# stale pre-projects 12.0.1, which downloads cases/<id>/ WITHOUT the project segment and fails.
export OF_IMAGE_URI="${OF_IMAGE_URI:-us-central1-docker.pkg.dev/cfd-lemnisca/openfoam/openfoam:12.0.5}"
# Pin the GCP project for the Storage/Firestore clients so this app always targets cfd-lemnisca,
# regardless of `gcloud config`/ADC quota project (which you may switch for other work).
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-cfd-lemnisca}"
export PYTHONPATH=.
echo "Backend (dev, no-auth) on http://localhost:8000  — Gemini key: $([ -n "$GEMINI_API_KEY" ] && echo set || echo MISSING)"
exec .venv312/bin/uvicorn backend.main:app --port 8000 --reload
