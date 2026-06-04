# --- stage 1: build the SPA ---
FROM node:20-slim AS fe
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_OAUTH_CLIENT_ID
ENV VITE_OAUTH_CLIENT_ID=$VITE_OAUTH_CLIENT_ID
RUN npm run build         # -> /fe/dist

# --- stage 2: backend serving the built SPA ---
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements-backend.txt ./
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir -r requirements-backend.txt
COPY core ./core
COPY backend ./backend
# built SPA replaces the placeholder
COPY --from=fe /fe/dist ./backend/static
ENV PORT=8080
CMD ["sh","-c","uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
