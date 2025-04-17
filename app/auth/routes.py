# app/auth/routes.py
"""Blueprint for authentication API routes."""

import logging
from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash # Already imported in models? No harm here.
from typing import Optional, Dict, Any, Tuple

# Import db instance and User model
from ..extensions import db
from ..models import User

logger = logging.getLogger(__name__)
# Create Blueprint instance with URL prefix
bp = Blueprint('auth', __name__, url_prefix='/api')

@bp.route('/register', methods=['POST'])
def register() -> Tuple[str, int]:
    """Registers a new user."""
    data: Optional[Dict[str, Any]] = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        logger.warning("Registration attempt failed: Missing username or password.")
        return jsonify({"error": "Username and password required"}), 400

    username: str = data['username'].strip()
    password: str = data['password']

    if not username or len(username) < 3 or len(password) < 6:
         logger.warning(f"Registration attempt failed for '{username}': Invalid length.")
         return jsonify({"error": "Username must be >= 3 chars, password >= 6 chars"}), 400

    try:
        existing_user = db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none()
        if existing_user:
            logger.warning(f"Registration attempt failed: Username '{username}' already exists.")
            return jsonify({"error": "Username already exists"}), 409 # Conflict

        new_user = User(username=username)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()
        logger.info(f"User '{username}' registered successfully.")
        return jsonify({"message": "User registered successfully"}), 201 # Created
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error during registration for '{username}': {e}", exc_info=True)
        return jsonify({"error": "Registration failed due to server error"}), 500


@bp.route('/login', methods=['POST'])
def login() -> Tuple[str, int]:
    """Logs a user in."""
    if current_user.is_authenticated:
         logger.info(f"User '{current_user.username}' attempted login while already logged in.")
         return jsonify({"message": "Already logged in", "username": current_user.username}), 200

    data: Optional[Dict[str, Any]] = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        logger.warning("Login attempt failed: Missing username or password.")
        return jsonify({"error": "Username and password required"}), 400

    username: str = data['username']
    password: str = data['password']

    try:
        user = db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none()

        if user is None or not user.check_password(password):
            logger.warning(f"Login attempt failed for username: '{username}' - Invalid credentials.")
            return jsonify({"error": "Invalid username or password"}), 401 # Unauthorized

        # Log the user in using Flask-Login
        # Use app config for session lifetime
        from flask import current_app
        login_user(user, remember=True, duration=current_app.config.get('PERMANENT_SESSION_LIFETIME'))
        logger.info(f"User '{username}' logged in successfully.")
        return jsonify({"message": "Login successful", "username": user.username}), 200
    except Exception as e:
        logger.error(f"Error during login for username '{username}': {e}", exc_info=True)
        return jsonify({"error": "Login failed due to server error"}), 500


@bp.route('/logout', methods=['POST'])
@login_required # Ensure user is logged in to log out
def logout() -> Tuple[str, int]:
    """Logs the current user out."""
    username = getattr(current_user, 'username', 'Unknown')
    logout_user()
    logger.info(f"User '{username}' logged out.")
    return jsonify({"message": "Logout successful"}), 200


@bp.route('/status', methods=['GET'])
def status() -> Tuple[str, int]:
    """Checks if a user is currently logged in."""
    if current_user.is_authenticated:
        user_id = getattr(current_user, 'id', None)
        username = getattr(current_user, 'username', 'Unknown')
        logger.debug(f"API Status check: User '{username}' (ID: {user_id}) is logged in.")
        return jsonify({
            "logged_in": True,
            "user": {"username": username, "id": user_id}
        }), 200
    else:
        logger.debug("API Status check: No user logged in.")
        return jsonify({"logged_in": False}), 200

