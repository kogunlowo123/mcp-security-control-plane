# Build stage — install dependencies into a virtual environment
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build tools required by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency manifest first for Docker layer caching
COPY pyproject.toml .
COPY src/ src/

# Create virtual environment and install all dependencies
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache .

# Runtime stage — minimal image with only what's needed to run
FROM python:3.12-slim AS runtime

WORKDIR /app

# Create non-root service user and group
RUN groupadd --system --gid 1001 ragcore && \
    useradd --system --uid 1001 --gid ragcore --no-create-home --shell /sbin/nologin ragcore

# Install only runtime shared libraries (no headers or build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY --chown=ragcore:ragcore src/ src/

# Environment setup
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Health probe: ensure the package imports cleanly
RUN python -c "import rag_core"

# Drop to non-root user
USER ragcore

# Default entrypoint — override in Kubernetes manifests
CMD ["python", "-m", "rag_core"]
