import os
import json
import logging
import fitdecode
import pandas as pd
from datetime import datetime, timezone, date
from flask import Flask, render_template, request, jsonify
from typing import List, Dict, Optional, Any, Tuple, Union

# --- Basic Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
app = Flask(__name__)

# Read FIT_DIR from environment variable, default to 'fitfiles'
# Use a specific prefix for environment variables to avoid conflicts
FIT_DIR_ENV_VAR = 'FIT_ANALYZER_FIT_DIR'
DEFAULT_FIT_DIR = "fitfiles"
FIT_DIR: str = os.getenv(FIT_DIR_ENV_VAR, DEFAULT_FIT_DIR)

# Ensure the configured fitfiles directory exists
if not os.path.isdir(FIT_DIR):
    logger.warning(f"FIT file directory '{FIT_DIR}' not found. Attempting to create.")
    try:
        os.makedirs(FIT_DIR)
        logger.info(f"Created directory: {FIT_DIR}. Please add your .fit files there.")
    except OSError as e:
        logger.error(f"Could not create FIT file directory '{FIT_DIR}': {e}. Please create it manually.")
        # Depending on desired behavior, you might exit or continue with warnings
else:
    logger.info(f"Using FIT file directory: {FIT_DIR}")


# --- Type Definitions (Optional but helpful) ---
FitFileDetail = Dict[str, str] # e.g., {"filename": "...", "date": "YYYY-MM-DD"}
RecordData = Dict[str, Union[datetime, int, float, str, None]] # e.g., {"timestamp": ..., "power": ...}
PowerCurveData = Dict[int, float] # e.g., {60: 250.1, 300: 220.5}

# --- Helper Functions ---

def get_fit_file_details(dir_path: str) -> List[FitFileDetail]:
    """
    Scans a directory for .fit files and extracts their filename and date.

    Args:
        dir_path: The path to the directory containing .fit files.

    Returns:
        A list of dictionaries, each containing 'filename' and 'date' (YYYY-MM-DD).
        Returns an empty list if the directory doesn't exist or no files are found.
    """
    files_details: List[FitFileDetail] = []
    if not os.path.isdir(dir_path):
        logger.error(f"Directory not found during scan: {dir_path}")
        return files_details

    logger.info(f"Scanning directory for FIT files: {dir_path}")
    for filename in os.listdir(dir_path):
        if filename.lower().endswith(".fit"):
            filepath: str = os.path.join(dir_path, filename)
            file_date_str: Optional[str] = None
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
                                     file_date_str = timestamp.strftime('%Y-%m-%d')
                                     break
                if file_date_str:
                    files_details.append({"filename": filename, "date": file_date_str})
                else:
                     logger.warning(f"Could not determine date for {filename} from file_id message.")

            except fitdecode.FitError as e:
                logger.warning(f"Could not read {filename} to get date (FitError: {e}). Skipping.")
            except Exception as e:
                logger.warning(f"Could not process {filename} to get date (Error: {e}). Skipping.")

    files_details.sort(key=lambda x: x.get('date', '0000-00-00'), reverse=True)
    logger.info(f"Found {len(files_details)} FIT files with dates.")
    return files_details

def _perform_power_curve_calculation(records_data: List[RecordData]) -> Optional[PowerCurveData]:
    """
    Performs the power curve calculation using pandas on aggregated records data.

    Args:
        records_data: List of dictionaries [{'timestamp': dt, 'power': W}, ...].

    Returns:
        A dictionary {duration_sec: max_avg_power_watts} or None if error.
        Returns empty dict if no valid data.
    """
    if not records_data:
        logger.warning("Internal: No records data provided to _perform_power_curve_calculation.")
        return {}

    max_average_power: PowerCurveData = {}
    try:
        df = pd.DataFrame(records_data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
        df['power'] = pd.to_numeric(df['power'], errors='coerce')
        df = df.dropna(subset=['timestamp', 'power'])

        if df.empty:
             logger.warning("Internal: Data invalid or empty after cleaning in _perform_power_curve_calculation.")
             return {}

        df = df.set_index('timestamp').sort_index()

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
        logger.error(f"Internal: An error occurred during pandas processing in _perform_power_curve_calculation: {e}", exc_info=True)
        return None


def calculate_aggregate_power_curve(file_paths: List[str]) -> Optional[PowerCurveData]:
    """
    Processes multiple FIT files, aggregates their 'record' data,
    and calculates the max average power curve by calling the helper function.

    Args:
        file_paths: A list of full paths to the .fit files to process.

    Returns:
        A dictionary {duration_sec: max_avg_power_watts} or None if error/no data.
    """
    all_records_data: List[RecordData] = []
    total_records_processed: int = 0

    logger.info(f"Processing {len(file_paths)} files for power curve...")
    for filepath in file_paths:
        basename: str = os.path.basename(filepath)
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
                            all_records_data.append({'timestamp': timestamp, 'power': power})
                            file_record_count += 1
                logger.debug(f"    Found {file_record_count} records with timestamp & power in {basename}.")
                total_records_processed += file_record_count
        except fitdecode.FitError as e:
            logger.warning(f"Skipping {basename} due to FitError: {e}")
        except Exception as e:
            logger.error(f"Skipping {basename} due to unexpected Error: {e}", exc_info=True) # Log traceback for unexpected errors

    if not all_records_data:
        logger.warning("No valid 'record' data found across selected files.")
        return None

    logger.info(f"Total records aggregated: {total_records_processed}. Calculating power curve...")
    result = _perform_power_curve_calculation(all_records_data)

    if result is None:
        logger.error("Power curve calculation failed (returned None).")
        return None
    if not result: # Empty dict means calculation ran but yielded no points
        logger.warning("Power curve calculation resulted in no data points.")
        return None # Return None to API to indicate no curve generated

    logger.info("Power curve calculation complete.")
    return result

# --- Flask Routes ---

@app.route('/')
def index() -> str:
    """Serves the main HTML page."""
    logger.debug("Serving index.html")
    return render_template('index.html')

@app.route('/api/files', methods=['GET'])
def get_files() -> Tuple[str, int] | str :
    """API endpoint to get the list of FIT files and their dates."""
    logger.info("Request received for /api/files")
    # Read FIT_DIR here again in case it changed via env var without app restart
    # Or rely on the value read at startup
    current_fit_dir = os.getenv(FIT_DIR_ENV_VAR, DEFAULT_FIT_DIR)
    details = get_fit_file_details(current_fit_dir)
    return jsonify(details)

@app.route('/api/powercurve', methods=['POST'])
def get_power_curve() -> Tuple[str, int] | str :
    """
    API endpoint to calculate the power curve for files within a date range.
    Expects JSON: {"startDate": "YYYY-MM-DD", "endDate": "YYYY-MM-DD"}
    """
    logger.info("Request received for /api/powercurve")
    try:
        data: Optional[Dict[str, Any]] = request.get_json()
        if not data:
             logger.warning("Bad Request: No JSON data received.")
             return jsonify({"error": "Request body must be JSON."}), 400

        start_date_str: Optional[str] = data.get('startDate')
        end_date_str: Optional[str] = data.get('endDate')

        if not start_date_str or not end_date_str:
            logger.warning("Bad Request: Missing startDate or endDate in JSON payload.")
            return jsonify({"error": "Missing startDate or endDate"}), 400

        try:
            start_date: date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date: date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
             logger.warning(f"Bad Request: Invalid date format received. Start: '{start_date_str}', End: '{end_date_str}'")
             return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        if start_date > end_date:
             logger.warning(f"Bad Request: Start date ({start_date_str}) is after end date ({end_date_str}).")
             return jsonify({"error": "Start date cannot be after end date."}), 400


        logger.info(f"Processing request for power curve between {start_date_str} and {end_date_str}")

        current_fit_dir = os.getenv(FIT_DIR_ENV_VAR, DEFAULT_FIT_DIR)
        all_files: List[FitFileDetail] = get_fit_file_details(current_fit_dir)
        selected_files_paths: List[str] = []

        for file_info in all_files:
            try:
                file_date: date = datetime.strptime(file_info['date'], '%Y-%m-%d').date()
                if start_date <= file_date <= end_date:
                    selected_files_paths.append(os.path.join(current_fit_dir, file_info['filename']))
            except (ValueError, TypeError, KeyError):
                 logger.warning(f"Could not parse date or info for {file_info.get('filename')}. Skipping file for date range check.")

        if not selected_files_paths:
            logger.warning(f"No FIT files found within the date range {start_date_str} to {end_date_str}.")
            return jsonify({"error": "No FIT files found within the specified date range."}), 404

        power_curve_data: Optional[PowerCurveData] = calculate_aggregate_power_curve(selected_files_paths)

        if power_curve_data is None:
            logger.error("Power curve calculation failed for the selected date range.")
            return jsonify({"error": "Failed to calculate power curve from selected files. Check logs for details."}), 500

        # Prepare data for JSON (keys are already int, values float)
        # Convert keys to string for JSON standard, although most clients handle int keys
        json_compatible_data = {str(k): v for k, v in power_curve_data.items()}

        logger.info(f"Successfully calculated power curve for {len(selected_files_paths)} files.")
        return jsonify(json_compatible_data)

    except Exception as e:
        logger.exception("An unexpected error occurred in /api/powercurve endpoint.") # Log full traceback
        return jsonify({"error": "An internal server error occurred."}), 500


# --- Main Execution ---
if __name__ == '__main__':
    # Get host and port from environment variables or use defaults
    host = os.getenv('FIT_ANALYZER_HOST', '127.0.0.1')
    port = int(os.getenv('FIT_ANALYZER_PORT', '5000'))
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')

    logger.info(f"Starting Flask server on {host}:{port} (Debug: {debug_mode})")
    # Use debug=debug_mode for development server
    # Production deployment should use Gunicorn (handled in Dockerfile CMD)
    app.run(debug=debug_mode, host=host, port=port)

