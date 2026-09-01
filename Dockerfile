FROM python:3.12-slim AS base

# Metadata
LABEL maintainer="polluxa-analytics"
LABEL description="Polluxa LinkedIn Agent Analytics Platform"

# Security: run as non-root
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY README.md pyproject.toml ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/
COPY data/ ./data/

# Create data directories and permissions
RUN mkdir -p /app/data/imports /app/logs && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Default command: run the pipeline
CMD ["python", "scripts/run_pipeline.py", "run"]


