# run.py
"""Script to run the Flask application (primarily for local development)."""

import os
from app import create_app # Import the factory function

# Create app instance using the factory
# Load environment variables (e.g., from .env) before calling create_app
app = create_app()

if __name__ == '__main__':
    # Get host/port/debug settings from environment variables
    host = os.getenv('FIT_ANALYZER_HOST', '127.0.0.1')
    port = int(os.getenv('FIT_ANALYZER_PORT', '5000'))
    # Check FLASK_DEBUG env var for debug mode
    debug_mode = os.getenv('FLASK_DEBUG', '0').lower() in ('true', '1', 't')

    # Security check for SECRET_KEY
    secret_key = app.config.get('SECRET_KEY')
    if not secret_key or secret_key == 'dev-secret-key-please-change-in-prod':
         if not debug_mode:
             app.logger.critical("FATAL: SECRET_KEY is not set or is insecure in production environment!")
         else:
              app.logger.warning("WARNING: Using default/insecure SECRET_KEY in debug mode.")

    app.logger.info(f"Starting Flask development server on {host}:{port} (Debug: {debug_mode})")
    # Use app.run() here for the development server
    # Production deployment uses Gunicorn via Docker CMD pointing to the app factory
    app.run(host=host, port=port, debug=debug_mode)

