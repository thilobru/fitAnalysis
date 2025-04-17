# app/analysis/routes.py
"""Blueprint for analysis API routes (e.g., power curve)."""

import os
import logging
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date
from typing import Optional, Dict, Any, Tuple, List

# Import db instance and models
from ..extensions import db
from ..models import FitFile, User

# Import calculation service function
from ..services import calculate_aggregate_power_curve, PowerCurveData

logger = logging.getLogger(__name__)
# Create Blueprint instance with URL prefix
bp = Blueprint('analysis', __name__, url_prefix='/api')

@bp.route('/powercurve', methods=['POST'])
@login_required
def get_user_power_curve() -> Tuple[str, int] | str :
    """
    API endpoint to calculate power curve for the logged-in user's files
    within a specified date range.
    """
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
        files_to_process_query = current_user.fit_files.filter(
                FitFile.activity_date >= start_date,
                FitFile.activity_date <= end_date
                # Optional: Add status filter, e.g., FitFile.processing_status == 'complete'
            )
        files_to_process = files_to_process_query.all()

        if not files_to_process:
            logger.info(f"No FIT files with activity dates found for user {user_id} in range {start_date_str} to {end_date_str}.")
            return jsonify({}), 200 # OK, but no data

        # Construct full paths and check existence
        file_paths: List[str] = [f.get_full_path() for f in files_to_process]
        existing_file_paths = [p for p in file_paths if os.path.isfile(p)]

        if not existing_file_paths:
             logger.warning(f"No files found on filesystem for user {user_id} in range {start_date_str} to {end_date_str}, though DB records exist.")
             return jsonify({"error": "Files associated with this date range not found on server."}), 404

        if len(existing_file_paths) < len(file_paths):
             logger.warning(f"Missing {len(file_paths) - len(existing_file_paths)} files on filesystem for user {user_id} in range.")

        # Call the calculation function (imported from services)
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

