# app/analysis/routes.py
"""Blueprint for analysis API routes (e.g., power curve)."""

import os
import logging
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date
from typing import Optional, Dict, Any, Tuple, List
from sqlalchemy import func # For aggregation functions like max()

# Import db instance and models
from ..extensions import db
from ..models import FitFile, PowerCurvePoint, User # Import PowerCurvePoint

# REMOVED import of calculate_aggregate_power_curve
# from ..services import calculate_aggregate_power_curve, PowerCurveData

logger = logging.getLogger(__name__)
# Create Blueprint instance with URL prefix
bp = Blueprint('analysis', __name__, url_prefix='/api')

@bp.route('/powercurve', methods=['POST'])
@login_required
def get_user_power_curve() -> Tuple[str, int] | str :
    """
    API endpoint to calculate aggregate power curve for the logged-in user's
    processed files within a specified date range using pre-calculated data.
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

    logger.info(f"Aggregating pre-calculated power curve for user {user_id} between {start_date_str} and {end_date_str}")
    try:
        # --- Query pre-calculated data ---
        # 1. Find FitFile IDs for the user/date range that are processed
        processed_file_ids_query = db.session.query(FitFile.id).filter(
            FitFile.user_id == user_id,
            FitFile.activity_date >= start_date,
            FitFile.activity_date <= end_date,
            FitFile.processing_status == 'processed' # Only include processed files
        )
        processed_file_ids = [item[0] for item in processed_file_ids_query.all()]

        if not processed_file_ids:
            logger.info(f"No processed FIT files found for user {user_id} in range {start_date_str} to {end_date_str}.")
            return jsonify({}), 200 # OK, but no data

        logger.debug(f"Found {len(processed_file_ids)} processed files in range.")

        # 2. Query PowerCurvePoint table for points belonging to these files
        #    Group by duration and find the maximum power for each duration.
        #    func.max() comes from sqlalchemy
        aggregated_power_query = db.session.query(
            PowerCurvePoint.duration_seconds,
            func.max(PowerCurvePoint.max_power_watts).label('max_power')
        ).filter(
            PowerCurvePoint.fit_file_id.in_(processed_file_ids) # Filter by relevant file IDs
        ).group_by(
            PowerCurvePoint.duration_seconds # Group by duration
        ).order_by(
            PowerCurvePoint.duration_seconds # Order by duration
        )

        aggregated_results = aggregated_power_query.all()
        # --- End Query ---

        if not aggregated_results:
             logger.warning(f"No power curve points found for processed files {processed_file_ids} for user {user_id}.")
             return jsonify({}), 200 # OK, but no power data found

        # Convert results to the desired JSON format { "duration": power }
        final_power_curve = {str(duration): round(power, 1) for duration, power in aggregated_results}

        logger.info(f"Successfully aggregated power curve for user {user_id} using data from {len(processed_file_ids)} files.")
        return jsonify(final_power_curve), 200

    except Exception as e:
        logger.exception(f"Unexpected error during power curve aggregation for user {user_id}")
        return jsonify({"error": "An internal server error occurred during calculation."}), 500
