import os
import json
import fitdecode
import pandas as pd
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify

# --- Configuration ---
# Create a Flask application instance
app = Flask(__name__)
# Define the directory where your .fit files are stored
FIT_DIR = "fitfiles"
# Ensure the fitfiles directory exists
if not os.path.isdir(FIT_DIR):
    os.makedirs(FIT_DIR)
    print(f"Created directory: {FIT_DIR}. Please add your .fit files there.")

# --- Helper Functions ---

def get_fit_file_details(dir_path):
    """
    Scans a directory for .fit files and extracts their filename and date.

    Args:
        dir_path (str): The path to the directory containing .fit files.

    Returns:
        list: A list of dictionaries, each containing 'filename' and 'date' (YYYY-MM-DD).
              Returns an empty list if the directory doesn't exist or no files are found.
    """
    files_details = []
    if not os.path.isdir(dir_path):
        print(f"Error: Directory not found - {dir_path}")
        return files_details

    print(f"Scanning directory: {dir_path}")
    for filename in os.listdir(dir_path):
        if filename.lower().endswith(".fit"):
            filepath = os.path.join(dir_path, filename)
            file_date_str = None
            try:
                # Try to get the date from the file_id message (most reliable)
                with fitdecode.FitReader(filepath) as fit:
                    for frame in fit:
                        if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == 'file_id':
                            # The 'time_created' field usually holds the activity start time
                            if frame.has_field('time_created'):
                                timestamp = frame.get_value('time_created')
                                # Ensure timestamp is timezone-aware (UTC) before getting date
                                if isinstance(timestamp, datetime):
                                     if timestamp.tzinfo is None:
                                         timestamp = timestamp.replace(tzinfo=timezone.utc)
                                     else:
                                         timestamp = timestamp.astimezone(timezone.utc)
                                     file_date_str = timestamp.strftime('%Y-%m-%d')
                                     break # Found file_id with time_created
                    # Fallback: If no file_id found, maybe use file modification time? Less reliable.
                    # if not file_date_str:
                    #     mtime = os.path.getmtime(filepath)
                    #     file_date_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')

                if file_date_str:
                    files_details.append({"filename": filename, "date": file_date_str})
                else:
                     print(f"Warning: Could not determine date for {filename}.")

            except fitdecode.FitError as e:
                print(f"Warning: Could not read {filename} to get date (FitError: {e}). Skipping.")
            except Exception as e:
                print(f"Warning: Could not process {filename} to get date (Error: {e}). Skipping.")

    # Sort files by date descending (most recent first)
    files_details.sort(key=lambda x: x.get('date', '0000-00-00'), reverse=True)
    print(f"Found {len(files_details)} FIT files with dates.")
    return files_details

def _perform_power_curve_calculation(records_data):
    """
    Performs the power curve calculation using pandas on aggregated records data.

    Args:
        records_data (list): List of dictionaries [{'timestamp': dt, 'power': W}, ...].

    Returns:
        dict: A dictionary {duration_sec: max_avg_power_watts} or None if error/no data.
    """
    if not records_data:
        print("Internal: No records data provided to _perform_power_curve_calculation.")
        # Return empty dict for consistency in tests, API endpoint can return 404/error
        return {}

    max_average_power = {}
    try:
        df = pd.DataFrame(records_data)
        # Ensure timestamp is datetime and power is numeric
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
        df['power'] = pd.to_numeric(df['power'], errors='coerce')
        # Drop rows where conversion failed
        df = df.dropna(subset=['timestamp', 'power'])

        if df.empty:
             print("Internal: Data invalid or empty after cleaning in _perform_power_curve_calculation.")
             # Return empty dict if no valid data remains
             return {}

        # Sort by timestamp (crucial for rolling calculations)
        df = df.set_index('timestamp').sort_index()

        # Define Power Curve Window Durations (in seconds)
        window_durations = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                            12, 15, 20, 30, 45,
                            60, 75, 90, 120, 150, 180,
                            240, 300, 420, 600, 900,
                            1200, 1800, 2700, 3600, 5400]

        for duration_sec in window_durations:
            window_str = f'{duration_sec}s'
            rolling_mean = df['power'].rolling(window_str, min_periods=1, closed='right').mean()
            max_power = rolling_mean.max()

            if pd.notna(max_power):
                 # Store results with integer keys for consistency
                 max_average_power[duration_sec] = round(max_power, 1)
            # else:
                 # We don't store None for durations where calculation wasn't possible or resulted in NaN
                 # max_average_power[duration_sec] = None

        # print("Internal: Power curve calculation complete.") # Optional debug print
        return max_average_power

    except Exception as e:
        print(f"Internal: An error occurred during pandas processing in _perform_power_curve_calculation: {e}")
        # Return None on unexpected errors during calculation
        return None


def calculate_aggregate_power_curve(file_paths):
    """
    Processes multiple FIT files, aggregates their 'record' data,
    and calculates the max average power curve by calling the helper function.

    Args:
        file_paths (list): A list of full paths to the .fit files to process.

    Returns:
        dict: A dictionary {duration_sec: max_avg_power_watts} or None if error/no data.
    """
    all_records_data = []
    total_records_processed = 0

    print(f"Processing {len(file_paths)} files for power curve...")
    for filepath in file_paths:
        try:
            # print(f"  Reading: {os.path.basename(filepath)}") # Optional debug print
            with fitdecode.FitReader(filepath) as fit:
                file_record_count = 0
                for frame in fit:
                    if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == 'record':
                        timestamp = frame.get_value('timestamp', fallback=None)
                        power = frame.get_value('power', fallback=None)

                        if timestamp is not None and power is not None:
                            if not isinstance(timestamp, datetime):
                                print(f"Warning: Invalid timestamp type in {os.path.basename(filepath)}. Skipping record.")
                                continue
                            all_records_data.append({'timestamp': timestamp, 'power': power})
                            file_record_count += 1
                # print(f"    Found {file_record_count} records with timestamp & power.") # Optional debug print
                total_records_processed += file_record_count
        except fitdecode.FitError as e:
            print(f"Warning: Skipping {os.path.basename(filepath)} due to FitError: {e}")
        except Exception as e:
            print(f"Warning: Skipping {os.path.basename(filepath)} due to Error: {e}")

    if not all_records_data:
        print("No valid 'record' data found across selected files.")
        return None # Return None if no data was aggregated

    print(f"Total records aggregated: {total_records_processed}. Calculating power curve...")
    # Call the internal helper function to perform the calculation
    result = _perform_power_curve_calculation(all_records_data)

    # Check if calculation itself failed (returned None)
    if result is None:
        print("Power curve calculation failed.")
        return None
    # Check if calculation resulted in no valid data points
    if not result:
        print("Power curve calculation resulted in no data points.")
        # Return None to indicate no curve could be generated, distinct from calculation error
        return None

    print("Power curve calculation complete.")
    return result

# --- Flask Routes ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    # Renders the template file located in the 'templates' folder
    return render_template('index.html')

@app.route('/api/files', methods=['GET'])
def get_files():
    """API endpoint to get the list of FIT files and their dates."""
    details = get_fit_file_details(FIT_DIR)
    return jsonify(details)

@app.route('/api/powercurve', methods=['POST'])
def get_power_curve():
    """
    API endpoint to calculate the power curve for files within a date range.
    Expects JSON: {"startDate": "YYYY-MM-DD", "endDate": "YYYY-MM-DD"}
    """
    try:
        data = request.get_json()
        start_date_str = data.get('startDate')
        end_date_str = data.get('endDate')

        if not start_date_str or not end_date_str:
            return jsonify({"error": "Missing startDate or endDate"}), 400

        # Validate date format (optional but recommended)
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
             return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

        print(f"Received request for power curve between {start_date_str} and {end_date_str}")

        # Get all file details
        all_files = get_fit_file_details(FIT_DIR)
        selected_files_paths = []

        # Filter files by date range
        for file_info in all_files:
            try:
                file_date = datetime.strptime(file_info['date'], '%Y-%m-%d').date()
                if start_date <= file_date <= end_date:
                    selected_files_paths.append(os.path.join(FIT_DIR, file_info['filename']))
            except (ValueError, TypeError):
                 print(f"Warning: Could not parse date '{file_info.get('date')}' for {file_info.get('filename')}. Skipping file for date range check.")


        if not selected_files_paths:
            return jsonify({"error": "No FIT files found within the specified date range."}), 404 # Not Found

        # Calculate aggregate power curve
        power_curve_data = calculate_aggregate_power_curve(selected_files_paths)

        if power_curve_data is None:
            return jsonify({"error": "Failed to calculate power curve from selected files."}), 500 # Internal Server Error

        # Prepare data for JSON response (convert dict keys to strings if needed, though not strictly necessary here)
        # Filter out None values before sending to frontend
        valid_power_data = {str(k): v for k, v in power_curve_data.items() if v is not None}

        return jsonify(valid_power_data)

    except Exception as e:
        print(f"Error in /api/powercurve: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500


# --- Main Execution ---
if __name__ == '__main__':
    # Runs the Flask development server.
    # Debug=True allows automatic reloading on code changes and provides detailed error pages.
    # DO NOT use debug=True in a production environment.
    # Host='0.0.0.0' makes the server accessible on your network (use with caution).
    # Use '127.0.0.1' (default) to only allow connections from your own computer.
    print("Starting Flask server...")
    app.run(debug=True, host='127.0.0.1', port=5000)

