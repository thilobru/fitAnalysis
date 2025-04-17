import os
import json
import logging
import fitdecode
import pandas as pd
from datetime import datetime, timezone, date
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash # For password hashing
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

# --- Database Configuration ---
# Get database URL from environment variable set by docker-compose or locally
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql+psycopg://user:password@localhost:5432/fit_analyzer_db' # Default for local dev if not set
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Disable modification tracking overhead

# Initialize SQLAlchemy and Migrate
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Database Models ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False) # Increased length for hash
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationship to FitFile (one-to-many)
    fit_files = db.relationship('FitFile', backref='owner', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password: str):
        # Hash the password before storing
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        # Check hashed password
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class FitFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(255), nullable=False)
    # Store path relative to a configured base storage path, or a unique ID/key
    storage_path = db.Column(db.String(512), nullable=False, unique=True)
    upload_timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    activity_date = db.Column(db.Date, nullable=True) # Extracted from file if possible
    filesize = db.Column(db.Integer, nullable=True) # In bytes
    processing_status = db.Column(db.String(50), default='uploaded') # e.g., uploaded, processing, complete, error
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Foreign key to User table

    def __repr__(self):
        return f'<FitFile {self.original_filename} User {self.user_id}>'


# --- Ensure directory exists (moved after app init) ---
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
# ... (get_fit_file_details needs update later to read from DB for a user) ...
# ... (_perform_power_curve_calculation remains the same) ...
# ... (calculate_aggregate_power_curve needs update later to read files based on DB records) ...

# --- Flask Routes ---
# ... (Existing routes need significant updates later for auth and DB interaction) ...
# Add a simple route to test DB connection (optional)
@app.route('/health')
def health_check() -> Tuple[str, int]:
     try:
         # Try a simple query
         db.session.execute(db.text('SELECT 1'))
         return jsonify({"status": "ok", "database": "connected"}), 200
     except Exception as e:
         logger.error(f"Database connection failed: {e}")
         return jsonify({"status": "error", "database": "disconnected"}), 500

@app.route('/')
def index() -> str:
    logger.debug("Serving index.html")
    return render_template('index.html')

# --- Placeholder API routes (to be properly implemented later) ---
@app.route('/api/files', methods=['GET'])
def get_files() -> Tuple[str, int] | str :
    logger.warning("/api/files needs update for authenticated users and DB query")
    # Replace with DB query for logged-in user later
    return jsonify([]) # Return empty for now

@app.route('/api/powercurve', methods=['POST'])
def get_power_curve() -> Tuple[str, int] | str :
    logger.warning("/api/powercurve needs update for authenticated users and DB query")
    # Replace with user-specific logic later
    return jsonify({"error": "Endpoint needs update for multi-user support."}), 501 # Not Implemented


# --- Main Execution ---
if __name__ == '__main__':
    host = os.getenv('FIT_ANALYZER_HOST', '127.0.0.1')
    port = int(os.getenv('FIT_ANALYZER_PORT', '5000'))
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')

    logger.info(f"Starting Flask server on {host}:{port} (Debug: {debug_mode})")
    app.run(debug=debug_mode, host=host, port=port)
