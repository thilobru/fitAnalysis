import os
import json
import logging
import fitdecode
import pandas as pd
import uuid # For generating unique filenames
from datetime import datetime, timezone, date, timedelta
from flask import Flask, render_template, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
# Werkzeug security comes with Flask, used for password hashing
from werkzeug.security import generate_password_hash, check_password_hash
# Werkzeug tool for securing filenames provided by users
from werkzeug.utils import secure_filename
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
from dotenv import load_dotenv
load_dotenv() # Load .env file if present

FIT_DIR_ENV_VAR = 'FIT_ANALYZER_FIT_DIR'
DEFAULT_FIT_DIR = "fitfiles"
# Resolve FIT_DIR path once
FIT_DIR: str = os.path.abspath(os.getenv(FIT_DIR_ENV_VAR, DEFAULT_FIT_DIR))

# --- App Configuration ---
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-please-change-in-prod')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql+psycopg://user:password@localhost:5432/fit_analyzer_db' # Use explicit dialect
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# ** FIX: Store resolved FIT_DIR in app config as well **
app.config['FIT_DIR'] = FIT_DIR
# Optional: Limit upload size (e.g., 16MB)
# app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'.fit'} # Define allowed file extensions

# --- Extensions Initialization ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
@login_manager.unauthorized_handler
def unauthorized():
    logger.warning("Unauthorized access attempt.")
    return jsonify(error="Login required"), 401

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
    storage_path = db.Column(db.String(512), nullable=False, unique=True) # Relative path: <user_id>/<uuid>.fit
    upload_timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    activity_date = db.Column(db.Date, nullable=True) # Extracted from file if possible
    filesize = db.Column(db.Integer, nullable=True) # In bytes
    processing_status = db.Column(db.String(50), default='uploaded') # e.g., uploaded, processing, complete, error
    # Foreign key to User table, ensure cascade delete works if user is deleted
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)

    def get_full_path(self) -> str:
        """Helper to get the absolute path to the stored file."""
        # Read from app config for consistency
        base_dir = app.config.get('FIT_DIR', DEFAULT_FIT_DIR)
        return os.path.join(base_dir, self.storage_path)

    def __repr__(self):
        return f'<FitFile {self.original_filename} User {self.user_id}>'


# --- Ensure Base FIT_DIR exists ---
# Needs to run after app context might be available or just use os directly
# Moved this check lower, but it's mainly for local dev without Docker volume mount
# In Docker, the Dockerfile creates /app/fitfiles
if __name__ == '__main__': # Only check/create when running directly
    # Use the path from app config now
    resolved_fit_dir = app.config.get('FIT_DIR', DEFAULT_FIT_DIR)
    if not os.path.isdir(resolved_fit_dir):
        logger.warning(f"Base FIT file directory '{resolved_fit_dir}' not found. Attempting to create.")
        try:
            os.makedirs(resolved_fit_dir, exist_ok=True) # Use exist_ok=True
            logger.info(f"Created base directory: {resolved_fit_dir}.")
        except OSError as e:
            logger.error(f"Could not create base FIT file directory '{resolved_fit_dir}': {e}.")
    else:
        logger.info(f"Using base FIT file directory: {resolved_fit_dir}")

# --- Type Definitions ---
FitFileDetail = Dict[str, str]
RecordData = Dict[str, Union[datetime, int, float, str, None]]
PowerCurveData = Dict[int, float]

# --- Helper Functions ---

def _extract_activity_date(filepath: str) -> Optional[date]:
    """Extracts the activity date from a FIT file's file_id message."""
    activity_date: Optional[date] = None
    try:
        with fitdecode.FitReader(filepath) as fit:
            for frame in fit:
                if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == 'file_id':
                    if frame.has_field('time_created'):
                        timestamp = frame.get_value('time_created')
                        if isinstance(timestamp, datetime):
                             if timestamp.tzinfo is None:
                                 timestamp = timestamp.replace(tzinfo=timezone.utc)
                             else:
                                 timestamp = timestamp.astimezone(timezone.utc)
                             activity_date = timestamp.date()
                             break # Found it
        return activity_date
    except Exception as e:
        logger.error(f"Error extracting date from {os.path.basename(filepath)}: {e}")
        return None

def _allowed_file(filename: str) -> bool:
    """Checks if the filename has an allowed extension."""
    return '.' in filename and \
           os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

def _perform_power_curve_calculation(records_data: List[RecordData]) -> Optional[PowerCurveData]:
    """Performs the power curve calculation using pandas on aggregated records data."""
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
        # Define Power Curve Window Durations (in seconds)
        window_durations: List[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                                       12, 15, 20, 30, 45,
                                       60, 75, 90, 120, 150, 180,
                                       240, 300, 420, 600, 900,
                                       1200, 1800, 2700, 3600, 5400]

        for duration_sec in window_durations:
            window_str: str = f'{duration_sec}s'
            # Using float64 for potentially better precision in mean calculation
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
    """Processes multiple FIT files (given their paths), aggregates 'record' data, and calculates power curve."""
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
            logger.error(f"Skipping {basename} due to unexpected Error: {e}", exc_info=True) # Log traceback for unexpected errors

    if not all_records_data:
        logger.warning("No valid 'record' data found across selected files.")
        return None # Return None if no data was aggregated

    logger.info(f"Total records aggregated: {total_records_processed}. Calculating power curve...")
    result = _perform_power_curve_calculation(all_records_data)

    # Check if calculation itself failed (returned None)
    if result is None:
        logger.error("Power curve calculation failed (returned None).")
        return None
    # Check if calculation resulted in no valid data points (empty dict)
    if not result:
        logger.warning("Power curve calculation resulted in no data points.")
        return None # Return None to API to indicate no curve generated

    logger.info("Power curve calculation complete.")
    return result

# --- Authentication API Routes (Full Implementation) ---

@app.route('/api/register', methods=['POST'])
def register() -> Tuple[str, int]:
    """Registers a new user."""
    data: Optional[Dict[str, Any]] = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        logger.warning("Registration attempt failed: Missing username or password.")
        return jsonify({"error": "Username and password required"}), 400

    username: str = data['username'].strip() # Remove leading/trailing whitespace
    password: str = data['password']

    # Basic validation (add more as needed)
    if not username or len(username) < 3 or len(password) < 6:
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
        # Consider logging the user in automatically after registration
        # login_user(new_user, remember=True)
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
         # Return success if already logged in
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
            # Use a generic error message for security
            return jsonify({"error": "Invalid username or password"}), 401 # Unauthorized

        # Log the user in using Flask-Login
        # remember=True sets a persistent cookie
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
    username = getattr(current_user, 'username', 'Unknown') # Get username before logging out for logging
    logout_user()
    logger.info(f"User '{username}' logged out.")
    # Clear any other session data if necessary: session.clear()
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
            "user": {"username": username, "id": user_id} # Return basic user info
        }), 200
    else:
        logger.debug("API Status check: No user logged in.")
        return jsonify({"logged_in": False}), 200


# --- File Management API Routes ---

@app.route('/api/files', methods=['POST'])
@login_required
def upload_file() -> Tuple[str, int]:
    """Handles FIT file uploads for the logged-in user."""
    if 'file' not in request.files:
        logger.warning(f"File upload attempt failed for user {current_user.id}: No file part.")
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']
    # Check if file object exists and has a name
    if not file or not file.filename:
        logger.warning(f"File upload attempt failed for user {current_user.id}: No selected file.")
        return jsonify({"error": "No selected file"}), 400

    if _allowed_file(file.filename):
        original_filename = secure_filename(file.filename) # Sanitize filename
        file_ext = os.path.splitext(original_filename)[1]
        # Generate unique filename using UUID, keep original extension
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        user_id_str = str(current_user.id)
        # Relative path for storage within FIT_DIR
        relative_storage_path = os.path.join(user_id_str, unique_filename)
        # Absolute path for saving using app config
        full_save_path = os.path.join(app.config['FIT_DIR'], relative_storage_path)

        try:
            # Create user-specific directory if it doesn't exist
            user_dir = os.path.dirname(full_save_path)
            os.makedirs(user_dir, exist_ok=True)

            # Save the file
            file.save(full_save_path)
            logger.info(f"File '{original_filename}' uploaded by user {current_user.id} saved to '{full_save_path}'")

            # Get file size
            filesize = os.path.getsize(full_save_path)

            # Extract activity date (optional, can be slow)
            activity_date = _extract_activity_date(full_save_path)

            # Create database record
            new_fit_file = FitFile(
                original_filename=original_filename,
                storage_path=relative_storage_path, # Store relative path
                user_id=current_user.id,
                filesize=filesize,
                activity_date=activity_date,
                processing_status='uploaded' # Initial status
            )
            db.session.add(new_fit_file)
            db.session.commit()
            logger.info(f"Database record created for file ID {new_fit_file.id}")

            # Return info about the uploaded file
            return jsonify({
                "message": "File uploaded successfully",
                "file": {
                    "id": new_fit_file.id,
                    "filename": new_fit_file.original_filename,
                    "date": new_fit_file.activity_date.strftime('%Y-%m-%d') if new_fit_file.activity_date else None,
                    "status": new_fit_file.processing_status
                }
            }), 201 # Created

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error saving file or DB record for user {current_user.id}, file '{original_filename}': {e}", exc_info=True)
            # Clean up saved file if DB commit failed
            if os.path.exists(full_save_path):
                 try: os.remove(full_save_path); logger.info(f"Cleaned up failed upload: {full_save_path}")
                 except OSError: logger.error(f"Could not clean up failed upload: {full_save_path}")
            return jsonify({"error": "Failed to save file or create database record"}), 500

    else:
        logger.warning(f"File upload attempt failed for user {current_user.id}: File type '{file.filename}' not allowed.")
        return jsonify({"error": f"File type not allowed. Allowed: {ALLOWED_EXTENSIONS}"}), 400


@app.route('/api/files', methods=['GET'])
@login_required
def get_user_files() -> Tuple[str, int] | str :
    """API endpoint to get the list of FIT files for the logged-in user."""
    user_id = getattr(current_user, 'id', None)
    logger.info(f"Request received for /api/files list for user {user_id}")
    try:
        # Use lazy='dynamic' query for potential filtering later
        files_query = current_user.fit_files.order_by(FitFile.upload_timestamp.desc())
        files = files_query.all()

        details = [{
            "id": f.id,
            "filename": f.original_filename,
            "date": f.activity_date.strftime('%Y-%m-%d') if f.activity_date else None,
            "uploaded": f.upload_timestamp.isoformat(),
            "size_kb": round(f.filesize / 1024) if f.filesize else None,
            "status": f.processing_status
        } for f in files]

        return jsonify(details), 200
    except Exception as e:
        logger.error(f"Error fetching files for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve file list"}), 500


@app.route('/api/files/<int:file_id>', methods=['DELETE'])
@login_required
def delete_file(file_id: int) -> Tuple[str, int]:
    """Deletes a specific FIT file for the logged-in user."""
    user_id = getattr(current_user, 'id', None)
    logger.info(f"Request received to delete file {file_id} for user {user_id}")
    try:
        # Find the file ensuring it belongs to the current user
        # Use lazy='dynamic' query from relationship
        fit_file = current_user.fit_files.filter_by(id=file_id).first()

        if fit_file is None:
            logger.warning(f"Delete request failed: File ID {file_id} not found or not owned by user {user_id}.")
            # Return 404 even if it exists but belongs to another user, for security
            return jsonify({"error": "File not found"}), 404

        full_path = fit_file.get_full_path() # Get absolute path using helper
        storage_path_log = fit_file.storage_path # For logging

        # Try to delete file from filesystem first
        file_deleted_ok = False
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
                logger.info(f"Deleted file from filesystem: {full_path}")
                file_deleted_ok = True
            except OSError as e:
                logger.error(f"Error deleting file {full_path} from filesystem: {e}. Proceeding to delete DB record.")
                # Decide if you want to proceed or return error - let's proceed for now
                file_deleted_ok = True # Treat as ok to allow DB delete, but log error
        else:
            logger.warning(f"File not found on filesystem for deletion: {full_path} (DB record for {storage_path_log} will be deleted).")
            file_deleted_ok = True # Allow DB delete if file already gone

        # Proceed to delete DB record
        db.session.delete(fit_file)
        db.session.commit()
        logger.info(f"Successfully deleted file record ID {file_id} for user {user_id}.")
        return jsonify({"message": "File deleted successfully"}), 200 # Or 204 No Content

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting file ID {file_id} for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to delete file"}), 500


# --- Analysis API Route ---
@app.route('/api/powercurve', methods=['POST'])
@login_required
def get_user_power_curve() -> Tuple[str, int] | str :
    """Calculates power curve for the logged-in user's files within a date range."""
    user_id = getattr(current_user, 'id', None)
    logger.info(f"Request received for /api/powercurve for user {user_id}")

    data: Optional[Dict[str, Any]] = request.get_json()
    if not data: return jsonify({"error": "Request body must be JSON."}), 400
    start_date_str: Optional[str] = data.get('startDate')
    end_date_str: Optional[str] = data.get('endDate')
    if not start_date_str or not end_date_str: return jsonify({"error": "Missing startDate or endDate"}), 400

    try:
        start_date: date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date: date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError: return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
    if start_date > end_date: return jsonify({"error": "Start date cannot be after end date."}), 400

    logger.info(f"Calculating power curve for user {user_id} between {start_date_str} and {end_date_str}")
    try:
        # Query DB for files belonging to the user within the date range
        # Use lazy='dynamic' query from relationship
        files_to_process_query = current_user.fit_files.filter(
                FitFile.activity_date >= start_date,
                FitFile.activity_date <= end_date
                # Optional: Add status filter, e.g., FitFile.processing_status == 'complete'
            )
        files_to_process = files_to_process_query.all()

        if not files_to_process:
            logger.info(f"No FIT files with activity dates found for user {user_id} in range {start_date_str} to {end_date_str}.")
            return jsonify({}), 200 # OK, but no data

        # Construct full paths for the calculation function
        file_paths: List[str] = [f.get_full_path() for f in files_to_process]
        # Check which files actually exist before passing to calculation
        existing_file_paths = [p for p in file_paths if os.path.isfile(p)]
        if not existing_file_paths:
             logger.warning(f"No files found on filesystem for user {user_id} in range {start_date_str} to {end_date_str}, though DB records exist.")
             # Consider deleting orphaned DB records or marking them as error?
             return jsonify({"error": "Files associated with this date range not found on server."}), 404

        if len(existing_file_paths) < len(file_paths):
             logger.warning(f"Missing {len(file_paths) - len(existing_file_paths)} files on filesystem for user {user_id} in range.")

        # Call the existing calculation function
        power_curve_data: Optional[PowerCurveData] = calculate_aggregate_power_curve(existing_file_paths)

        if power_curve_data is None:
             logger.error(f"Power curve calculation failed for user {user_id} (returned None or empty). Check logs.")
             return jsonify({"error": "Failed to calculate power curve. Files might be invalid or empty."}), 500

        # Convert keys to string for JSON
        json_compatible_data = {str(k): v for k, v in power_curve_data.items()}
        logger.info(f"Successfully calculated power curve for user {user_id} using {len(existing_file_paths)} files.")
        return jsonify(json_compatible_data), 200

    except Exception as e:
        logger.exception(f"Unexpected error during power curve calculation for user {user_id}")
        return jsonify({"error": "An internal server error occurred during calculation."}), 500

# --- Main Execution & Other Routes ---
@app.route('/')
def index() -> str:
    """Serves the main HTML page."""
    return render_template('index.html')

@app.route('/health')
def health_check() -> Tuple[str, int]:
    """Checks database connectivity."""
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify({"status": "ok", "database": "connected"}), 200
    except Exception as e:
        logger.error(f"DB connection failed: {e}")
        return jsonify({"status": "error", "database": "disconnected"}), 500

if __name__ == '__main__':
    host = os.getenv('FIT_ANALYZER_HOST', '127.0.0.1')
    port = int(os.getenv('FIT_ANALYZER_PORT', '5000'))
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')
    secret_key = app.config.get('SECRET_KEY')
    # Security check for SECRET_KEY
    if not secret_key or secret_key == 'dev-secret-key-please-change-in-prod':
         if not debug_mode:
             logger.critical("FATAL: SECRET_KEY is not set or is insecure in production environment (FLASK_DEBUG=False)!")
             # In a real app, you might raise an exception or exit here
             # raise ValueError("Missing or insecure SECRET_KEY in production!")
         else:
              logger.warning("WARNING: Using default/insecure SECRET_KEY in debug mode.")

    logger.info(f"Starting Flask server on {host}:{port} (Debug: {debug_mode})")
    # Use Flask's development server if running directly (debug=True enables auto-reload)
    # Production deployment uses Gunicorn via Docker CMD
    app.run(debug=debug_mode, host=host, port=port)

