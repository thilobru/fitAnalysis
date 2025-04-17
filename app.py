import os
import json
import logging
import fitdecode
import pandas as pd
from datetime import datetime, timezone, date, timedelta
from flask import Flask, render_template, request, jsonify, session # Added session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
# Werkzeug security comes with Flask, used for password hashing
from werkzeug.security import generate_password_hash, check_password_hash
# Flask-Login for session management
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from typing import List, Dict, Optional, Any, Tuple, Union

# --- Basic Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
app = Flask(__name__)

# Load environment variables from .env file if it exists (for local development)
from dotenv import load_dotenv
load_dotenv()

# Read FIT_DIR from environment variable, default to 'fitfiles'
FIT_DIR_ENV_VAR = 'FIT_ANALYZER_FIT_DIR'
DEFAULT_FIT_DIR = "fitfiles"
FIT_DIR: str = os.getenv(FIT_DIR_ENV_VAR, DEFAULT_FIT_DIR)

# --- Secret Key Configuration (CRUCIAL for Sessions) ---
# MUST be set to a strong, random secret in production via environment variable
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-please-change')
# Configure session cookie settings (optional)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7) # Example: session lasts 7 days

# --- Database Configuration ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql+psycopg://user:password@localhost:5432/fit_analyzer_db' # Default for local dev
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Flask-Login Configuration ---
login_manager = LoginManager()
login_manager.init_app(app)
# If using API-only, you might handle unauthorized differently,
# but setting login_view is still good practice.
# login_manager.login_view = 'login_route_name' # e.g., if you had an HTML login page route
# login_manager.login_message_category = 'info' # Flash message category

@login_manager.user_loader
def load_user(user_id: str) -> Optional['User']:
    """Flask-Login callback to load a user from the session."""
    try:
        return db.session.get(User, int(user_id))
    except Exception as e:
        logger.error(f"Error loading user {user_id}: {e}")
        return None

# --- Database Models ---

# Add UserMixin for Flask-Login integration
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True) # Added index
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    fit_files = db.relationship('FitFile', backref='owner', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password: str):
        # Hash the password before storing using a strong method
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password: str) -> bool:
        # Check hashed password
        return check_password_hash(self.password_hash, password)

    # Flask-Login requires the get_id method (provided by UserMixin if id is primary key)
    # def get_id(self):
    #     return str(self.id)

    def __repr__(self):
        return f'<User {self.username}>'

class FitFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(512), nullable=False, unique=True)
    upload_timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    activity_date = db.Column(db.Date, nullable=True)
    filesize = db.Column(db.Integer, nullable=True)
    processing_status = db.Column(db.String(50), default='uploaded')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True) # Added index & ondelete

    def __repr__(self):
        return f'<FitFile {self.original_filename} User {self.user_id}>'

# --- Ensure directory exists ---
# (Code remains the same as before)
if not os.path.isdir(FIT_DIR):
    logger.warning(f"FIT file directory '{FIT_DIR}' not found. Attempting to create.")
    try:
        os.makedirs(FIT_DIR)
        logger.info(f"Created directory: {FIT_DIR}. Please add your .fit files there.")
    except OSError as e:
        logger.error(f"Could not create FIT file directory '{FIT_DIR}': {e}.")
else:
    logger.info(f"Using FIT file directory: {FIT_DIR}")

# --- Type Definitions ---
# (Code remains the same as before)
FitFileDetail = Dict[str, str]
RecordData = Dict[str, Union[datetime, int, float, str, None]]
PowerCurveData = Dict[int, float]

# --- Helper Functions ---
# (get_fit_file_details, _perform_power_curve_calculation, calculate_aggregate_power_curve)
# (These need significant updates later to work with specific users and DB storage)
# (For now, they are effectively disabled by the changes in the API routes below)

# --- Authentication API Routes ---

@app.route('/api/register', methods=['POST'])
def register() -> Tuple[str, int]:
    """Registers a new user."""
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"error": "Username and password required"}), 400

    username = data['username']
    password = data['password']

    # Basic validation (add more as needed)
    if len(username) < 3 or len(password) < 6:
         return jsonify({"error": "Username must be >= 3 chars, password >= 6 chars"}), 400

    existing_user = db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none()
    if existing_user:
        logger.warning(f"Registration attempt failed: Username '{username}' already exists.")
        return jsonify({"error": "Username already exists"}), 409 # Conflict

    new_user = User(username=username)
    new_user.set_password(password)
    try:
        db.session.add(new_user)
        db.session.commit()
        logger.info(f"User '{username}' registered successfully.")
        # Optionally log the user in immediately after registration
        # login_user(new_user, remember=True, duration=app.config['PERMANENT_SESSION_LIFETIME'])
        return jsonify({"message": "User registered successfully"}), 201 # Created
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error during registration for '{username}': {e}", exc_info=True)
        return jsonify({"error": "Registration failed due to server error"}), 500


@app.route('/api/login', methods=['POST'])
def login() -> Tuple[str, int]:
    """Logs a user in."""
    if current_user.is_authenticated:
         return jsonify({"message": "Already logged in", "username": current_user.username}), 200

    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"error": "Username and password required"}), 400

    username = data['username']
    password = data['password']

    user = db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none()

    if user is None or not user.check_password(password):
        logger.warning(f"Login attempt failed for username: '{username}'")
        # Use a generic error message for security
        return jsonify({"error": "Invalid username or password"}), 401 # Unauthorized

    # Log the user in using Flask-Login
    # remember=True sets a persistent cookie
    login_user(user, remember=True, duration=app.config['PERMANENT_SESSION_LIFETIME'])
    logger.info(f"User '{username}' logged in successfully.")
    return jsonify({"message": "Login successful", "username": user.username}), 200


@app.route('/api/logout', methods=['POST'])
@login_required # Ensure user is logged in to log out
def logout() -> Tuple[str, int]:
    """Logs the current user out."""
    username = current_user.username # Get username before logging out
    logout_user()
    logger.info(f"User '{username}' logged out.")
    return jsonify({"message": "Logout successful"}), 200


@app.route('/api/status', methods=['GET'])
def status() -> Tuple[str, int]:
    """Checks if a user is currently logged in."""
    if current_user.is_authenticated:
        return jsonify({
            "logged_in": True,
            "user": {"username": current_user.username, "id": current_user.id}
        }), 200
    else:
        return jsonify({"logged_in": False}), 200


# --- Main Application Routes ---

@app.route('/')
def index() -> str:
    """Serves the main HTML page."""
    logger.debug("Serving index.html")
    return render_template('index.html')

@app.route('/health')
def health_check() -> Tuple[str, int]:
     """Checks database connectivity."""
     try:
         db.session.execute(db.text('SELECT 1'))
         return jsonify({"status": "ok", "database": "connected"}), 200
     except Exception as e:
         logger.error(f"Database connection failed: {e}")
         return jsonify({"status": "error", "database": "disconnected"}), 500


# --- Placeholder API routes (NEED UPDATING FOR AUTH & DB) ---
@app.route('/api/files', methods=['GET'])
@login_required # Protect this route
def get_files() -> Tuple[str, int] | str :
    """API endpoint to get the list of FIT files for the logged-in user."""
    logger.info(f"Request received for /api/files for user {current_user.id}")
    # TODO: Implement DB query to get FitFile records for current_user.id
    # Example structure:
    # files = db.session.execute(db.select(FitFile).filter_by(user_id=current_user.id).order_by(FitFile.upload_timestamp.desc())).scalars().all()
    # details = [{"id": f.id, "filename": f.original_filename, "date": f.activity_date.strftime('%Y-%m-%d') if f.activity_date else None, "status": f.processing_status} for f in files]
    # return jsonify(details)
    logger.warning("/api/files needs update for authenticated users and DB query")
    return jsonify([]) # Return empty for now

@app.route('/api/powercurve', methods=['POST'])
@login_required # Protect this route
def get_power_curve() -> Tuple[str, int] | str :
    """API endpoint to calculate power curve for the logged-in user's files."""
    logger.info(f"Request received for /api/powercurve for user {current_user.id}")
    # TODO:
    # 1. Get date range from request JSON.
    # 2. Query DB for FitFile records for current_user.id within date range.
    # 3. Get storage_path for each selected file record.
    # 4. Construct full paths based on a configured base storage path.
    # 5. Call calculate_aggregate_power_curve with these full paths.
    # 6. Return result or error.
    logger.warning("/api/powercurve needs update for authenticated users and DB query")
    return jsonify({"error": "Endpoint needs update for multi-user support."}), 501 # Not Implemented


# --- Main Execution ---
if __name__ == '__main__':
    host = os.getenv('FIT_ANALYZER_HOST', '127.0.0.1')
    port = int(os.getenv('FIT_ANALYZER_PORT', '5000'))
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')

    # IMPORTANT: Ensure SECRET_KEY is set, especially if debug_mode is False
    if not app.config['SECRET_KEY'] and not debug_mode:
         logger.error("FATAL: SECRET_KEY is not set in production environment!")
         # Consider exiting or raising an error here in a real app
    elif app.config['SECRET_KEY'] == 'dev-secret-key-please-change' and not debug_mode:
         logger.warning("WARNING: Using default SECRET_KEY in non-debug mode. Set a strong SECRET_KEY environment variable!")


    logger.info(f"Starting Flask server on {host}:{port} (Debug: {debug_mode})")
    app.run(debug=debug_mode, host=host, port=port)
