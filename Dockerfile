FROM python:3.13-slim AS runtime

ARG VCS_REF="unknown"
ARG VERSION="dev"

LABEL org.opencontainers.image.title="Ports" \
      org.opencontainers.image.description="A polished, read-only Docker port inventory and service launchpad" \
      org.opencontainers.image.source="https://github.com/palermostest25/ports" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt \
    && addgroup --system --gid 10001 ports \
    && adduser --system --uid 10001 --ingroup ports --home /nonexistent --no-create-home ports

COPY --chown=ports:ports app.py ./
COPY --chown=ports:ports templates ./templates
COPY --chown=ports:ports static ./static

USER 10001:10001
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=3)" || exit 1

CMD ["gunicorn", "--bind=0.0.0.0:5000", "--workers=2", "--threads=4", "--timeout=30", "--access-logfile=-", "--error-logfile=-", "app:app"]
