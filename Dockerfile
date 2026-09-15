# Dockerfile for Skills MCP Server
# Supports both STDIO and HTTP transports

FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 mcpuser

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY profiles/ ./profiles/
COPY config.json ./config.json.example

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create directory for skills (will be mounted or synced)
RUN mkdir -p /skills && chown mcpuser:mcpuser /skills

# Switch to non-root user
USER mcpuser

# Expose port for HTTP mode
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default environment variables
ENV SKILL_ROOT=/skills
ENV PROFILE_DIR=/app/profiles
ENV TRANSPORT=http
ENV HOST=0.0.0.0
ENV PORT=8000
ENV LOG_LEVEL=INFO
ENV AUTH_TOKEN=

# Entry point
ENTRYPOINT ["python", "-m", "src.http_server"]
CMD ["--host", "0.0.0.0", "--port", "8000"]