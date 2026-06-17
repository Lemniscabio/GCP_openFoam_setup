# --- stage 1: build the SPA ---
FROM node:20-slim AS fe
WORKDIR /fe
COPY phase3-run-app/frontend/package.json phase3-run-app/frontend/package-lock.json ./
RUN npm ci
COPY phase3-run-app/frontend/ ./
ARG VITE_OAUTH_CLIENT_ID
ENV VITE_OAUTH_CLIENT_ID=$VITE_OAUTH_CLIENT_ID
RUN npm run build         # -> /fe/dist

# --- stage 2: backend serving the built SPA ---
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libxrender1 libsm6 libxext6 \
    && rm -rf /var/lib/apt/lists/*
COPY phase3-run-app/pyproject.toml phase3-run-app/requirements-backend.txt ./
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir -r requirements-backend.txt
# Part A/B geometry+case generator package (pulls cadquery, trimesh, google-genai)
COPY part-a-cad ./part-a-cad
RUN pip install --no-cache-dir ./part-a-cad
COPY phase3-run-app/core ./core
COPY phase3-run-app/backend ./backend
# built SPA replaces the placeholder
COPY --from=fe /fe/dist ./backend/static
ENV PORT=8080
CMD ["sh","-c","uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
