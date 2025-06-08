FROM python:3.11-slim

# Set up environment
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    PYTHONPATH=/app/src

# Install dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        gcc \
        libpq-dev \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy source code and requirements
COPY pyproject.toml README.md ./
COPY src/ /app/src/

# Install the package
RUN pip install --no-cache-dir -e .

# Copy config example
COPY config.yaml.example /app/config.yaml

# Create user
RUN addgroup --system monitor && adduser --system --group monitor
RUN chown -R monitor:monitor /app
USER monitor

# Set entrypoint
ENTRYPOINT ["python", "-m", "server_monitor.cli"]
CMD ["start", "/app/config.yaml", "--health-port", "8081"]

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8081/health || exit 1
