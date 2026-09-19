# Multi-stage build for optimized Docker image
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt ./

# Install Python dependencies in a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy package files and install
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder (includes installed package)
COPY --from=builder /opt/venv /opt/venv

# Set environment variables
# HOST/PORT are defaults, not hardcodes: `docker run -e PORT=4000`, a compose
# `environment:` entry, or an Unraid variable all override them. The app falls
# back to these when nothing is supplied.
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=3000 \
    CACHE_DIR=/root/.cache/csm-dashboard

# Health check (shell form so $PORT is expanded at runtime)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:$PORT/api/health || exit 1

# Expose the default port. EXPOSE is metadata only and cannot be dynamic — it
# documents the default and does not restrict what the app actually binds.
EXPOSE 3000

# Default command - csm is now an entry point from pip install.
# Exec form keeps PID 1 as the Python process so it receives SIGTERM directly;
# host/port come from the HOST/PORT environment variables set above.
CMD ["csm", "serve"]
