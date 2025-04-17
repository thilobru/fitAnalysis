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
# Configure logging level and format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Get logger instance for this module
logger = logging.getLogger(__name__)

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Configuration Loading ---
# Load environment variables from .env file if it exists (for local development)
from dotenv import load_dotenv
load_dotenv()

# Read FIT_DIR from environment variable, default to 'fitfiles'
FIT_DIR_ENV_VAR = 'FIT_ANALYZER_FIT_DIR'
DEFAULT_FIT_DIR = "fitfiles"
FIT_DIR: str = os.getenv(FIT_DIR_ENV_VAR, DEFAULT_FIT_DIR)

# Secret Key Configuration (CRUCIAL for Sessions)
# MUST be set to a strong, random secret in production via environment variable
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-please-change-in-prod')
# Configure session cookie settings (optional)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7) # Example: session lasts 7 days

# Database Configuration
# Use explicit 'postgresql+psycopg' dialect
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql+psycopg://user:password@localhost:5432/fit_analyzer_db' # Default for local dev
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Disable modification tracking overhead

# --- Extensions Initialization ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
# If you were redirecting non-logged-in users to an HTML login page:
# login_manager.login_view = 'login' # Name of the login route function
# login_manager.login_message = 'Please log in to access this page.'
# login_manager.login_message_category = 'info'

# --- Flask-Login User Loader ---
@login_manager.user_loader
def load_user(user_id: str) -> Optional['User']:
    """Flask-Login callback to load a user from the session."""
    try:
        # Use db.session.get for primary key lookup
        return db.session.get(User, int(user_id))
    except Exception as e:
        logger.error(f"Error loading user {user_id}: {e}")
        return None

# --- Database Models ---

# Add UserMixin for Flask-Login integration
class User(db.Model, UserMixin):
    __tablename__ = 'user' # Explicit table name is good practice
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationship to FitFile (one-to-many)
    # cascade="all, delete-orphan": Deletes user's files if user is deleted
    # lazy='dynamic': Allows further querying on the relationship (e.g., filtering files)
    fit_files = db.relationship('FitFile', backref='owner', lazy='dynamic', cascade="all, delete-orphan")

    def set_password(self, password: str):
        # Hash the password before storing using a strong method
        # Use default salt length and iterations
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password: str) -> bool:
        # Check hashed password
        return check_password_hash(self.password_hash, password)

    # get_id method is provided by UserMixin

    def __repr__(self):
        return f'<User {self.username}>'

class FitFile(db.Model):
    __tablename__ = 'fit_file' # Explicit table name
    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(255), nullable=False)
    # Store path relative to a configured base storage path, or a unique ID/key
    storage_path = db.Column(db.String(512), nullable=False, unique=True)
    upload_timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    activity_date = db.Column(db.Date, nullable=True) # Extracted from file if possible
    filesize = db.Column(db.Integer, nullable=True) # In bytes
    processing_status = db.Column(db.String(50), default='uploaded') # e.g., uploaded, processing, complete, error
    # Foreign key to User table, ensure cascade delete works if user is deleted
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)

    def __repr__(self):
        return f'<FitFile {self.original_filename} User {self.user_id}>'


# --- Ensure FIT_DIR exists ---
# Needs to run after app context might be available or just use os directly
# Moved this check lower, but it's mainly for local dev without Docker volume mount
# In Docker, the Dockerfile creates /app/fitfiles
if __name__ == '__main__': # Only check/create when running directly
    if not os.path.isdir(FIT_DIR):
        logger.warning(f"FIT file directory '{FIT_DIR}' not found. Attempting to create.")
        try:
            os.makedirs(FIT_DIR)
            logger.info(f"Created directory: {FIT_DIR}. Please add your .fit files there.")
        except OSError as e:
            logger.error(f"Could not create FIT file directory '{FIT_DIR}': {e}. Please create it manually.")
    else:
        logger.info(f"Using FIT file directory: {FIT_DIR}")

# --- Type Definitions ---
FitFileDetail = Dict[str, str]
RecordData = Dict[str, Union[datetime, int, float, str, None]]
PowerCurveData = Dict[int, float]

# --- Helper Functions ---

def get_fit_file_details(dir_path: str) -> List[FitFileDetail]:
    """
    Scans a directory for .fit files and extracts their filename and date.
    NOTE: This function needs to be adapted or removed for multi-user DB approach.
          It's currently unused by the placeholder API routes below.
    """
    files_details: List[FitFileDetail] = []
    # ... (Implementation as before, but log warning if called) ...
    logger.warning("get_fit_file_details function called - needs update for multi-user DB storage.")
    return files_details

def _perform_power_curve_calculation(records_data: List[RecordData]) -> Optional[PowerCurveData]:
    """
    Performs the power curve calculation using pandas on aggregated records data.
    (Implementation remains the same as in app_py_enhanced - the core logic is sound)
    """
    if not records_data:
        logger.warning("Internal: No records data provided to _perform_power_curve_calculation.")
        return {} # Return empty dict for no data

    max_average_power: PowerCurveData = {}
    try:
        df = pd.DataFrame(records_data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
        df['power'] = pd.to_numeric(df['power'], errors='coerce')
        df = df.dropna(subset=['timestamp', 'power'])

        if df.empty:
             logger.warning("Internal: Data invalid or empty after cleaning in _perform_power_curve_calculation.")
             return {} # Return empty dict if no valid data remains

        df = df.set_index('timestamp').sort_index()

        window_durations: List[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                                       12, 15, 20, 30, 45,
                                       60, 75, 90, 120, 150, 180,
                                       240, 300, 420, 600, 900,
                                       1200, 1800, 2700, 3600, 5400]

        for duration_sec in window_durations:
            window_str: str = f'{duration_sec}s'
            rolling_mean = df['power'].astype('float64').rolling(window_str, min_periods=1, closed='right').mean()
            max_power = rolling_mean.max()

            if pd.notna(max_power):
                 max_average_power[duration_sec] = round(float(max_power), 1)

        logger.debug("Internal: Power curve calculation complete.")
        return max_average_power

    except Exception as e:
        logger.error(f"Internal: An error occurred during pandas processing: {e}", exc_info=True)
        return None # Return None on unexpected calculation errors


def calculate_aggregate_power_curve(file_paths: List[str]) -> Optional[PowerCurveData]:
    """
    Processes multiple FIT files (given their paths), aggregates 'record' data,
    and calculates the max average power curve.
    NOTE: This needs update later to handle potential errors per file better.
    """
    all_records_data: List[RecordData] = []
    total_records_processed: int = 0

    logger.info(f"Processing {len(file_paths)} files for power curve...")
    for filepath in file_paths:
        basename: str = os.path.basename(filepath)
        # Basic check if file exists before trying to open
        if not os.path.isfile(filepath):
             logger.warning(f"File not found during calculation: {filepath}. Skipping.")
             continue
        try:
            logger.debug(f"  Reading: {basename}")
            with fitdecode.FitReader(filepath) as fit:
                file_record_count: int = 0
                for frame in fit:
                    if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == 'record':
                        timestamp = frame.get_value('timestamp', fallback=None)
                        power = frame.get_value('power', fallback=None)

                        if timestamp is not None and power is not None:
                            if not isinstance(timestamp, datetime):
                                logger.warning(f"Invalid timestamp type ({type(timestamp)}) in {basename}. Skipping record.")
                                continue
                            # Convert power to numeric early if possible
                            try:
                                numeric_power = float(power)
                                all_records_data.append({'timestamp': timestamp, 'power': numeric_power})
                                file_record_count += 1
                            except (ValueError, TypeError):
                                logger.warning(f"Invalid power value ({power}) in {basename}. Skipping record.")
                logger.debug(f"    Found {file_record_count} valid records in {basename}.")
                total_records_processed += file_record_count
        except fitdecode.FitError as e:
            logger.warning(f"Skipping {basename} due to FitError: {e}")
        except Exception as e:
            logger.error(f"Skipping {basename} due to unexpected Error: {e}", exc_info=True)

    if not all_records_data:
        logger.warning("No valid 'record' data found across selected files.")
        return None

    logger.info(f"Total records aggregated: {total_records_processed}. Calculating power curve...")
    result = _perform_power_curve_calculation(all_records_data)

    if result is None:
        logger.error("Power curve calculation failed (returned None).")
        return None
    if not result: # Empty dict
        logger.warning("Power curve calculation resulted in no data points.")
        return None # Indicate no curve generated

    logger.info("Power curve calculation complete.")
    return result

# --- Authentication API Routes ---

@app.route('/api/register', methods=['POST'])
def register() -> Tuple[str, int]:
    """Registers a new user."""
    data: Optional[Dict[str, Any]] = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        logger.warning("Registration attempt failed: Missing username or password.")
        return jsonify({"error": "Username and password required"}), 400

    username: str = data['username']
    password: str = data['password']

    if len(username) < 3 or len(password) < 6:
         logger.warning(f"Registration attempt failed for '{username}': Invalid length.")
         return jsonify({"error": "Username must be >= 3 chars, password >= 6 chars"}), 400

    # Use try-except for database query
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


@app.route('/api/login', methods=['POST'])
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
        login_user(user, remember=True, duration=app.config['PERMANENT_SESSION_LIFETIME'])
        logger.info(f"User '{username}' logged in successfully.")
        return jsonify({"message": "Login successful", "username": user.username}), 200
    except Exception as e:
        logger.error(f"Error during login for username '{username}': {e}", exc_info=True)
        return jsonify({"error": "Login failed due to server error"}), 500


@app.route('/api/logout', methods=['POST'])
@login_required # Ensure user is logged in to log out
def logout() -> Tuple[str, int]:
    """Logs the current user out."""
    username = current_user.username # Get username before logging out for logging
    logout_user()
    logger.info(f"User '{username}' logged out.")
    return jsonify({"message": "Logout successful"}), 200


@app.route('/api/status', methods=['GET'])
def status() -> Tuple[str, int]:
    """Checks if a user is currently logged in."""
    if current_user.is_authenticated:
        # Ensure current_user has expected attributes before accessing
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
         # Try a simple query to check connection
         db.session.execute(db.text('SELECT 1'))
         logger.debug("Health check: Database connection successful.")
         return jsonify({"status": "ok", "database": "connected"}), 200
     except Exception as e:
         logger.error(f"Health check: Database connection failed: {e}")
         return jsonify({"status": "error", "database": "disconnected"}), 500


# --- Placeholder API routes (NEED FULL IMPLEMENTATION) ---
@app.route('/api/files', methods=['GET'])
@login_required # Protect this route
def get_user_files() -> Tuple[str, int] | str :
    """API endpoint to get the list of FIT files for the logged-in user."""
    user_id = getattr(current_user, 'id', None)
    logger.info(f"Request received for /api/files for user {user_id}")
    # TODO: Implement DB query to get FitFile records for current_user.id
    # files = db.session.execute(db.select(FitFile).filter_by(user_id=user_id).order_by(FitFile.upload_timestamp.desc())).scalars().all()
    # details = [{"id": f.id, "filename": f.original_filename, "date": f.activity_date.strftime('%Y-%m-%d') if f.activity_date else None, "status": f.processing_status} for f in files]
    # return jsonify(details)
    logger.warning("/api/files needs update for authenticated users and DB query")
    return jsonify([]) # Return empty for now

# TODO: Add POST /api/files route for uploads
# TODO: Add DELETE /api/files/<id> route

@app.route('/api/powercurve', methods=['POST'])
@login_required # Protect this route
def get_user_power_curve() -> Tuple[str, int] | str :
    """API endpoint to calculate power curve for the logged-in user's files."""
    user_id = getattr(current_user, 'id', None)
    logger.info(f"Request received for /api/powercurve for user {user_id}")
    # TODO:
    # 1. Get date range from request JSON. Validate dates.
    # 2. Query DB for FitFile records for user_id within date range (where status is 'complete'?).
    # 3. Get storage_path for each selected file record.
    # 4. Construct full paths based on a configured base storage path (e.g., FIT_DIR). Check existence.
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
    secret_key = app.config.get('SECRET_KEY')
    if not secret_key or secret_key == 'dev-secret-key-please-change-in-prod':
         if not debug_mode:
             logger.critical("FATAL: SECRET_KEY is not set or is insecure in production environment (FLASK_DEBUG=False)!")
             # Exit or raise error in a real production scenario
             # raise ValueError("Missing or insecure SECRET_KEY in production!")
         else:
              logger.warning("WARNING: Using default/insecure SECRET_KEY in debug mode.")

    logger.info(f"Starting Flask server on {host}:{port} (Debug: {debug_mode})")
    # Use debug=debug_mode for development server
    # Production deployment should use Gunicorn (handled in Dockerfile CMD)
    app.run(debug=debug_mode, host=host, port=port)
