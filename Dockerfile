# --- Stage 1: Builder ---
FROM python:3.10-slim AS builder

WORKDIR /opt/builder

# Install build dependencies needed for psycopg and potentially other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Use explicit destination paths for COPY
COPY requirements.txt /opt/builder/requirements.txt
COPY requirements-dev.txt /opt/builder/requirements-dev.txt

# Use explicit path in pip install
RUN pip install --no-cache-dir -r /opt/builder/requirements-dev.txt

# --- Stage 2: Final Application Image ---
FROM python:3.10-slim

# Install runtime dependencies for psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# ** CHANGE: Use separate ENV instructions **
ENV PYTHONUNBUFFERED=1
ENV FIT_ANALYZER_FIT_DIR=/app/fitfiles
ENV FIT_ANALYZER_HOST=0.0.0.0
ENV FIT_ANALYZER_PORT=5000
ENV WORKERS=2
ENV TIMEOUT=180
ENV FLASK_APP="app:create_app()" 
# Still useful for 'flask' commands

# Create a non-root user and group
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Create the application directory and the mount point for FIT files
RUN mkdir -p /app/fitfiles /app/migrations /app/templates /app/tests 
# Create base dirs

WORKDIR /app

# Copy installed dependencies from the builder stage
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
# Copy the executables installed by pip (including pytest)
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code (copy the whole 'app' package now)
COPY app ./app
# Copy migrations and run script
COPY migrations ./migrations
COPY run.py . 
# run.py is at the root
# Copy test directory
COPY tests ./tests

# Change ownership
RUN chown -R appuser:appgroup /app

# Switch to the non-root user
USER appuser

EXPOSE ${FIT_ANALYZER_PORT} 
# Still uses env var set above

# Use Shell form for CMD to allow environment variable substitution
# Using 'exec' ensures gunicorn replaces the shell process (becomes PID 1)
# Reads WORKERS, HOST, PORT, TIMEOUT from ENV vars set above
CMD exec gunicorn --workers $WORKERS --bind $FIT_ANALYZER_HOST:$FIT_ANALYZER_PORT --timeout $TIMEOUT run:app
