# app/services.py
"""Core helper functions for calculations, file processing etc."""

import os
import logging
import fitdecode
import pandas as pd
from datetime import datetime, timezone, date
from typing import List, Dict, Optional, Any, Union
from flask import current_app # Use current_app to access config safely

# Import db instance if needed for helpers that interact with DB directly
# from .extensions import db
# Import models if needed
# from .models import FitFile, User

# Type Definitions (can also live in a central types file)
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
                # Check for file_id message type
                if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == 'file_id':
                    # Check if the 'time_created' field exists in this message
                    if frame.has_field('time_created'):
                        timestamp = frame.get_value('time_created')
                        # Ensure it's a datetime object
                        if isinstance(timestamp, datetime):
                             # Ensure timezone awareness (assume UTC if naive)
                             if timestamp.tzinfo is None:
                                 timestamp = timestamp.replace(tzinfo=timezone.utc)
                             else:
                                 timestamp = timestamp.astimezone(timezone.utc)
                             activity_date = timestamp.date()
                             logger.debug(f"Extracted date {activity_date} from {os.path.basename(filepath)}")
                             break # Found the date, no need to process further frames
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
    # Use ALLOWED_EXTENSIONS from app config
    allowed_extensions = current_app.config.get('ALLOWED_EXTENSIONS', {'.fit'})
    return '.' in filename and \
           os.path.splitext(filename)[1].lower() in allowed_extensions

# --- Power Curve Calculation Helpers ---

def _perform_power_curve_calculation(records_data: List[RecordData]) -> Optional[PowerCurveData]:
    """Performs the power curve calculation using pandas on aggregated records data."""
    if not records_data:
        logger.warning("Internal: No records data provided to _perform_power_curve_calculation.")
        return {} # Return empty dict for no data

    max_average_power: PowerCurveData = {}
    logger.info(f"Starting power curve calculation on {len(records_data)} records.")
    try:
        # Create DataFrame efficiently
        df = pd.DataFrame.from_records(records_data, columns=['timestamp', 'power'])
        logger.debug("DataFrame created.")

        # Convert types, handling errors
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
        df['power'] = pd.to_numeric(df['power'], errors='coerce')
        logger.debug("Types converted.")

        # Drop invalid rows
        initial_rows = len(df)
        df = df.dropna(subset=['timestamp', 'power'])
        dropped_rows = initial_rows - len(df)
        if dropped_rows > 0:
            logger.warning(f"Dropped {dropped_rows} rows with invalid timestamp or power.")

        if df.empty:
             logger.warning("Internal: Data invalid or empty after cleaning in _perform_power_curve_calculation.")
             return {} # Return empty dict if no valid data remains

        # Set index and sort (crucial and potentially time-consuming)
        logger.debug("Setting and sorting index...")
        df = df.set_index('timestamp').sort_index()
        logger.debug("Index set and sorted.")

        # Define Power Curve Window Durations (in seconds)
        window_durations: List[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                                       12, 15, 20, 30, 45,
                                       60, 75, 90, 120, 150, 180,
                                       240, 300, 420, 600, 900,
                                       1200, 1800, 2700, 3600, 5400]

        logger.debug(f"Calculating rolling means for {len(window_durations)} durations...")
        # Pre-calculate rolling means for all durations if memory allows, might be faster
        # Or calculate one by one
        for duration_sec in window_durations:
            window_str: str = f'{duration_sec}s'
            # Ensure power column is float for mean calculation
            rolling_mean = df['power'].astype('float64').rolling(window_str, min_periods=1, closed='right').mean()
            max_power = rolling_mean.max() # Find max average for this window duration

            if pd.notna(max_power):
                 max_average_power[duration_sec] = round(float(max_power), 1)
        logger.debug("Rolling means calculated.")

        return max_average_power

    except Exception as e:
        logger.error(f"Internal: An error occurred during pandas processing: {e}", exc_info=True)
        return None # Return None on unexpected calculation errors


def calculate_aggregate_power_curve(file_paths: List[str]) -> Optional[PowerCurveData]:
    """Processes multiple FIT files, aggregates 'record' data, and calculates power curve."""
    all_records_data: List[RecordData] = []
    total_records_processed: int = 0
    logger.info(f"Aggregating records from {len(file_paths)} files...")

    for filepath in file_paths:
        basename: str = os.path.basename(filepath)
        if not os.path.isfile(filepath):
            logger.warning(f"File not found during aggregation: {filepath}. Skipping.")
            continue
        try:
            logger.debug(f"  Reading records from: {basename}")
            with fitdecode.FitReader(filepath) as fit:
                file_record_count: int = 0
                for frame in fit:
                    if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == 'record':
                        # Use get_value for safer access, check types
                        timestamp = frame.get_value('timestamp', fallback=None)
                        power = frame.get_value('power', fallback=None)

                        if isinstance(timestamp, datetime) and power is not None:
                            try:
                                numeric_power = float(power) # Ensure power is numeric
                                all_records_data.append({'timestamp': timestamp, 'power': numeric_power})
                                file_record_count += 1
                            except (ValueError, TypeError):
                                logger.debug(f"Invalid power value ({power}) in {basename}. Skipping record.")
                        # else: logger.debug(f"Record missing timestamp or power in {basename}") # Too verbose potentially

                logger.debug(f"    Found {file_record_count} valid records in {basename}.")
                total_records_processed += file_record_count
        except fitdecode.FitError as e:
            logger.warning(f"Skipping {basename} due to FitError: {e}")
        except Exception as e:
            logger.error(f"Skipping {basename} due to unexpected Error: {e}", exc_info=True)

    if not all_records_data:
        logger.warning("No valid 'record' data found across selected files for aggregation.")
        return None # Return None if no data was aggregated

    logger.info(f"Total records aggregated: {total_records_processed}. Calculating final power curve...")
    result = _perform_power_curve_calculation(all_records_data) # Call the pandas helper

    if result is None:
        logger.error("Power curve calculation failed (returned None).")
        return None
    if not result: # Empty dict means calculation ran but yielded no points
        logger.warning("Power curve calculation resulted in no data points.")
        return None # Indicate no curve generated

    logger.info("Power curve calculation complete.")
    return result

