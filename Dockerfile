# --- Stage 1: Builder ---
    FROM python:3.10-slim AS builder

    WORKDIR /opt/builder
    
    # Install build dependencies needed for psycopg and potentially other packages
    RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        && rm -rf /var/lib/apt/lists/*
    
    # Copy requirements files
    COPY requirements.txt .
    COPY requirements-dev.txt .
    
    # Install dependencies using requirements-dev.txt
    RUN pip install --no-cache-dir -r requirements-dev.txt
    
    # --- Stage 2: Final Application Image ---
    FROM python:3.10-slim
    
    # Install runtime dependencies for psycopg
    RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        && rm -rf /var/lib/apt/lists/*
    
    # Set environment variables
    ENV PYTHONUNBUFFERED=1 \
        FIT_ANALYZER_FIT_DIR=/app/fitfiles \
        FIT_ANALYZER_HOST=0.0.0.0 \
        FIT_ANALYZER_PORT=5000 \
        WORKERS=2 \
        TIMEOUT=180
    
    # Create a non-root user and group
    RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
    
    # Create the application directory and the mount point for FIT files
    RUN mkdir -p /app/fitfiles
    
    WORKDIR /app
    
    # Copy installed dependencies from the builder stage
    COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
    # Copy the executables installed by pip (including pytest)
    COPY --from=builder /usr/local/bin /usr/local/bin
    
    # Copy application code (app.py, templates/)
    COPY app.py .
    COPY templates ./templates
    # Copy migrations directory (ensure flask db init was run locally first!)
    COPY migrations ./migrations
    # Copy test directory (optional, but needed if running tests from within final image)
    COPY tests ./tests
    
    # Change ownership
    RUN chown -R appuser:appgroup /app
    
    # Switch to the non-root user
    USER appuser
    
    EXPOSE ${FIT_ANALYZER_PORT}
    
    # ** CHANGE: Use Shell form for CMD to allow environment variable substitution **
    # Using 'exec' ensures gunicorn replaces the shell process (becomes PID 1)
    CMD exec gunicorn --workers $WORKERS --bind $FIT_ANALYZER_HOST:$FIT_ANALYZER_PORT --timeout $TIMEOUT app:app
    
    # Alternative shell form (without explicit 'exec'):
    # CMD gunicorn --workers $WORKERS --bind $FIT_ANALYZER_HOST:$FIT_ANALYZER_PORT --timeout $TIMEOUT app:app
    