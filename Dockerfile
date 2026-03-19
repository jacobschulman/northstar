FROM python:3.11-slim

# Install system deps for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright + Chromium (this handles all remaining system deps)
RUN playwright install chromium && playwright install-deps chromium

# App code
COPY scraper/ scraper/
COPY report/ report/
COPY app.py run.py ./

# Default config + data dirs (mount over these with volumes)
RUN mkdir -p /app/data /app/config
COPY config/ config/

EXPOSE 8501

# Streamlit config for headless server mode
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

# Healthcheck — Streamlit serves on 8501
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD wget -q --spider http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py"]
