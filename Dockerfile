# Use an official Python runtime as a parent image
# Using a specific version and the 'slim' variant reduces image size
FROM python:3.10-slim

# Set environment variables
# Prevents Python from buffering stdout and stderr (good for logs)
ENV PYTHONUNBUFFERED=1
# Set the Flask application entry point (though Gunicorn overrides this)
# ENV FLASK_APP=app.py
# Set the working directory in the container
WORKDIR /app

# Install system dependencies that might be needed by pandas or other libraries
# (Example: build-essential might be needed for some packages)
# Adjust as necessary based on runtime errors
# RUN apt-get update && apt-get install -y --no-install-recommends \
#    build-essential \
#    && rm -rf /var/lib/apt/lists/*

# Copy just the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
# --no-cache-dir reduces image size by not storing the pip cache
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
# This includes app.py and the templates/ directory
COPY . .

# Create the directory for FIT files mount point inside the container
# This directory will be typically mounted over using a Docker volume
RUN mkdir -p /app/fitfiles

# Expose the port the app runs on (Gunicorn will bind to this port)
EXPOSE 5000

# Define the command to run the application using Gunicorn
# --workers: Number of worker processes (adjust based on CPU cores, e.g., 2 * cores + 1)
# --bind 0.0.0.0:5000: Makes the app accessible from outside the container on the exposed port
# app:app: Tells Gunicorn to run the 'app' instance found in the 'app.py' module
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "app:app"]