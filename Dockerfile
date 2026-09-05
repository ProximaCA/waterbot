FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/certs/russian_trusted_root_ca.pem /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
COPY deploy/certs/russian_trusted_sub_ca.pem /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt
RUN update-ca-certificates

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /data && useradd --system --uid 1000 wm \
    && chown -R wm:wm /app /data
USER wm

EXPOSE 8010
CMD ["python", "-m", "app.main"]
