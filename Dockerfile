# Faultline — web surface.
#
# Note what this image can and cannot do. The engine is designed around local
# inference: four roles and every fallback run on Ollama, which is what makes a
# full run cost $0. There is no Ollama here, so a container is either
#
#   FAULTLINE_PUBLIC_DEMO=1   serves the UI and the recorded runs (no keys)
#   FAULTLINE_HOSTED_ONLY=1   live runs on hosted models only (needs keys,
#                             and screening volume will meet free-tier limits)
#
# For a real run with the design working as intended, clone and run locally
# with Ollama.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FAULTLINE_PUBLIC_DEMO=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source, the web surface, and the recorded runs the public demo replays.
COPY faultline/ ./faultline/
COPY web/ ./web/
COPY demo/ ./demo/
COPY server.py ./

# The store is created on first use; keep it on a writable path.
RUN mkdir -p data/uploads

EXPOSE 8000

# Hosts inject $PORT; fall back to 8000 for a plain `docker run`.
CMD ["sh", "-c", "python -m uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
