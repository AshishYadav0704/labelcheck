# LabelCheck: one container serves the API and the web app.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Tesseract = offline label reading when no AI key is set (or the AI service is down).
# DejaVu fonts are used to draw the long-term video frames.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/app backend/app
COPY web web

RUN useradd --create-home --uid 10001 labelcheck \
 && mkdir -p /data \
 && chown -R labelcheck:labelcheck /data
USER labelcheck

ENV APP_ENV=production \
    DATA_DIR=/data \
    WEB_DIR=/app/web \
    PORT=8000
WORKDIR /app/backend
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/v1/health', timeout=4).status == 200 else 1)"

# One worker: the rate limiter, SQLite database and video render locks live in this
# process. Requests run concurrently on its thread pool. See README > Scaling.
# The app logs every API request itself (with request ID and timing), so uvicorn's access log is off.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 15 --no-server-header --no-access-log"]
