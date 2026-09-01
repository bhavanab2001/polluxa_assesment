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

# Install Python dependencies (pinned via pyproject.toml)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy application code
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Create data directories
RUN mkdir -p /app/data/imports /app/logs && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "from src.config import settings; print('healthy')" || exit 1

# Default command: run the pipeline
ENTRYPOINT ["python", "-m", "scripts.run_pipeline"]
CMD ["run"]
