# SAO Co-Pilot — production container image
#
# Bootcamp ties:
#   - Xtra Topic 1 — "Deploying Prototype as a Containerized App"
#   - Topic 5.2  — Secure credentials (key passed via env at run time)
#   - Topic 6.2  — pip + venv (we use system pip inside the image; no venv
#                  needed since the container itself is the isolation)
#
# Build:
#   docker build -t sao-co-pilot:latest .
#
# Run (local):
#   docker run -p 8501:8501 --env-file .env sao-co-pilot:latest
#
# Run (production, with explicit secret):
#   docker run -p 8501:8501 \
#       -e OPENAI_API_KEY="sk-proj-..." \
#       -e APP_PASSWORD="..." \
#       sao-co-pilot:latest

# ---------------------------------------------------------------------------
# Base image — Python 3.11 slim. ~120 MB before any pip installs.
# ---------------------------------------------------------------------------
FROM python:3.11-slim

# Don't write .pyc files; flush stdout/stderr in real time.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---------------------------------------------------------------------------
# Python dependencies — install BEFORE copying source, so this layer is
# cached when only application code changes.
# ---------------------------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Application source + pre-built corpus.
# .dockerignore filters out .venv, .env, samples/, etc.
# ---------------------------------------------------------------------------
COPY . .

# ---------------------------------------------------------------------------
# Streamlit configuration — must listen on 0.0.0.0 to be reachable from
# outside the container. Disable telemetry by default.
# ---------------------------------------------------------------------------
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHERUSAGESTATS=false

EXPOSE 8501

# ---------------------------------------------------------------------------
# Healthcheck — Streamlit exposes /_stcore/health for orchestrators
# (Kubernetes / CStack / Docker Swarm). Uses Python so we don't need curl
# in the slim image.
# ---------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request as r, sys; sys.exit(0 if r.urlopen('http://localhost:8501/_stcore/health').getcode() == 200 else 1)" \
  || exit 1

# ---------------------------------------------------------------------------
# Default command — same as we'd run locally.
# ---------------------------------------------------------------------------
CMD ["streamlit", "run", "app.py"]
