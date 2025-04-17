# --- Stage 1: Builder ---
# Use a specific Python version slim image as the base for building
FROM python:3.10-slim as builder

# Set working directory
WORKDIR /opt/builder

# Install build dependencies if necessary (e.g., gcc for some packages)
# RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install dependencies into a target directory
# Using --no-cache-dir and --prefix helps keep layers smaller and separates packages
# Note: Using --target or --prefix might require adjusting PYTHONPATH later
# Simpler alternative: Install normally, then copy site-packages in next stage
RUN pip wheel --no-cache-dir --wheel-dir=/opt/wheels -r requirements.txt \
    && pip install --no-cache-dir --no-index --find-links=/opt/wheels -r requirements.txt

# --- Stage 2: Final Application Image ---
# Use the same slim base image for the final stage
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    # Set default FIT directory path inside container
    FIT_ANALYZER_FIT_DIR=/app/fitfiles \
    # Set default host/port for Flask/Gunicorn (can be overridden)
    FIT_ANALYZER_HOST=0.0.0.0 \
    FIT_ANALYZER_PORT=5000 \
    # Gunicorn specific settings (can also be set via CMD)
    WORKERS=2 \
    # Timeout for Gunicorn (in seconds)
    TIMEOUT=180

# Create a non-root user and group
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Create the application directory and the mount point for FIT files
RUN mkdir -p /app/fitfiles

# Set the working directory
WORKDIR /app

# Copy installed dependencies from the builder stage
# This location might vary slightly depending on Python version/base image
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
# Copy Gunicorn executable (location might vary) - ensure it's found
COPY --from=builder /usr/local/bin/gunicorn /usr/local/bin/gunicorn

# Copy application code (app.py, templates/)
COPY app.py .
COPY templates ./templates

# Change ownership of the app directory and mount point to the non-root user
# Ensure the user can write logs if logging to files, or adjust permissions
RUN chown -R appuser:appgroup /app

# Switch to the non-root user
USER appuser

# Expose the port the app runs on
EXPOSE ${FIT_ANALYZER_PORT}

# Define the command to run the application using Gunicorn
# Reads host/port/workers from environment variables set above
CMD ["gunicorn", "--workers", "$WORKERS", "--bind", "$FIT_ANALYZER_HOST:$FIT_ANALYZER_PORT", "app:app"]
