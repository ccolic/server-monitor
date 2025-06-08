# Stage 1: Builder
FROM python:3.11-slim AS builder

# Set up environment
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    PYTHONPATH=${PYTHONPATH}:/app

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy only requirements first, to leverage Docker caching
COPY pyproject.toml ./

# Install dependencies
RUN pip install --no-cache-dir -e .

# Stage 2: Final Image
FROM python:3.11-alpine

# Set up environment
ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONPATH=${PYTHONPATH}:/app

# Install runtime dependencies
RUN apk add --no-cache \
        ca-certificates \
        libpq \
        curl

# Set up working directory
WORKDIR /app

# Copy compiled dependencies from builder stage
COPY --from=builder /app /app

# Copy source code
COPY src/ /app/src/

# Copy config example
COPY config.yaml.example /app/config.yaml

# Create user
RUN addgroup -S monitor && adduser -S monitor -G monitor
RUN chown -R monitor:monitor /app
USER monitor

# Set entrypoint
ENTRYPOINT ["python", "-m", "server_monitor.cli"]
CMD ["start", "/app/config.yaml"]

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1
