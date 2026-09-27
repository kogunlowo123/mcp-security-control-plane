# ---- Builder stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency manifest first for layer caching
COPY pyproject.toml ./

# Create a venv and install dependencies (no dev deps)
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache . --extra-index-url https://pypi.org/simple

# Copy source code
COPY src/ ./src/

# Install the package itself into the venv
RUN . /opt/venv/bin/activate && uv pip install --no-cache .

# ---- Runtime stage ----
FROM python:3.12-slim AS runtime

# Create non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy the populated venv from the builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY --from=builder /build/src ./src

# Make venv the active Python
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Drop privileges
USER appuser

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
