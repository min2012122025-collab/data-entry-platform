FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && useradd --uid 10001 --create-home entry && mkdir -p /var/lib/data-entry/uploads /var/lib/data-entry/templates && chown -R entry:entry /var/lib/data-entry
COPY backend/app /app/backend/app
COPY database /app/database
COPY frontend/dist /app/frontend/dist
COPY run.sh /app/run.sh
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod 755 /app/run.sh /app/docker-entrypoint.sh
USER 10001:10001
EXPOSE 8125
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8125/api/health',timeout=3)"
ENTRYPOINT ["/app/docker-entrypoint.sh"]
