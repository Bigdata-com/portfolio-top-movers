# Build stage with uv for fast dependency installation
FROM python:3.11-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files (README.md needed for hatchling build)
COPY pyproject.toml README.md ./

# Install dependencies using uv (creates .venv)
RUN uv venv && uv pip install --no-cache .

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY . .

# Create data and output directories
RUN mkdir -p /app/data /app/output

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8000
ENV DB_STRING=sqlite:///data/jobs.db

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "main.py"]
