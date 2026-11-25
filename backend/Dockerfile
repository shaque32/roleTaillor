# syntax=docker/dockerfile:1.7
# RoleTailor API and worker image. Build from the repository root:
#   docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# LibreOffice (headless Writer) converts DOCX to PDF for exports; Tesseract OCRs scanned PDF resumes.
# Carlito, Caladea and Liberation are metric-compatible stand-ins for Calibri, Cambria, Arial and
# Times when an in-place PDF edit needs a glyph the embedded font subset lacks (found via fc-match).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer-nogui fonts-dejavu-core fonts-liberation \
        fonts-crosextra-carlito fonts-crosextra-caladea fontconfig \
        tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 app && useradd --system --uid 1001 --gid app --create-home app

WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/roletailor backend/roletailor
RUN pip install ./backend
COPY config config
COPY db db
# Read access for the non-root user regardless of the host's file modes or umask.
RUN chmod -R a+rX /app

# The image is production unless told otherwise, so the config guard in
# roletailor/config.py is on by default. Local compose sets RT_ENVIRONMENT=dev in .env.
ENV RT_ENVIRONMENT=prod \
    RT_MODELS_CONFIG_PATH=/app/config/models.yaml \
    RT_STORAGE_LOCAL_DIR=/data/files \
    HOME=/home/app
RUN mkdir -p /data/files && chown -R app:app /data
USER app

EXPOSE 8000
# No --proxy-headers: X-Forwarded-For is client-controlled. The app reads the client
# address itself (see api/deps.py: client_ip).
CMD ["uvicorn", "roletailor.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
