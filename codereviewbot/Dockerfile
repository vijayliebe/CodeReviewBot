FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy configuration and setup files
COPY pyproject.toml /app/
COPY README.md /app/

# Install python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy source code
COPY src/ /app/src/
COPY .agents/ /app/.agents/

# Set Python path to /app
ENV PYTHONPATH=/app

# Default command
ENTRYPOINT ["codereviewbot"]
CMD ["--help"]
