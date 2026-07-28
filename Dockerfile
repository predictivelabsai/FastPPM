FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal — pure-Python stack (FastHTML + SQLAlchemy + Plotly).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistent volume for the SQLite db + uploads.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 5012

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5012/health').read()"

CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "5012"]
