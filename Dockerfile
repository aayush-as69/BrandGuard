FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 BRANDGUARD_ENV=production BRANDGUARD_DB=/data/brandguard.db BRANDGUARD_LOG_JSON=1 BRANDGUARD_TRUSTED_PROXIES=1
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt
COPY . .
RUN useradd -r -m -u 10001 app && mkdir /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'))"
# One worker per CPU is fine: SQLite uses a file lock and the app keeps no state in memory except rate limits.
# Hosts such as Render tell us the port in $PORT; default 8000.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 60 run:app"]
