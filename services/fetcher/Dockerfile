
FROM python:3.12-slim-bookworm AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .

RUN pip install -r requirements.txt


FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
    
# fixed numeric uid: works with --read-only and Kubernetes-style runAsNonRoot checks
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

COPY --from=build /opt/venv /opt/venv

WORKDIR /app

COPY worker.py healthcheck.py ./

USER 10001

# no EXPOSE: the fetcher opens no port, it only talks to Redis
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "healthcheck.py"]
CMD ["python", "worker.py"]
