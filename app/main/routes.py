# app/main/routes.py
"""Blueprint for main application routes (e.g., index, health check)."""

import logging
from flask import Blueprint, render_template, jsonify
from ..extensions import db # Import db from shared extensions

logger = logging.getLogger(__name__)
# Create Blueprint instance
bp = Blueprint('main', __name__)

@bp.route('/')
def index() -> str:
    """Serves the main HTML page."""
    logger.debug("Serving index.html via main blueprint")
    # Assumes index.html is in app/templates/
    return render_template('index.html')

@bp.route('/health')
def health_check() -> tuple[str, int]:
    """Checks database connectivity."""
    try:
        # Try a simple query to check connection
        db.session.execute(db.text('SELECT 1'))
        logger.debug("Health check: Database connection successful.")
        return jsonify({"status": "ok", "database": "connected"}), 200
    except Exception as e:
        logger.error(f"Health check: Database connection failed: {e}")
        return jsonify({"status": "error", "database": "disconnected"}), 500

