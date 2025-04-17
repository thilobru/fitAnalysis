# --- Stage 1: Builder ---
    FROM python:3.10-slim AS builder

    WORKDIR /opt/builder
    
    # Install build dependencies needed for psycopg and potentially other packages
    # libpq-dev provides PostgreSQL client development files
    RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        && rm -rf /var/lib/apt/lists/*
    
    # Copy requirements file
    COPY requirements.txt .
    
    # Install dependencies
    RUN pip wheel --no-cache-dir --wheel-dir=/opt/wheels -r requirements.txt \
        && pip install --no-cache-dir --no-index --find-links=/opt/wheels -r requirements.txt
    
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
        # Database URL will be set via docker-compose typically
        # FLASK_APP=app.py # Set if needed, gunicorn uses app:app syntax
        WORKERS=2 \
        TIMEOUT=180
    
    # Create a non-root user and group
    RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
    
    # Create the application directory and the mount point for FIT files
    RUN mkdir -p /app/fitfiles
    
    WORKDIR /app
    
    # Copy installed dependencies from the builder stage
    COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
    COPY --from=builder /usr/local/bin/gunicorn /usr/local/bin/gunicorn
    # Copy alembic if installed globally in builder (location might vary)
    # COPY --from=builder /usr/local/bin/alembic /usr/local/bin/alembic
    
    # Copy application code
    COPY app.py .
    COPY templates ./templates
    # Copy migrations directory if it exists (created by flask db init)
    COPY migrations ./migrations
    
    # Change ownership
    RUN chown -R appuser:appgroup /app
    
    # Switch to the non-root user
    USER appuser
    
    EXPOSE ${FIT_ANALYZER_PORT}
    
    # Use tini as entrypoint for better signal handling (optional but good)
    # RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*
    # ENTRYPOINT ["/usr/bin/tini", "--"]
    
    # Define the command to run migrations then the application
    # Note: Running migrations automatically on startup can be risky in production replicas.
    # Consider a separate migration job/script for production.
    # For development/simplicity:
    CMD ["sh", "-c", "flask db upgrade && gunicorn --workers $WORKERS --bind $FIT_ANALYZER_HOST:$FIT_ANALYZER_PORT --timeout $TIMEOUT app:app"]
    
    # Alternative CMD without auto-migration:
    # CMD ["gunicorn", "--workers", "$WORKERS", "--bind", "$FIT_ANALYZER_HOST:$FIT_ANALYZER_PORT", "--timeout", "$TIMEOUT", "app:app"]
    