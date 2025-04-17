# app/services.py
"""Core helper functions for calculations, file processing etc."""

import os
import logging
import fitdecode
import pandas as pd
from datetime import datetime, timezone, date
from typing import List, Dict, Optional, Any, Union
from flask import current_app # Use current_app to access config safely

# Import db instance and models
from .extensions import db
from .models import FitFile, PowerCurvePoint # Import new model

# Type Definitions
RecordData = Dict[str, Union[datetime, int, float, str, None]]
PowerCurveData = Dict[int, float]

logger = logging.getLogger(__name__)

# --- File Handling Helpers ---

def _extract_activity_date(filepath: str) -> Optional[date]:
    """Extracts the activity date from a FIT file's file_id message."""
    activity_date: Optional[date] = None
    logger.debug(f"Attempting to extract date from: {filepath}")
    if not os.path.isfile(filepath):
        logger.warning(f"File not found during date extraction: {filepath}")
        return None
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
                             logger.debug(f"Extracted date {activity_date} from {os.path.basename(filepath)}")
                             break
            if not activity_date:
                 logger.warning(f"No 'time_created' field found in file_id message for {os.path.basename(filepath)}")
        return activity_date
    except fitdecode.FitError as fe:
         logger.error(f"FitDecodeError extracting date from {os.path.basename(filepath)}: {fe}")
         return None
    except Exception as e:
        logger.error(f"Unexpected error extracting date from {os.path.basename(filepath)}: {e}", exc_info=True)
        return None

def _allowed_file(filename: str) -> bool:
    """Checks if the filename has an allowed extension."""
    allowed_extensions = current_app.config.get('ALLOWED_EXTENSIONS', {'.fit'})
    return '.' in filename and \
           os.path.splitext(filename)[1].lower() in allowed_extensions

# --- Power Curve Calculation Helpers ---

def _perform_power_curve_calculation(records_data: List[RecordData]) -> Optional[PowerCurveData]:
    """Performs the power curve calculation using pandas on records data."""
    # (Keep this function as is - it calculates the curve from a list of records)
    if not records_data:
        logger.warning("Internal: No records data provided to _perform_power_curve_calculation.")
        return {} # Return empty dict for no data

    max_average_power: PowerCurveData = {}
    logger.info(f"Starting power curve calculation on {len(records_data)} records.")
    try:
        df = pd.DataFrame.from_records(records_data, columns=['timestamp', 'power'])
        logger.debug("DataFrame created.")

        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
        df['power'] = pd.to_numeric(df['power'], errors='coerce')
        logger.debug("Types converted.")

        initial_rows = len(df)
        df = df.dropna(subset=['timestamp', 'power'])
        dropped_rows = initial_rows - len(df)
        if dropped_rows > 0:
            logger.warning(f"Dropped {dropped_rows} rows with invalid timestamp or power.")

        if df.empty:
             logger.warning("Internal: Data invalid or empty after cleaning in _perform_power_curve_calculation.")
             return {}

        logger.debug("Setting and sorting index...")
        df = df.set_index('timestamp').sort_index()
        logger.debug("Index set and sorted.")

        window_durations: List[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                                       12, 15, 20, 30, 45,
                                       60, 75, 90, 120, 150, 180,
                                       240, 300, 420, 600, 900,
                                       1200, 1800, 2700, 3600, 5400]

        logger.debug(f"Calculating rolling means for {len(window_durations)} durations...")
        for duration_sec in window_durations:
            window_str: str = f'{duration_sec}s'
            rolling_mean = df['power'].astype('float64').rolling(window_str, min_periods=1, closed='right').mean()
            max_power = rolling_mean.max()

            if pd.notna(max_power):
                 max_average_power[duration_sec] = round(float(max_power), 1)
        logger.debug("Rolling means calculated.")

        return max_average_power

    except Exception as e:
        logger.error(f"Internal: An error occurred during pandas processing: {e}", exc_info=True)
        return None

# --- NEW: Function to process a single file and save its power curve ---
def calculate_and_save_single_file_power_curve(file_id: int) -> bool:
    """
    Calculates the power curve for a single FitFile, saves the results
    to the PowerCurvePoint table, and updates the FitFile status.

    Args:
        file_id: The ID of the FitFile to process.

    Returns:
        True if processing was successful, False otherwise.
    """
    logger.info(f"Starting single file power curve calculation for FitFile ID: {file_id}")
    fit_file = db.session.get(FitFile, file_id)

    if not fit_file:
        logger.error(f"FitFile ID {file_id} not found in database.")
        return False

    # Update status to 'processing'
    fit_file.processing_status = 'processing'
    db.session.add(fit_file)
    db.session.commit() # Commit status change immediately

    file_path = fit_file.get_full_path()
    if not os.path.isfile(file_path):
        logger.error(f"File not found on filesystem for FitFile ID {file_id}: {file_path}")
        fit_file.processing_status = 'analysis_failed'
        db.session.add(fit_file)
        db.session.commit()
        return False

    records_data: List[RecordData] = []
    try:
        logger.debug(f"Reading records from: {fit_file.original_filename} (ID: {file_id})")
        with fitdecode.FitReader(file_path) as fit:
            for frame in fit:
                if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == 'record':
                    timestamp = frame.get_value('timestamp', fallback=None)
                    power = frame.get_value('power', fallback=None)
                    if isinstance(timestamp, datetime) and power is not None:
                        try:
                            numeric_power = float(power)
                            records_data.append({'timestamp': timestamp, 'power': numeric_power})
                        except (ValueError, TypeError):
                            pass # Ignore invalid power values in single file processing

        logger.debug(f"Found {len(records_data)} valid records for FitFile ID {file_id}.")

        if not records_data:
             logger.warning(f"No valid record data found in FitFile ID {file_id}. Marking as processed (empty).")
             # Delete potentially existing old points if reprocessing
             PowerCurvePoint.query.filter_by(fit_file_id=file_id).delete()
             fit_file.processing_status = 'processed' # Mark as processed even if empty
             db.session.add(fit_file)
             db.session.commit()
             return True # Technically successful, just no data

        # Calculate power curve for this file's data
        power_curve_data: Optional[PowerCurveData] = _perform_power_curve_calculation(records_data)

        if power_curve_data is None: # Indicates an internal calculation error
            raise Exception("Power curve calculation returned None, indicating an internal error.")
        if not power_curve_data: # Empty dict means calculation ran but no points (e.g., <1s duration)
             logger.warning(f"Power curve calculation resulted in no data points for FitFile ID {file_id}. Marking as processed.")
             # Delete potentially existing old points if reprocessing
             PowerCurvePoint.query.filter_by(fit_file_id=file_id).delete()
             fit_file.processing_status = 'processed'
             db.session.add(fit_file)
             db.session.commit()
             return True # Successful calculation, even if result is empty

        # Save the calculated points to the database
        # Delete potentially existing old points first (important if reprocessing)
        PowerCurvePoint.query.filter_by(fit_file_id=file_id).delete()
        logger.debug(f"Deleted old power curve points for FitFile ID {file_id} (if any).")

        # Add new points
        new_points = []
        for duration, power in power_curve_data.items():
            new_points.append(PowerCurvePoint(
                fit_file_id=file_id,
                duration_seconds=duration,
                max_power_watts=power
            ))

        if new_points:
            db.session.bulk_save_objects(new_points) # Efficiently add multiple points
            logger.info(f"Saved {len(new_points)} power curve points for FitFile ID {file_id}.")

        # Update status to 'processed'
        fit_file.processing_status = 'processed'
        db.session.add(fit_file)
        db.session.commit()
        logger.info(f"Successfully processed and saved power curve for FitFile ID: {file_id}")
        return True

    except fitdecode.FitError as fe:
        db.session.rollback() # Rollback any partial saves
        logger.error(f"FitDecodeError processing FitFile ID {file_id}: {fe}")
        fit_file = db.session.get(FitFile, file_id) # Re-fetch after rollback
        if fit_file:
            fit_file.processing_status = 'analysis_failed'
            db.session.add(fit_file)
            db.session.commit()
        return False
    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected error processing FitFile ID {file_id}: {e}", exc_info=True)
        fit_file = db.session.get(FitFile, file_id) # Re-fetch after rollback
        if fit_file:
            fit_file.processing_status = 'analysis_failed'
            db.session.add(fit_file)
            db.session.commit()
        return False
