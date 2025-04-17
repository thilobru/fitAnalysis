# --- Stage 1: Builder ---
    FROM python:3.10-slim AS builder

    WORKDIR /opt/builder
    
    # Install build dependencies needed for psycopg and potentially other packages
    RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        && rm -rf /var/lib/apt/lists/*
    
    # Copy requirements file
    COPY requirements.txt .
    
    # Install dependencies
    RUN pip install --no-cache-dir -r requirements.txt
    
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
    # Copy the executables installed by pip
    COPY --from=builder /usr/local/bin /usr/local/bin
    
    # *** DIAGNOSTIC STEP: Check if psycopg was copied ***
    RUN echo "Checking for psycopg in final stage site-packages:" && \
        ls -l /usr/local/lib/python3.10/site-packages/psycopg* || echo "psycopg* not found!"
    
    # Copy application code (app.py, templates/)
    COPY app.py .
    COPY templates ./templates
    # Copy migrations directory if it exists (created by flask db init)
    COPY migrations ./migrations
    
    # Change ownership
    RUN chown -R appuser:appgroup /app
    
    # Switch to the non-root user
    USER appuser
    
    EXPOSE ${FIT_ANALYZER_PORT}
    
    # Define the command to run migrations then the application
    CMD ["sh", "-c", "flask db upgrade && gunicorn --workers $WORKERS --bind $FIT_ANALYZER_HOST:$FIT_ANALYZER_PORT --timeout $TIMEOUT app:app"]
    
    # Alternative CMD without auto-migration:
    # CMD ["gunicorn", "--workers", "$WORKERS", "--bind", "$FIT_ANALYZER_HOST:$FIT_ANALYZER_PORT", "--timeout", "$TIMEOUT", "app:app"]
    