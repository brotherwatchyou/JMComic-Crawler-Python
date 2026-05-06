FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy source and install
COPY . .
RUN pip install --no-cache-dir ".[web]"

# Data & download directories
ENV JM_DATA_DIR=/data
ENV JM_DOWNLOAD_DIR=/downloads

VOLUME ["/data", "/downloads"]

EXPOSE 9801

# Default config if none provided
ENV JM_OPTION_PATH=/app/assets/option/option_docker.yml

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:9801/ || exit 1

CMD ["python", "-c", "\
from jmcomic import create_option_by_file; \
from jmcomic.jm_plugin import JmWebUIPlugin; \
import os, time; \
path = os.environ.get('JM_OPTION_PATH', '/app/assets/option/option_docker.yml'); \
option = create_option_by_file(path); \
plugin = JmWebUIPlugin.build(option); \
plugin.invoke(host='0.0.0.0', port=9801, debug=False); \
while plugin.running: time.sleep(1)"]
