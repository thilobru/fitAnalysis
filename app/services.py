# app/services.py
"""Core helper functions for calculations, file processing etc."""

import os
import logging
import fitdecode
import pandas as pd
from datetime import datetime, timezone, date, timedelta # Added timedelta
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
    """
    Performs the power curve calculation using pandas on records data.
    Assumes records_data is sorted by timestamp and includes 0-power gap records.
    """
    if not records_data:
        logger.warning("Internal: No records data provided to _perform_power_curve_calculation.")
        return {} # Return empty dict for no data

    max_average_power: PowerCurveData = {}
    logger.info(f"Starting power curve calculation on {len(records_data)} records (incl. gap-fills).")
    try:
        # Create DataFrame directly from records_data which should be pre-sorted
        # and have timestamps as datetime objects.
        df = pd.DataFrame.from_records(records_data, columns=['timestamp', 'power'])
        logger.debug("DataFrame created from records_data.")

        # Ensure timestamp is datetime and set as index
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
        df['power'] = pd.to_numeric(df['power'], errors='coerce')
        
        initial_rows = len(df)
        df = df.dropna(subset=['timestamp', 'power']) # Drop rows if conversion failed
        dropped_rows = initial_rows - len(df)
        if dropped_rows > 0:
            logger.warning(f"Dropped {dropped_rows} rows with invalid timestamp or power during DataFrame processing.")

        if df.empty:
             logger.warning("Internal: Data invalid or empty after cleaning in _perform_power_curve_calculation.")
             return {}

        logger.debug("Setting and sorting index...")
        df = df.set_index('timestamp').sort_index() # Sort again just in case, though input should be sorted
        logger.debug("Index set and sorted.")


        # Resample to 1-second frequency. This will forward-fill power during actual recording gaps
        # if the device only records on change, but our inserted 0-power points will override this for longer breaks.
        # However, for the rolling calculation, we need a consistent time series.
        # If we have already inserted 0-power records for gaps > 2s, this resampling
        # might not be strictly necessary for those gaps, but it ensures a regular time index
        # for pandas rolling operations which expect it.
        # Let's test the impact of this. The primary gap filling is done before this function.
        # For now, we rely on the pre-filled gaps and pandas' ability to handle the irregular series
        # with time-based window strings.

        window_durations: List[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                                       12, 15, 20, 30, 45,
                                       60, 75, 90, 120, 150, 180,
                                       240, 300, 420, 600, 900,
                                       1200, 1800, 2700, 3600, 5400]

        logger.debug(f"Calculating rolling means for {len(window_durations)} durations...")
        for duration_sec in window_durations:
            window_str: str = f'{duration_sec}s'
            # closed='right' means the window includes the current point and looks back.
            # For power curves, this is standard: max power for the *preceding* X seconds.
            rolling_mean = df['power'].astype('float64').rolling(window_str, min_periods=duration_sec, closed='right').mean()
            max_power = rolling_mean.max()

            if pd.notna(max_power):
                 max_average_power[duration_sec] = round(float(max_power), 3)
        logger.debug("Rolling means calculated.")

        return max_average_power

    except Exception as e:
        logger.error(f"Internal: An error occurred during pandas processing in _perform_power_curve_calculation: {e}", exc_info=True)
        return None

# --- NEW: Function to process a single file and save its power curve ---
def calculate_and_save_single_file_power_curve(file_id: int) -> bool:
    """
    Calculates the power curve for a single FitFile, saves the results
    to the PowerCurvePoint table, and updates the FitFile status.
    This version inserts zero-power records for time gaps > 2 seconds.
    """
    logger.info(f"Starting single file power curve calculation for FitFile ID: {file_id}")
    fit_file = db.session.get(FitFile, file_id)

    if not fit_file:
        logger.error(f"FitFile ID {file_id} not found in database.")
        return False

    fit_file.processing_status = 'processing'
    db.session.add(fit_file)
    db.session.commit() 

    file_path = fit_file.get_full_path()
    if not os.path.isfile(file_path):
        logger.error(f"File not found on filesystem for FitFile ID {file_id}: {file_path}")
        fit_file.processing_status = 'analysis_failed'
        db.session.add(fit_file)
        db.session.commit()
        return False

    raw_records_data: List[RecordData] = []
    try:
        logger.debug(f"Reading records from: {fit_file.original_filename} (ID: {file_id})")
        with fitdecode.FitReader(file_path) as fit:
            for frame in fit:
                if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == 'record':
                    timestamp_val = frame.get_value('timestamp', fallback=None)
                    power_val = frame.get_value('power', fallback=None)
                    
                    if isinstance(timestamp_val, datetime) and power_val is not None:
                        # Ensure timestamp is timezone-aware (UTC)
                        if timestamp_val.tzinfo is None:
                            timestamp_val = timestamp_val.replace(tzinfo=timezone.utc)
                        else:
                            timestamp_val = timestamp_val.astimezone(timezone.utc)
                        
                        try:
                            numeric_power = float(power_val)
                            raw_records_data.append({'timestamp': timestamp_val, 'power': numeric_power})
                        except (ValueError, TypeError):
                            logger.warning(f"Skipping record with invalid power value '{power_val}' at {timestamp_val} for file {file_id}")
                            pass 
        
        # Sort records by timestamp, essential for gap detection
        raw_records_data.sort(key=lambda r: r['timestamp'])
        logger.debug(f"Found and sorted {len(raw_records_data)} raw records for FitFile ID {file_id}.")

        # --- START: Gap Filling Logic ---
        processed_records_data: List[RecordData] = []
        if not raw_records_data:
            logger.warning(f"No valid record data found in FitFile ID {file_id} before gap filling.")
            # Proceed with empty list, will be handled later
        else:
            processed_records_data.append(raw_records_data[0]) # Add the first record
            for i in range(len(raw_records_data) - 1):
                current_record_time = raw_records_data[i]['timestamp']
                next_record_time = raw_records_data[i+1]['timestamp']
                time_diff_seconds = (next_record_time - current_record_time).total_seconds()

                if time_diff_seconds > 1.0: # Gap detected (e.g., more than 1 seconds)
                    logger.debug(f"Gap detected: {time_diff_seconds:.1f}s between {current_record_time} and {next_record_time} for file {file_id}")
                    # Insert 0-power records for each second in the gap, starting from
                    # current_record_time + 1s up to next_record_time - 1s.
                    # The current record raw_records_data[i] is already added or will be.
                    # The next actual record raw_records_data[i+1] will be added in the next iteration's start.

                    # Start filling from the second after the current record's timestamp
                    fill_time = current_record_time + timedelta(seconds=1)
                    while fill_time < next_record_time:
                        # Only add if the fill_time is at least 1s before next_record_time to avoid duplicate timestamps
                        # if next_record_time is exactly current_record_time + 2s + epsilon
                        if (next_record_time - fill_time).total_seconds() >= 1.0:
                             processed_records_data.append({'timestamp': fill_time, 'power': 0.0})
                        fill_time += timedelta(seconds=1)
                
                processed_records_data.append(raw_records_data[i+1]) # Add the next actual record
            
            # Deduplicate if any exact timestamp duplicates were created (e.g. by gap filling logic)
            # This is a safeguard. Ideally, gap filling logic should avoid creating exact duplicates.
            if processed_records_data:
                final_unique_records = []
                seen_timestamps = set()
                for record in processed_records_data:
                    if record['timestamp'] not in seen_timestamps:
                        final_unique_records.append(record)
                        seen_timestamps.add(record['timestamp'])
                processed_records_data = final_unique_records
                logger.debug(f"Gap filling complete. Total records for processing: {len(processed_records_data)} for file {file_id}")

        # --- END: Gap Filling Logic ---

        if not processed_records_data: # Check after gap filling
             logger.warning(f"No valid record data (even after gap fill attempt) for FitFile ID {file_id}. Marking as processed (empty).")
             PowerCurvePoint.query.filter_by(fit_file_id=file_id).delete()
             fit_file.processing_status = 'processed' 
             db.session.add(fit_file)
             db.session.commit()
             return True 

        # Calculate power curve using the (potentially gap-filled) data
        power_curve_data: Optional[PowerCurveData] = _perform_power_curve_calculation(processed_records_data)

        if power_curve_data is None: 
            raise Exception("Power curve calculation returned None, indicating an internal error.")
        if not power_curve_data: 
             logger.warning(f"Power curve calculation resulted in no data points for FitFile ID {file_id}. Marking as processed.")
             PowerCurvePoint.query.filter_by(fit_file_id=file_id).delete()
             fit_file.processing_status = 'processed'
             db.session.add(fit_file)
             db.session.commit()
             return True 

        PowerCurvePoint.query.filter_by(fit_file_id=file_id).delete()
        logger.debug(f"Deleted old power curve points for FitFile ID {file_id} (if any).")

        new_points = []
        for duration, power in power_curve_data.items():
            new_points.append(PowerCurvePoint(
                fit_file_id=file_id,
                duration_seconds=duration,
                max_power_watts=power
            ))

        if new_points:
            db.session.bulk_save_objects(new_points) 
            logger.info(f"Saved {len(new_points)} power curve points for FitFile ID {file_id}.")

        fit_file.processing_status = 'processed'
        db.session.add(fit_file)
        db.session.commit()
        logger.info(f"Successfully processed and saved power curve for FitFile ID: {file_id}")
        return True

    except fitdecode.FitError as fe:
        db.session.rollback() 
        logger.error(f"FitDecodeError processing FitFile ID {file_id}: {fe}")
        fit_file = db.session.get(FitFile, file_id) 
        if fit_file:
            fit_file.processing_status = 'analysis_failed'
            db.session.add(fit_file)
            db.session.commit()
        return False
    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected error processing FitFile ID {file_id}: {e}", exc_info=True)
        fit_file = db.session.get(FitFile, file_id) 
        if fit_file:
            fit_file.processing_status = 'analysis_failed'
            db.session.add(fit_file)
            db.session.commit()
        return False
    