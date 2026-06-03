FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements-backend.txt ./
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir -r requirements-backend.txt
COPY core ./core
COPY backend ./backend
ENV PORT=8080
CMD ["sh","-c","uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
