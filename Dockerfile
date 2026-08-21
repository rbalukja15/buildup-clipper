# --- stage 1: build the UI -------------------------------------------------
FROM node:22-alpine AS ui

WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY frontend/ ./
# Empty API base: in the packaged build FastAPI serves the UI from its own origin.
ENV NEXT_PUBLIC_API_BASE=""
RUN npm run build

# --- stage 2: runtime ------------------------------------------------------
FROM python:3.11-slim

# ffmpeg does the work; yt-dlp only matters for YouTube sources.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=ui /ui/out ./frontend

ENV BUC_DATA_DIR=/data \
    BUC_FRONTEND_DIR=/srv/frontend \
    PYTHONUNBUFFERED=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
